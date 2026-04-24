"""Household and person enrichment stages for prepared tables."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import polars as pl

from processor.prepare.enrichment.columns import _has_columns
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from processor.prepare.enrichment.zones import _add_geo, _skim_lookup, _to_taz
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _enrich_households(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> None:
    ao_col = config.col_auto_ownership
    if ao_col in state.hh.columns:
        state.hh = state.hh.with_columns(pl.col(ao_col).clip(0, 4).alias("HHVEH"))

    sz_col = config.col_hhsize
    if sz_col in state.hh.columns:
        state.hh = state.hh.with_columns(pl.col(sz_col).clip(1, 5).alias("HHSIZE"))

    if config.col_num_workers in state.hh.columns:
        state.hh = state.hh.with_columns(pl.col(config.col_num_workers).alias("WORKERS"))
    if config.col_num_adults in state.hh.columns:
        state.hh = state.hh.with_columns(pl.col(config.col_num_adults).alias("ADULTS"))

    state.hh = _to_taz(
        state.hh,
        "home_zone_id",
        "home_taz",
        config=config,
        zone_context=zone_context,
    )
    state.hh = _add_geo(
        state.hh,
        "home_taz",
        "HGEO",
        config=config,
        zone_context=zone_context,
    )


def _enrich_persons(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> None:
    if (
        "home_zone_id" not in state.per.columns
        and _has_columns(state.per, "household_id")
        and _has_columns(state.hh, "household_id", "home_zone_id")
    ):
        LOGGER.warning(
            "Warning: 'home_zone_id' column not found in persons for run '%s'. Merging from household_id.",
            state.label,
        )
        state.per = state.per.join(
            state.hh.select(["household_id", "home_zone_id"]),
            on="household_id",
            how="left",
        )

    state.per = _to_taz(
        state.per,
        "home_zone_id",
        "home_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _to_taz(
        state.per,
        "workplace_zone_id",
        "work_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _to_taz(
        state.per,
        "school_zone_id",
        "school_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _add_geo(
        state.per,
        "home_taz",
        "HGEO",
        config=config,
        zone_context=zone_context,
    )
    state.per = _add_geo(
        state.per,
        "work_taz",
        "WGEO",
        config=config,
        zone_context=zone_context,
    )

    if state.skim is not None:
        LOGGER.info("[prepare_data] Computing person skim distances for '%s'", state.label)
        if "home_taz" in state.per.columns and "work_taz" in state.per.columns:
            o = state.per["home_taz"].fill_null(0).to_numpy()
            d = state.per["work_taz"].fill_null(0).to_numpy()
            state.per = state.per.with_columns(
                pl.Series("distance_to_work", _skim_lookup(state.skim, o, d, state.skim_map))
            )
        if "home_taz" in state.per.columns and "school_taz" in state.per.columns:
            o = state.per["home_taz"].fill_null(0).to_numpy()
            d = state.per["school_taz"].fill_null(0).to_numpy()
            state.per = state.per.with_columns(
                pl.Series(
                    "distance_to_school",
                    _skim_lookup(state.skim, o, d, state.skim_map),
                )
            )

    if "mandatory_tour_frequency" in state.per.columns and "imf_choice" not in state.per.columns:
        state.per = state.per.with_columns(
            pl.when(pl.col("mandatory_tour_frequency") == "work1")
            .then(1)
            .when(pl.col("mandatory_tour_frequency") == "work2")
            .then(2)
            .when(pl.col("mandatory_tour_frequency") == "school1")
            .then(3)
            .when(pl.col("mandatory_tour_frequency") == "school2")
            .then(4)
            .when(pl.col("mandatory_tour_frequency") == "work_and_school")
            .then(5)
            .otherwise(0)
            .alias("imf_choice")
        )


def _enrich_households_and_persons(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
    _enrich_households(state, config, zone_context)
    _enrich_persons(state, config, zone_context)
    return state
