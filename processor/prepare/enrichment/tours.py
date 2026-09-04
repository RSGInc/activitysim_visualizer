"""Tour enrichment stage for prepared tables."""

from __future__ import annotations

from runtime.logging import get_logger
import polars as pl

from processor.tour_purpose import with_summary_tour_purpose
from processor.prepare.enrichment.autosuff import (
    apply_autosufficiency,
    autosuff_reference_column,
)
from processor.prepare.enrichment.columns import _resolve_source_column
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from processor.prepare.enrichment.zones import (
    _add_aggregated_geography,
    _nullable_float_numpy,
    _record_prepare_metric,
    _skim_lookup,
    _skim_series,
    _to_taz,
)
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _identifier_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Float64, strict=False)
        .cast(pl.Int64, strict=False)
        .cast(pl.Utf8)
    )


def _canonical_tour_origins(tours: pl.DataFrame, hh: pl.DataFrame) -> pl.DataFrame:
    if tours.is_empty() or "origin" not in tours.columns:
        return tours

    result = tours
    if {"household_id", "home_zone_id"}.issubset(hh.columns) and "household_id" in result.columns:
        result = result.join(
            hh.select(
                "household_id",
                pl.col("home_zone_id").alias("_home_tour_origin"),
            ).unique("household_id"),
            on="household_id",
            how="left",
        )
    else:
        result = result.with_columns(pl.lit(None).alias("_home_tour_origin"))

    parent_origin_columns: list[str] = []
    for parent_id, tour_id in (
        ("parent_tour_id", "tour_id"),
        ("survey_parent_tour_id", "survey_tour_id"),
    ):
        if not {parent_id, tour_id, "destination"}.issubset(tours.columns):
            continue
        key_col = f"_parent_key_{len(parent_origin_columns)}"
        origin_col = f"_parent_tour_origin_{len(parent_origin_columns)}"
        parent_destinations = (
            tours.filter(pl.col(tour_id).is_not_null())
            .select(
                _identifier_expr(tour_id).alias(key_col),
                pl.col("destination").alias(origin_col),
            )
            .filter(pl.col(key_col).is_not_null())
            .unique(key_col)
        )
        result = (
            result.with_columns(_identifier_expr(parent_id).alias(key_col))
            .join(parent_destinations, on=key_col, how="left")
            .drop(key_col)
        )
        parent_origin_columns.append(origin_col)

    category = (
        pl.col("tour_category").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        if "tour_category" in result.columns
        else pl.lit("")
    )
    parent_origins = [pl.col(column) for column in parent_origin_columns]
    parent_origins.append(pl.col("origin"))
    result = result.with_columns(
        pl.when(category.is_in(["atwork", "at_work"]))
        .then(pl.coalesce(parent_origins))
        .otherwise(pl.coalesce("_home_tour_origin", "origin"))
        .alias("origin")
    )
    return result.drop(["_home_tour_origin", *parent_origin_columns])


def _derive_joint_composition(
    tours: pl.DataFrame,
    joint_participants: pl.DataFrame,
    persons: pl.DataFrame,
) -> pl.DataFrame:
    person_type_col = next(
        (
            column
            for column in ("person_type", "ptype", "PERTYPE")
            if column in persons.columns
        ),
        None,
    )
    age_col = next(
        (column for column in ("age", "age_app", "age_fv") if column in persons.columns),
        None,
    )
    if (
        tours.is_empty()
        or joint_participants.is_empty()
        or (person_type_col is None and age_col is None)
        or "person_id" not in persons.columns
        or "person_id" not in joint_participants.columns
    ):
        return tours

    adult_sources: list[pl.Expr] = []
    if person_type_col is not None:
        person_type = pl.col(person_type_col).cast(pl.Int64, strict=False)
        adult_sources.append(
            pl.when(person_type.is_between(1, 5))
            .then(pl.lit(True))
            .when(person_type.is_between(6, 8))
            .then(pl.lit(False))
            .otherwise(None)
        )
    if age_col is not None:
        age = pl.col(age_col).cast(pl.Float64, strict=False)
        adult_sources.append(
            pl.when(age.is_between(0, 994)).then(age >= 18).otherwise(None)
        )

    participant_adulthood = joint_participants.join(
        persons.select(
            "person_id",
            pl.coalesce(adult_sources).alias("_participant_is_adult"),
        ).unique("person_id"),
        on="person_id",
        how="left",
    ).filter(pl.col("_participant_is_adult").is_not_null())

    result = tours
    derived_columns: list[str] = []
    for identifier in ("joint_tour_id", "tour_id"):
        if identifier not in result.columns or identifier not in participant_adulthood.columns:
            continue
        key_col = f"_composition_key_{len(derived_columns)}"
        composition_col = f"_derived_composition_{len(derived_columns)}"
        compositions = (
            participant_adulthood.filter(pl.col(identifier).is_not_null())
            .with_columns(_identifier_expr(identifier).alias(key_col))
            .filter(pl.col(key_col).is_not_null())
            .unique([key_col, "person_id"])
            .group_by(key_col)
            .agg(
                pl.col("_participant_is_adult").min().alias("_all_adults"),
                pl.col("_participant_is_adult").max().alias("_any_adults"),
            )
            .with_columns(
                pl.when(pl.col("_all_adults"))
                .then(pl.lit("adults"))
                .when(~pl.col("_any_adults"))
                .then(pl.lit("children"))
                .otherwise(pl.lit("mixed"))
                .alias(composition_col)
            )
            .select(key_col, composition_col)
        )
        result = (
            result.with_columns(_identifier_expr(identifier).alias(key_col))
            .join(compositions, on=key_col, how="left")
            .drop(key_col)
        )
        derived_columns.append(composition_col)

    if not derived_columns:
        return result
    sources = []
    if "composition" in result.columns:
        sources.append(pl.col("composition").cast(pl.Utf8))
    sources.extend(pl.col(column) for column in derived_columns)
    return result.with_columns(pl.coalesce(sources).alias("composition")).drop(
        derived_columns
    )


