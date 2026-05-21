"""Household and person enrichment stages for prepared tables."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import polars as pl

from processor.prepare.enrichment.columns import _has_columns
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from processor.prepare.enrichment.zones import (
    _add_aggregated_geography,
    _add_geo,
    _nullable_float_numpy,
    _record_prepare_metric,
    _skim_lookup,
    _skim_series,
    _to_taz,
)
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _add_configured_geographies(
    df: pl.DataFrame,
    *,
    role_name: str,
    maz_col: str,
    taz_col: str,
    config: Config,
    zone_context: _ZoneContext,
) -> pl.DataFrame:
    result = df
    for aggregation in config.geography_aggregations.aggregations:
        zone_col = maz_col if aggregation.source_zone_system == "maz" else taz_col
        result = _add_aggregated_geography(
            result,
            zone_col,
            f"{role_name}_geo__{aggregation.name}",
            aggregation_name=aggregation.name,
            source_zone_system=aggregation.source_zone_system,
            zone_context=zone_context,
        )
    return result


def _licensed_driver_expr(column_name: str = "has_license") -> pl.Expr:
    return (
        pl.col(column_name)
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "licensed"])
    )


def _derive_num_joint_tours(state: _PrepareState) -> None:
    if (
        "num_joint_tours" in state.per.columns
        or "person_id" not in state.per.columns
        or "person_id" not in state.joint_participants.columns
        or "tour_id" not in state.joint_participants.columns
    ):
        return

    joint_counts = (
        state.joint_participants.filter(
            pl.col("person_id").is_not_null() & pl.col("tour_id").is_not_null()
        )
        .group_by("person_id")
        .agg(pl.col("tour_id").n_unique().cast(pl.Int32).alias("num_joint_tours"))
    )
    state.per = (
        state.per.join(joint_counts, on="person_id", how="left")
        .with_columns(pl.col("num_joint_tours").fill_null(0).cast(pl.Int32))
    )


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
        state.hh = state.hh.with_columns(
            pl.col(config.col_num_workers).alias("WORKERS")
        )
    if config.col_num_adults in state.hh.columns:
        state.hh = state.hh.with_columns(pl.col(config.col_num_adults).alias("ADULTS"))

    state.hh = _to_taz(
        state.hh,
        "home_zone_id",
        "home_taz",
        state=state,
        metric_id="households.home_taz",
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
    state.hh = _add_configured_geographies(
        state.hh,
        role_name="home",
        maz_col="home_zone_id",
        taz_col="home_taz",
        config=config,
        zone_context=zone_context,
    )


def _enrich_persons(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> None:
    _derive_num_joint_tours(state)

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
        state=state,
        metric_id="persons.home_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _to_taz(
        state.per,
        "workplace_zone_id",
        "work_taz",
        state=state,
        metric_id="persons.work_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _to_taz(
        state.per,
        "school_zone_id",
        "school_taz",
        state=state,
        metric_id="persons.school_taz",
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
    state.per = _add_configured_geographies(
        state.per,
        role_name="home",
        maz_col="home_zone_id",
        taz_col="home_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _add_configured_geographies(
        state.per,
        role_name="work",
        maz_col="workplace_zone_id",
        taz_col="work_taz",
        config=config,
        zone_context=zone_context,
    )
    state.per = _add_configured_geographies(
        state.per,
        role_name="school",
        maz_col="school_zone_id",
        taz_col="school_taz",
        config=config,
        zone_context=zone_context,
    )

    if state.skim is not None:
        LOGGER.info(
            "[prepare_data] Computing person skim distances for '%s'", state.label
        )
        if "home_taz" in state.per.columns and "work_taz" in state.per.columns:
            o = _nullable_float_numpy(state.per["home_taz"])
            d = _nullable_float_numpy(state.per["work_taz"])
            dist = _skim_lookup(state.skim, o, d, state.skim_map)
            state.per = state.per.with_columns(
                _skim_series("distance_to_work", dist)
            )
            total = state.per.filter(
                pl.col("home_zone_id").is_not_null()
                & pl.col("workplace_zone_id").is_not_null()
            ).height
            unresolved = state.per.filter(
                pl.col("home_zone_id").is_not_null()
                & pl.col("workplace_zone_id").is_not_null()
                & pl.col("distance_to_work").is_null()
            ).height
            _record_prepare_metric(
                state,
                "persons.distance_to_work",
                total=total,
                unresolved=unresolved,
            )
        if "home_taz" in state.per.columns and "school_taz" in state.per.columns:
            o = _nullable_float_numpy(state.per["home_taz"])
            d = _nullable_float_numpy(state.per["school_taz"])
            dist = _skim_lookup(state.skim, o, d, state.skim_map)
            state.per = state.per.with_columns(
                _skim_series("distance_to_school", dist)
            )
            total = state.per.filter(
                pl.col("home_zone_id").is_not_null()
                & pl.col("school_zone_id").is_not_null()
            ).height
            unresolved = state.per.filter(
                pl.col("home_zone_id").is_not_null()
                & pl.col("school_zone_id").is_not_null()
                & pl.col("distance_to_school").is_null()
            ).height
            _record_prepare_metric(
                state,
                "persons.distance_to_school",
                total=total,
                unresolved=unresolved,
            )

    if (
        "mandatory_tour_frequency" in state.per.columns
        and "imf_choice" not in state.per.columns
    ):
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

    if {
        "household_id",
        "has_license",
    }.issubset(state.per.columns) and "household_id" in state.hh.columns:
        licensed_drivers = (
            state.per.filter(
                pl.col("household_id").is_not_null()
                & pl.col("has_license").is_not_null()
            )
            .group_by("household_id")
            .agg(_licensed_driver_expr().sum().cast(pl.Int32).alias("LICENSEDDRIVERS"))
        )
        state.hh = state.hh.join(
            licensed_drivers, on="household_id", how="left"
        ).with_columns(pl.col("LICENSEDDRIVERS").fill_null(0).cast(pl.Int32))


def _enrich_households_and_persons(
    state: _PrepareState, config: Config, zone_context: _ZoneContext
) -> _PrepareState:
    _enrich_households(state, config, zone_context)
    _enrich_persons(state, config, zone_context)
    return state
