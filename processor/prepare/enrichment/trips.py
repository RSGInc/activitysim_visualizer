"""Trip enrichment stage for prepared tables."""

from __future__ import annotations

from runtime.logging import get_logger
import numpy as np
import polars as pl

from processor.tour_purpose import with_summary_tour_purpose
from processor.prepare.enrichment.autosuff import (
    apply_autosufficiency,
    autosuff_reference_column,
)
from processor.prepare.enrichment.columns import _has_columns
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
_CHILD_PERSON_TYPES = {"6", "7", "8"}


def _escort_value_present_expr(column: str) -> pl.Expr:
    return (
        pl.col(column).is_not_null()
        & (pl.col(column).cast(pl.Utf8).str.to_lowercase().str.strip_chars() != "")
        & (pl.col(column).cast(pl.Utf8).str.to_lowercase().str.strip_chars() != "not_escorted")
    )


def _ensure_escort_event_columns(trips: pl.DataFrame) -> pl.DataFrame:
    derived_schema = {
        "escort_event_role": pl.Utf8,
        "escort_event_trip_num": pl.Int32,
        "escort_stops_before_event": pl.Int32,
        "escort_stops_after_event": pl.Int32,
        "escort_event_match_status": pl.Utf8,
    }
    expressions: list[pl.Expr] = []
    for column, dtype in derived_schema.items():
        if column not in trips.columns:
            expressions.append(pl.lit(None, dtype=dtype).alias(column))
    if not expressions:
        return trips
    return trips.with_columns(expressions)