def _enrich_tours(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
    autosuff_ref_col = autosuff_reference_column(config)
    state.tours = _canonical_tour_origins(state.tours, state.hh)
    hh_income_source = _resolve_source_column(state.hh, config.col_income_segment)
    if hh_income_source is not None:
        hh_income = state.hh.select(
            [
                pl.col("household_id"),
                pl.col(hh_income_source).alias("income_segment_hh"),
            ]
        )
        if "household_id" in state.tours.columns:
            state.tours = state.tours.join(hh_income, on="household_id", how="left")
            if "income_segment" in state.tours.columns:
                state.tours = state.tours.with_columns(
                    pl.coalesce(
                        [pl.col("income_segment"), pl.col("income_segment_hh")]
                    ).alias("income_segment")
                ).drop("income_segment_hh")
            else:
                state.tours = state.tours.rename(
                    {"income_segment_hh": "income_segment"}
                )

    hh_for_tours = [
        column
        for column in dict.fromkeys(
            [
                "household_id",
                "HHVEH",
                "WORKERS",
                "LICENSEDDRIVERS",
                "ADULTS",
                autosuff_ref_col,
            ]
        )
        if column in state.hh.columns
    ]
    if "household_id" in state.tours.columns and "household_id" in hh_for_tours:
        state.tours = state.tours.join(
            state.hh.select(hh_for_tours),
            on="household_id",
            how="left",
        )

    state.tours = apply_autosufficiency(
        state.tours,
        state=state,
        config=config,
        metric_id="tours.AUTOSUFF",
    )

    if "stop_frequency" in state.tours.columns:
        state.tours = state.tours.with_columns(
            [
                pl.col("stop_frequency")
                .cast(pl.Utf8)
                .str.split("out_")
                .list.first()
                .cast(pl.Int32)
                .alias("num_ob_stops"),
                pl.col("stop_frequency")
                .cast(pl.Utf8)
                .str.split("out_")
                .list.last()
                .str.replace("in", "", literal=True)
                .cast(pl.Int32)
                .alias("num_ib_stops"),
            ]
        ).with_columns(
            (pl.col("num_ob_stops") + pl.col("num_ib_stops")).alias("num_tot_stops")
        )

    if config.use_maz and {"origin", "destination"}.issubset(state.tours.columns):
        state.tours = state.tours.with_columns(
            pl.col("origin").alias("o_maz"),
            pl.col("destination").alias("d_maz"),
        )

    state.tours = _to_taz(
        state.tours,
        "origin",
        "OTAZ",
        state=state,
        metric_id="tours.OTAZ",
        config=config,
        zone_context=zone_context,
    )
    state.tours = _to_taz(
        state.tours,
        "destination",
        "DTAZ",
        state=state,
        metric_id="tours.DTAZ",
        config=config,
        zone_context=zone_context,
    )
    state.tours = _to_taz(
        state.tours,
        "pnr_zone_id",
        "pnr_taz",
        state=state,
        metric_id="tours.pnr_taz",
        config=config,
        zone_context=zone_context,
    )
    for aggregation in config.geography_aggregations.aggregations:
        origin_zone_col = "origin" if aggregation.source_zone_system == "maz" else "OTAZ"
        destination_zone_col = (
            "destination" if aggregation.source_zone_system == "maz" else "DTAZ"
        )
        state.tours = _add_aggregated_geography(
            state.tours,
            origin_zone_col,
            f"origin_geo__{aggregation.name}",
            aggregation_name=aggregation.name,
            source_zone_system=aggregation.source_zone_system,
            zone_context=zone_context,
        )
        state.tours = _add_aggregated_geography(
            state.tours,
            destination_zone_col,
            f"destination_geo__{aggregation.name}",
            aggregation_name=aggregation.name,
            source_zone_system=aggregation.source_zone_system,
            zone_context=zone_context,
        )

    if (
        state.skim is not None
        and "OTAZ" in state.tours.columns
        and "DTAZ" in state.tours.columns
    ):
        LOGGER.info(
            "[prepare_data] Computing tour skim distances for '%s'", state.label
        )
        o = _nullable_float_numpy(state.tours["OTAZ"])
        d = _nullable_float_numpy(state.tours["DTAZ"])
        dist = _skim_lookup(state.skim, o, d, state.skim_map)
        state.tours = state.tours.with_columns(
            _skim_series("SKIMDIST", dist)
        )
        total = state.tours.filter(
            pl.col("origin").is_not_null() & pl.col("destination").is_not_null()
        ).height
        unresolved = state.tours.filter(
            pl.col("origin").is_not_null()
            & pl.col("destination").is_not_null()
            & pl.col("SKIMDIST").is_null()
        ).height
        _record_prepare_metric(
            state,
            "tours.SKIMDIST",
            total=total,
            unresolved=unresolved,
        )
    elif "SKIMDIST" not in state.tours.columns:
        LOGGER.info(
            "[prepare_data] Tour skim distances unavailable for '%s'; leaving SKIMDIST absent.",
            state.label,
        )

    if "SKIMDIST" in state.tours.columns:
        if "tour_distance" in state.tours.columns:
            state.tours = state.tours.with_columns(
                pl.coalesce(
                    pl.col("tour_distance").cast(pl.Float64, strict=False),
                    pl.col("SKIMDIST"),
                ).alias("tour_distance")
            )

    number_hh_sources: list[pl.Expr] = []
    participant_count_col = "_joint_participant_count"
    if (
        "tour_id" in state.tours.columns
        and "tour_id" in state.joint_participants.columns
        and state.joint_participants.schema.get("tour_id") != pl.Null
    ):
        party_size = state.joint_participants.group_by("tour_id").agg(
            pl.len().cast(pl.Int64).alias(participant_count_col)
        )
        state.tours = state.tours.join(party_size, on="tour_id", how="left")
        number_hh_sources.append(pl.col(participant_count_col))
    if "number_of_participants" in state.tours.columns:
        number_hh_sources.append(
            pl.col("number_of_participants").cast(pl.Int64, strict=False)
        )
    if "NUMBER_HH" in state.tours.columns:
        number_hh_sources.append(pl.col("NUMBER_HH").cast(pl.Int64, strict=False))
    number_hh_sources.append(pl.lit(1, dtype=pl.Int64))
    state.tours = state.tours.with_columns(
        pl.coalesce(number_hh_sources).alias("NUMBER_HH")
    )
    if participant_count_col in state.tours.columns:
        state.tours = state.tours.drop(participant_count_col)

    state.tours = _derive_joint_composition(
        state.tours,
        state.joint_participants,
        state.per,
    )

    if "start_hour" in state.tours.columns and "end_hour" in state.tours.columns:
        state.tours = state.tours.with_columns(
            (pl.col("end_hour") - pl.col("start_hour") + 1)
            .clip(1, 48)
            .alias("tourdur")
        )

    state.tours = _attach_first_inbound_trip_depart(state.tours, state.trips)

    state.tours = with_summary_tour_purpose(state.tours, config)

    return state


def _attach_first_inbound_trip_depart(
    tours: pl.DataFrame,
    trips: pl.DataFrame,
) -> pl.DataFrame:
    required_trip_columns = {"tour_id", "outbound", "trip_num", "depart_hour"}
    if "tour_id" not in tours.columns or not required_trip_columns.issubset(trips.columns):
        return tours

    first_inbound = (
        trips.filter(pl.col("outbound") == False)
        .sort(["tour_id", "trip_num"])
        .group_by("tour_id", maintain_order=True)
        .agg(pl.col("depart_hour").first().alias("first_inbound_trip_depart"))
    )
    if "first_inbound_trip_depart" in tours.columns:
        return (
            tours.join(
            first_inbound.rename(
                {"first_inbound_trip_depart": "__derived_first_inbound_trip_depart"}
            ),
            on="tour_id",
            how="left",
        ).with_columns(
            pl.coalesce(
                [
                    pl.col("first_inbound_trip_depart"),
                    pl.col("__derived_first_inbound_trip_depart"),
                ]
            ).alias("first_inbound_trip_depart")
        ).drop("__derived_first_inbound_trip_depart")
        )
    return tours.join(first_inbound, on="tour_id", how="left")
