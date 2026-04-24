"""Trip enrichment stage for prepared tables."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import numpy as np
import polars as pl

from processor.prepare.enrichment.columns import _has_columns
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from processor.prepare.enrichment.zones import _skim_lookup, _to_taz
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _enrich_trips(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
    tour_join_cols = [
        column
        for column in [
            "tour_id",
            "AUTOSUFF",
            "NUMBER_HH",
            "tour_purpose",
            "tour_mode",
            "tour_category",
        ]
        if column in state.tours.columns
    ]
    if (
        "tour_id" in state.trips.columns
        and "tour_id" in state.tours.columns
        and "tour_id" in tour_join_cols
    ):
        state.trips = state.trips.join(
            state.tours.select(tour_join_cols).rename({"NUMBER_HH": "num_participants"}),
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
            for column in ["household_id", "HHVEH", "WORKERS"]
            if column in state.hh.columns
        ]
        if "household_id" in state.trips.columns and "household_id" in hh_trip_join_cols:
            state.trips = state.trips.join(
                state.hh.select(hh_trip_join_cols),
                on="household_id",
                how="left",
            )
    if (
        "AUTOSUFF" not in state.trips.columns
        and "HHVEH" in state.trips.columns
        and "WORKERS" in state.trips.columns
    ):
        state.trips = state.trips.with_columns(
            pl.when(pl.col("HHVEH") == 0)
            .then(0)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") < pl.col("WORKERS")))
            .then(1)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") >= pl.col("WORKERS")))
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
    if state.skim is not None and "OTAZ" in state.trips.columns and "DTAZ" in state.trips.columns:
        LOGGER.info("[prepare_data] Computing trip skim distances for '%s'", state.label)
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

    return state