def _derive_escort_event_position(state: _PrepareState) -> _PrepareState:
    state.trips = _ensure_escort_event_columns(state.trips)

    trip_required = {
        "person_id",
        "trip_num",
        "outbound",
        "escort_participants",
        "max_trip_num",
        "summary_tour_purpose",
    }
    if not trip_required.issubset(set(state.trips.columns)) or not {
        "person_id",
        "person_type",
    }.issubset(set(state.per.columns)):
        return state

    trip_purpose_col = "trip_purpose" if "trip_purpose" in state.trips.columns else None
    if trip_purpose_col is None:
        return state

    trips = state.trips.with_row_index("_trip_row_id").join(
        state.per.select(
            "person_id",
            pl.col("person_type").cast(pl.Utf8).alias("_person_type"),
        ),
        on="person_id",
        how="left",
    )
    trips = trips.with_columns(
        pl.when(pl.col("outbound").is_null())
        .then(None)
        .when(
            pl.col("outbound")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["false", "0"])
        )
        .then(False)
        .otherwise(True)
        .alias("_outbound_bool"),
        pl.col("summary_tour_purpose")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .alias("_summary_tour_purpose"),
        pl.col(trip_purpose_col).cast(pl.Utf8).str.to_lowercase().alias("_trip_purpose"),
    )

    adult_candidates = (
        trips.filter(
            pl.col("escort_participants").is_not_null()
            & pl.col("_person_type").is_not_null()
            & ~pl.col("_person_type").is_in(sorted(_CHILD_PERSON_TYPES))
            & (pl.col("_summary_tour_purpose") == "escort")
            & pl.col("_outbound_bool").is_not_null()
        )
        .with_columns(
            pl.when(pl.col("_outbound_bool"))
            .then(pl.lit("dropoff"))
            .otherwise(pl.lit("pickup"))
            .alias("_escort_event_role_candidate")
        )
    )
    if adult_candidates.is_empty():
        return state

    child_candidates = (
        trips.filter(
            pl.col("escort_participants").is_not_null()
            & pl.col("_person_type").is_not_null()
            & pl.col("_person_type").is_in(sorted(_CHILD_PERSON_TYPES))
            & pl.col("_outbound_bool").is_not_null()
            & (
                (
                    pl.col("_outbound_bool")
                    & (pl.col("_trip_purpose") == "school")
                )
                | (
                    (~pl.col("_outbound_bool"))
                    & (pl.col("_trip_purpose") == "home")
                )
            )
        )
        .with_columns(
            pl.when(pl.col("_outbound_bool"))
            .then(pl.lit("dropoff"))
            .otherwise(pl.lit("pickup"))
            .alias("_escort_event_role_candidate")
        )
    )

    match_keys = [
        "escort_participants",
        "_outbound_bool",
        "_escort_event_role_candidate",
    ]
    adult_counts = adult_candidates.group_by(match_keys).agg(
        pl.len().alias("_adult_match_count")
    )
    child_counts = child_candidates.group_by(match_keys).agg(
        pl.len().alias("_child_match_count")
    )

    derived = (
        adult_candidates.join(adult_counts, on=match_keys, how="left")
        .join(child_counts, on=match_keys, how="left")
        .with_columns(
            pl.when(
                (pl.col("_adult_match_count") == 1)
                & (pl.col("_child_match_count") == 1)
            )
            .then(pl.lit("matched"))
            .when(
                (pl.col("_adult_match_count") > 1)
                | (pl.col("_child_match_count") > 1)
            )
            .then(pl.lit("ambiguous"))
            .otherwise(pl.lit("unmatched"))
            .alias("escort_event_match_status"),
        )
        .with_columns(
            pl.when(pl.col("escort_event_match_status") == "matched")
            .then(pl.col("_escort_event_role_candidate"))
            .otherwise(None)
            .cast(pl.Utf8)
            .alias("escort_event_role"),
            pl.when(pl.col("escort_event_match_status") == "matched")
            .then(pl.col("trip_num"))
            .otherwise(None)
            .cast(pl.Int32)
            .alias("escort_event_trip_num"),
            pl.when(pl.col("escort_event_match_status") == "matched")
            .then(pl.col("trip_num") - 1)
            .otherwise(None)
            .cast(pl.Int32)
            .alias("escort_stops_before_event"),
            pl.when(pl.col("escort_event_match_status") == "matched")
            .then(pl.col("max_trip_num") - pl.col("trip_num"))
            .otherwise(None)
            .cast(pl.Int32)
            .alias("escort_stops_after_event"),
        )
        .select(
            "_trip_row_id",
            "escort_event_role",
            "escort_event_trip_num",
            "escort_stops_before_event",
            "escort_stops_after_event",
            "escort_event_match_status",
        )
    )

    state.trips = (
        state.trips.with_row_index("_trip_row_id")
        .drop(
            [
                "escort_event_role",
                "escort_event_trip_num",
                "escort_stops_before_event",
                "escort_stops_after_event",
                "escort_event_match_status",
            ],
            strict=False,
        )
        .join(derived, on="_trip_row_id", how="left")
        .drop("_trip_row_id")
    )
    state.trips = _ensure_escort_event_columns(state.trips)
    return state


def _escort_link_targets(
    tours: pl.DataFrame,
    trips: pl.DataFrame,
    *,
    escorted_ids_col: str,
    outbound: bool,
    child_trip_purpose: str,
    target_col: str,
) -> pl.DataFrame:
    if escorted_ids_col not in tours.columns:
        return pl.DataFrame(
            schema={"tour_id": pl.Int64, "_target_values": pl.List(pl.Int64)}
        )

    base = tours.filter(
        pl.col(escorted_ids_col).is_not_null()
        & (pl.col(escorted_ids_col).cast(pl.Utf8).str.strip_chars() != "")
    ).select(
        pl.col("tour_id"),
        pl.col(escorted_ids_col)
        .cast(pl.Utf8)
        .str.split("_")
        .alias("_escorted_tour_id_list"),
    )
    if base.is_empty():
        return pl.DataFrame(
            schema={"tour_id": pl.Int64, "_target_values": pl.List(pl.Int64)}
        )

    exploded = (
        base.explode("_escorted_tour_id_list")
        .filter(pl.col("_escorted_tour_id_list").is_not_null())
        .with_columns(
            pl.col("_escorted_tour_id_list").cast(pl.Int64, strict=False).alias("_child_tour_id")
        )
        .filter(pl.col("_child_tour_id").is_not_null())
    )
    if exploded.is_empty():
        return pl.DataFrame(
            schema={"tour_id": pl.Int64, "_target_values": pl.List(pl.Int64)}
        )

    child_trip_matches = trips.filter(
        (pl.col("outbound") == outbound)
        & (pl.col("trip_purpose").cast(pl.Utf8).str.to_lowercase() == child_trip_purpose)
    ).select(
        pl.col("tour_id").alias("_child_tour_id"),
        pl.col(target_col).cast(pl.Int64),
    )
    if child_trip_matches.is_empty():
        return pl.DataFrame(
            schema={"tour_id": pl.Int64, "_target_values": pl.List(pl.Int64)}
        )

    return (
        exploded.join(child_trip_matches, on="_child_tour_id", how="inner")
        .group_by("tour_id")
        .agg(pl.col(target_col).drop_nulls().alias("_target_values"))
    )


