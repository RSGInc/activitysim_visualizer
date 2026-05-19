"""Trip enrichment stage for prepared tables."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import numpy as np
import polars as pl

from processor.tour_purpose import with_summary_tour_purpose
from processor.prepare.enrichment.columns import _has_columns
from processor.prepare.enrichment.columns import _resolve_source_column
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from processor.prepare.enrichment.zones import _skim_lookup, _to_taz
from runtime.config import Config

LOGGER = get_logger("processor.prepare")
_CHILD_PERSON_TYPES = {"6", "7", "8"}


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


def _enrich_trips(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
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
            for column in ["household_id", "HHVEH", "WORKERS", "LICENSEDDRIVERS"]
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
    if (
        "AUTOSUFF" not in state.trips.columns
        and "HHVEH" in state.trips.columns
        and "LICENSEDDRIVERS" in state.trips.columns
    ):
        state.trips = state.trips.with_columns(
            pl.when(pl.col("HHVEH") == 0)
            .then(0)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") < pl.col("LICENSEDDRIVERS")))
            .then(1)
            .when(
                (pl.col("HHVEH") > 0) & (pl.col("HHVEH") >= pl.col("LICENSEDDRIVERS"))
            )
            .then(2)
            .otherwise(0)
            .alias("AUTOSUFF")
        )

    state.trips = _to_taz(
        state.trips,
        "origin",
        "OTAZ",
        config=config,
        zone_context=zone_context,
    )
    state.trips = _to_taz(
        state.trips,
        "destination",
        "DTAZ",
        config=config,
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
        o = state.trips["OTAZ"].fill_null(0).to_numpy()
        d = state.trips["DTAZ"].fill_null(0).to_numpy()
        state.trips = state.trips.with_columns(
            pl.Series("od_dist", _skim_lookup(state.skim, o, d, state.skim_map))
        )
    elif "od_dist" not in state.trips.columns:
        state.trips = state.trips.with_columns(pl.lit(0.0).alias("od_dist"))

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
                state.trips["tour_DTAZ"].fill_null(0).to_numpy(),
                state.trips["tour_OTAZ"].fill_null(0).to_numpy(),
            )
            o = state.trips["OTAZ"].fill_null(0).to_numpy()
            d = state.trips["DTAZ"].fill_null(0).to_numpy()
            od = _skim_lookup(state.skim, o, d, state.skim_map)
            os_ = _skim_lookup(state.skim, o, finaldest, state.skim_map)
            sd = _skim_lookup(state.skim, d, finaldest, state.skim_map)
            state.trips = state.trips.with_columns(
                pl.Series("out_dir_dist", (os_ + sd - od).clip(0))
            )
        else:
            state.trips = state.trips.with_columns(pl.lit(0.0).alias("out_dir_dist"))

    state.trips = with_summary_tour_purpose(state.trips, config)
    state = _derive_escort_event_position(state)

    return state
