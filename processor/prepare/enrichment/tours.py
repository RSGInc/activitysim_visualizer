"""Tour enrichment stage for prepared tables."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import polars as pl

from processor.tour_purpose import with_summary_tour_purpose
from processor.prepare.enrichment.columns import _resolve_source_column
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from processor.prepare.enrichment.zones import _skim_lookup, _to_taz
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _enrich_tours(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
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
        for column in [
            "household_id",
            "HHVEH",
            "WORKERS",
            "LICENSEDDRIVERS",
            "ADULTS",
        ]
        if column in state.hh.columns
    ]
    if "household_id" in state.tours.columns and "household_id" in hh_for_tours:
        state.tours = state.tours.join(
            state.hh.select(hh_for_tours),
            on="household_id",
            how="left",
        )

    if "HHVEH" in state.tours.columns and "LICENSEDDRIVERS" in state.tours.columns:
        state.tours = state.tours.with_columns(
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

    state.tours = _to_taz(
        state.tours,
        "origin",
        "OTAZ",
        config=config,
        zone_context=zone_context,
    )
    state.tours = _to_taz(
        state.tours,
        "destination",
        "DTAZ",
        config=config,
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
        o = state.tours["OTAZ"].fill_null(0).to_numpy()
        d = state.tours["DTAZ"].fill_null(0).to_numpy()
        state.tours = state.tours.with_columns(
            pl.Series("SKIMDIST", _skim_lookup(state.skim, o, d, state.skim_map))
        )
    elif "SKIMDIST" not in state.tours.columns:
        state.tours = state.tours.with_columns(pl.lit(0.0).alias("SKIMDIST"))

    if (
        "tour_id" in state.tours.columns
        and "tour_id" in state.joint_participants.columns
        and state.joint_participants.schema.get("tour_id") != pl.Null
    ):
        party_size = state.joint_participants.group_by("tour_id").agg(
            pl.len().alias("NUMBER_HH")
        )
        state.tours = state.tours.join(party_size, on="tour_id", how="left")
    if "NUMBER_HH" not in state.tours.columns:
        state.tours = state.tours.with_columns(pl.lit(1).alias("NUMBER_HH"))
    state.tours = state.tours.with_columns(pl.col("NUMBER_HH").fill_null(1))

    if (
        "start_hour" in state.tours.columns
        and "end_hour" in state.tours.columns
        and "tourdur" not in state.tours.columns
    ):
        state.tours = state.tours.with_columns(
            (pl.col("end_hour") - pl.col("start_hour")).alias("tourdur")
        )

    state.tours = with_summary_tour_purpose(state.tours, config)

    return state