def _derive_escort_event_position_from_tour_links(state: _PrepareState) -> _PrepareState:
    state.trips = _ensure_escort_event_columns(state.trips)

    if "escort_participants" in state.trips.columns and state.trips["escort_participants"].is_not_null().any():
        return state

    trip_required = {
        "tour_id",
        "trip_num",
        "outbound",
        "trip_purpose",
        "max_trip_num",
        "escort_event_role",
    }
    tour_required = {
        "tour_id",
        "summary_tour_purpose",
        "school_esc_outbound",
        "school_esc_inbound",
    }
    if not trip_required.issubset(set(state.trips.columns)) or not tour_required.issubset(
        set(state.tours.columns)
    ):
        return state

    trip_rows = state.trips.with_row_index("_trip_row_id")
    explicit_escort_tours = state.tours.filter(
        pl.col("summary_tour_purpose").cast(pl.Utf8).str.to_lowercase() == "escort"
    ).select(
        [
            "tour_id",
            "school_esc_outbound",
            "school_esc_inbound",
            *[
                column
                for column in (
                    "out_escorted_tour_ids",
                    "inb_escorted_tour_ids",
                    "out_chauffeur_tour_id",
                    "inb_chauffeur_tour_id",
                )
                if column in state.tours.columns
            ],
        ]
    )
    if explicit_escort_tours.is_empty():
        return state

    outbound_targets = _escort_link_targets(
        explicit_escort_tours,
        state.trips,
        escorted_ids_col="out_escorted_tour_ids",
        outbound=True,
        child_trip_purpose="school",
        target_col="destination",
    )
    inbound_targets = _escort_link_targets(
        explicit_escort_tours,
        state.trips,
        escorted_ids_col="inb_escorted_tour_ids",
        outbound=False,
        child_trip_purpose="home",
        target_col="origin",
    )

    trip_counts = trip_rows.group_by(["tour_id", "outbound"]).agg(
        pl.len().alias("_direction_trip_count")
    )
    trip_rows = trip_rows.join(trip_counts, on=["tour_id", "outbound"], how="left")

    def _select_direction_event(
        *,
        role: str,
        outbound_value: bool,
        escort_col: str,
        purpose_preference: str,
        location_col: str,
        targets: pl.DataFrame,
    ) -> pl.DataFrame:
        candidates = (
            trip_rows.join(explicit_escort_tours, on="tour_id", how="inner")
            .filter(
                pl.col("escort_event_role").is_null()
                & (pl.col("outbound") == outbound_value)
                & _escort_value_present_expr(escort_col)
            )
            .join(targets, on="tour_id", how="left")
            .with_columns(
                pl.col("trip_purpose")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .alias("_trip_purpose_lc"),
            )
        )
        if candidates.is_empty():
            return pl.DataFrame(
                schema={
                    "_trip_row_id": pl.UInt32,
                    "escort_event_role": pl.Utf8,
                    "escort_event_trip_num": pl.Int32,
                    "escort_stops_before_event": pl.Int32,
                    "escort_stops_after_event": pl.Int32,
                    "escort_event_match_status": pl.Utf8,
                }
            )

        has_targets = (
            "_target_values" in candidates.columns
            and candidates.schema.get("_target_values") == pl.List(pl.Int64)
        )
        location_match_expr = (
            pl.col(location_col).cast(pl.Int64, strict=False).is_in(pl.col("_target_values"))
            if has_targets
            else pl.lit(False)
        )
        prioritized = candidates.with_columns(
            pl.when(location_match_expr & (pl.col("_trip_purpose_lc") == purpose_preference))
            .then(pl.lit(0))
            .when(location_match_expr)
            .then(pl.lit(1))
            .when(pl.col("_trip_purpose_lc") == purpose_preference)
            .then(pl.lit(2))
            .when(pl.col("_direction_trip_count") == 1)
            .then(pl.lit(3))
            .otherwise(pl.lit(99))
            .alias("_priority")
        )
        best = (
            prioritized.with_columns(
                pl.col("_priority").min().over("tour_id").alias("_best_priority")
            )
            .filter((pl.col("_priority") == pl.col("_best_priority")) & (pl.col("_priority") < 99))
        )
        if best.is_empty():
            return pl.DataFrame(
                schema={
                    "_trip_row_id": pl.UInt32,
                    "escort_event_role": pl.Utf8,
                    "escort_event_trip_num": pl.Int32,
                    "escort_stops_before_event": pl.Int32,
                    "escort_stops_after_event": pl.Int32,
                    "escort_event_match_status": pl.Utf8,
                }
            )

        selected = (
            best.group_by("tour_id")
            .agg(pl.len().alias("_best_count"))
            .join(best, on="tour_id", how="inner")
            .filter(pl.col("_best_count") == 1)
        )
        if selected.is_empty():
            return pl.DataFrame(
                schema={
                    "_trip_row_id": pl.UInt32,
                    "escort_event_role": pl.Utf8,
                    "escort_event_trip_num": pl.Int32,
                    "escort_stops_before_event": pl.Int32,
                    "escort_stops_after_event": pl.Int32,
                    "escort_event_match_status": pl.Utf8,
                }
            )

        return selected.select(
            pl.col("_trip_row_id"),
            pl.lit(role).alias("escort_event_role"),
            pl.col("trip_num").cast(pl.Int32).alias("escort_event_trip_num"),
            (pl.col("trip_num") - 1).cast(pl.Int32).alias("escort_stops_before_event"),
            (pl.col("max_trip_num") - pl.col("trip_num")).cast(pl.Int32).alias("escort_stops_after_event"),
            pl.lit("matched").alias("escort_event_match_status"),
        )

    outbound_selected = _select_direction_event(
        role="dropoff",
        outbound_value=True,
        escort_col="school_esc_outbound",
        purpose_preference="escort",
        location_col="destination",
        targets=outbound_targets,
    )
    inbound_selected = _select_direction_event(
        role="pickup",
        outbound_value=False,
        escort_col="school_esc_inbound",
        purpose_preference="home",
        location_col="origin",
        targets=inbound_targets,
    )

    derived = pl.concat([outbound_selected, inbound_selected], how="vertical")
    if derived.is_empty():
        return state

    updated = (
        trip_rows.drop(
            [
                "escort_event_role",
                "escort_event_trip_num",
                "escort_stops_before_event",
                "escort_stops_after_event",
                "escort_event_match_status",
            ],
            strict=False,
        )
        .join(derived, on="_trip_row_id", how="left")
        .drop("_trip_row_id")
    )
    state.trips = _ensure_escort_event_columns(updated)
    return state


def _enrich_trips(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
    autosuff_ref_col = autosuff_reference_column(config)
    hh_income_source = _resolve_source_column(state.hh, config.col_income_segment)
    if hh_income_source is not None and "household_id" in state.trips.columns:
        hh_income = state.hh.select(
            [
                pl.col("household_id"),
                pl.col(hh_income_source).alias("income_segment_hh"),
            ]
        )
        state.trips = state.trips.join(hh_income, on="household_id", how="left")
        if "income_segment" in state.trips.columns:
            state.trips = state.trips.with_columns(
                pl.coalesce([pl.col("income_segment"), pl.col("income_segment_hh")]).alias(
                    "income_segment"
                )
            ).drop("income_segment_hh")
        else:
            state.trips = state.trips.rename({"income_segment_hh": "income_segment"})

    tour_join_cols = [
        column
        for column in [
            "tour_id",
            "AUTOSUFF",
            "NUMBER_HH",
            "tour_purpose",
            "tour_mode",
            "tour_category",
            "atwork_subtour_frequency",
            "pnr_zone_id",
        ]
        if column in state.tours.columns
    ]
    if (
        "tour_id" in state.trips.columns
        and "tour_id" in state.tours.columns
        and "tour_id" in tour_join_cols
    ):
        state.trips = state.trips.join(
            state.tours.select(tour_join_cols).rename(
                {"NUMBER_HH": "num_participants"}
            ),
            on="tour_id",
            how="left",
            suffix="_tour",
        )
        for column in ["tour_purpose", "tour_mode", "tour_category"]:
            tour_col = f"{column}_tour"
            if tour_col in state.trips.columns and column in state.trips.columns:
                state.trips = state.trips.with_columns(
                    pl.coalesce([pl.col(tour_col), pl.col(column)]).alias(column)
                ).drop(tour_col)
            elif tour_col in state.trips.columns:
                state.trips = state.trips.rename({tour_col: column})

    if "HHVEH" not in state.trips.columns:
        hh_trip_join_cols = [
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
        if (
            "household_id" in state.trips.columns
            and "household_id" in hh_trip_join_cols
        ):
            state.trips = state.trips.join(
                state.hh.select(hh_trip_join_cols),
                on="household_id",
                how="left",
            )
    if "AUTOSUFF" not in state.trips.columns:
        if autosuff_ref_col not in state.trips.columns:
            hh_trip_join_cols = [
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
            if (
                "household_id" in state.trips.columns
                and "household_id" in hh_trip_join_cols
            ):
                state.trips = state.trips.join(
                    state.hh.select(hh_trip_join_cols),
                    on="household_id",
                    how="left",
                )
        state.trips = apply_autosufficiency(
            state.trips,
            state=state,
            config=config,
            metric_id="trips.AUTOSUFF",
        )
    if config.use_maz and {"origin", "destination"}.issubset(state.trips.columns):
        state.trips = state.trips.with_columns(
            pl.col("origin").alias("o_maz"),
            pl.col("destination").alias("d_maz"),
        )

    state.trips = _to_taz(
        state.trips,
        "origin",
        "OTAZ",
        state=state,
        metric_id="trips.OTAZ",
        config=config,
        zone_context=zone_context,
    )
    state.trips = _to_taz(
        state.trips,
        "destination",
        "DTAZ",
        state=state,
        metric_id="trips.DTAZ",
        config=config,
        zone_context=zone_context,
    )
    state.trips = _to_taz(
        state.trips,
        "pnr_zone_id",
        "pnr_taz",
        state=state,
        metric_id="trips.pnr_taz",
        config=config,
        zone_context=zone_context,
    )
    for aggregation in config.geography_aggregations.aggregations:
        origin_zone_col = "origin" if aggregation.source_zone_system == "maz" else "OTAZ"
        destination_zone_col = (
            "destination" if aggregation.source_zone_system == "maz" else "DTAZ"
        )
        state.trips = _add_aggregated_geography(
            state.trips,
            origin_zone_col,
            f"origin_geo__{aggregation.name}",
            aggregation_name=aggregation.name,
            source_zone_system=aggregation.source_zone_system,
            zone_context=zone_context,
        )
        state.trips = _add_aggregated_geography(
            state.trips,
            destination_zone_col,
            f"destination_geo__{aggregation.name}",
            aggregation_name=aggregation.name,
            source_zone_system=aggregation.source_zone_system,
            zone_context=zone_context,
        )
    if (
        state.skim is not None
        and "OTAZ" in state.trips.columns
        and "DTAZ" in state.trips.columns
    ):
        LOGGER.info(
            "[prepare_data] Computing trip skim distances for '%s'", state.label
        )
        o = _nullable_float_numpy(state.trips["OTAZ"])
        d = _nullable_float_numpy(state.trips["DTAZ"])
        dist = _skim_lookup(state.skim, o, d, state.skim_map)
        state.trips = state.trips.with_columns(
            _skim_series("od_dist", dist)
        )
        total = state.trips.filter(
            pl.col("origin").is_not_null() & pl.col("destination").is_not_null()
        ).height
        unresolved = state.trips.filter(
            pl.col("origin").is_not_null()
            & pl.col("destination").is_not_null()
            & pl.col("od_dist").is_null()
        ).height
        _record_prepare_metric(
            state,
            "trips.od_dist",
            total=total,
            unresolved=unresolved,
        )
    elif "od_dist" not in state.trips.columns:
        LOGGER.info(
            "[prepare_data] Trip skim distances unavailable for '%s'; leaving od_dist absent.",
            state.label,
        )

    if "depart_hour" not in state.trips.columns:
        state.trips = state.trips.with_columns(pl.lit(1).alias("depart_hour"))

    if "outbound" in state.trips.columns and "inbound" not in state.trips.columns:
        state.trips = state.trips.with_columns(
            pl.when(
                pl.col("outbound")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["false", "0"])
            )
            .then(1)
            .otherwise(0)
            .alias("inbound")
        )

    if _has_columns(state.trips, "tour_id", "trip_num", "outbound"):
        max_trip = state.trips.group_by(["tour_id", "outbound"]).agg(
            pl.col("trip_num").max().alias("max_trip_num")
        )
        state.trips = state.trips.join(max_trip, on=["tour_id", "outbound"], how="left")
        state.trips = state.trips.with_columns(
            pl.when(pl.col("trip_num") < pl.col("max_trip_num"))
            .then(1)
            .otherwise(0)
            .alias("stops")
        )
    elif "stops" not in state.trips.columns:
        state.trips = state.trips.with_columns(pl.lit(0).alias("stops"))

    if "out_dir_dist" not in state.trips.columns:
        if (
            state.skim is not None
            and _has_columns(state.trips, "tour_id", "OTAZ", "DTAZ", "inbound")
            and _has_columns(state.tours, "tour_id", "OTAZ", "DTAZ")
        ):
            tour_od = state.tours.select(["tour_id", "OTAZ", "DTAZ"]).rename(
                {"OTAZ": "tour_OTAZ", "DTAZ": "tour_DTAZ"}
            )
            state.trips = state.trips.join(tour_od, on="tour_id", how="left")
            finaldest = np.where(
                state.trips["inbound"].to_numpy() == 0,
                _nullable_float_numpy(state.trips["tour_DTAZ"]),
                _nullable_float_numpy(state.trips["tour_OTAZ"]),
            )
            o = _nullable_float_numpy(state.trips["OTAZ"])
            d = _nullable_float_numpy(state.trips["DTAZ"])
            od = _skim_lookup(state.skim, o, d, state.skim_map)
            os_ = _skim_lookup(state.skim, o, finaldest, state.skim_map)
            sd = _skim_lookup(state.skim, d, finaldest, state.skim_map)
            state.trips = state.trips.with_columns(
                _skim_series("out_dir_dist", np.clip(os_ + sd - od, 0, None))
            )
            total = state.trips.filter(
                pl.col("origin").is_not_null()
                & pl.col("destination").is_not_null()
                & pl.col("tour_id").is_not_null()
            ).height
            unresolved = state.trips.filter(
                pl.col("origin").is_not_null()
                & pl.col("destination").is_not_null()
                & pl.col("tour_id").is_not_null()
                & pl.col("out_dir_dist").is_null()
            ).height
            _record_prepare_metric(
                state,
                "trips.out_dir_dist",
                total=total,
                unresolved=unresolved,
            )
        else:
            LOGGER.info(
                "[prepare_data] Out-of-direction trip distances unavailable for '%s'; leaving out_dir_dist absent.",
                state.label,
            )

    state.trips = with_summary_tour_purpose(state.trips, config)
    state = _derive_escort_event_position(state)
    state = _derive_escort_event_position_from_tour_links(state)

    return state
