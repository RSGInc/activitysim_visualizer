"""Canonical-column materialization for raw prepare inputs."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.columns import (
    _cast_if_present,
    _materialize_column,
    _materialize_preferred_column,
    _resolve_source_column,
)
from processor.prepare.enrichment.types import _PrepareState
from runtime.config import Config


def _canonicalize_households(hh: pl.DataFrame, config: Config) -> pl.DataFrame:
    return _materialize_column(
        hh,
        "household_id",
        _resolve_source_column(hh, config.col_household_id),
    )


def _canonicalize_persons(per: pl.DataFrame, config: Config) -> pl.DataFrame:
    per = _materialize_column(
        per,
        "household_id",
        _resolve_source_column(per, config.col_household_id),
    )
    per = _materialize_column(
        per,
        "person_id",
        _resolve_source_column(per, config.col_person_id),
    )
    return _materialize_column(
        per,
        "person_type",
        _resolve_source_column(
            per, config.col_ptype, fallbacks=("person_type", "ptype")
        ),
        overwrite=True,
    )


def _canonicalize_tours(tours: pl.DataFrame, config: Config) -> pl.DataFrame:
    tours = _materialize_column(
        tours,
        "household_id",
        _resolve_source_column(tours, config.col_household_id),
    )
    tours = _materialize_column(
        tours,
        "person_id",
        _resolve_source_column(tours, config.col_person_id),
    )
    tours = _materialize_column(
        tours,
        "person_type",
        _resolve_source_column(
            tours, config.col_ptype, fallbacks=("person_type", "ptype")
        ),
        overwrite=True,
    )
    tours = _materialize_column(
        tours,
        "tour_id",
        _resolve_source_column(tours, config.col_tour_id),
    )
    tours = _materialize_column(
        tours,
        "tour_category",
        _resolve_source_column(tours, config.col_tour_category),
    )
    tours = _materialize_column(
        tours,
        "tour_mode",
        _resolve_source_column(tours, config.col_tour_mode),
    )
    tours = _materialize_preferred_column(
        tours,
        "tour_purpose",
        config.col_tour_purpose,
        require_non_numeric=True,
    )
    tours = _materialize_column(
        tours,
        "start_hour",
        _resolve_source_column(tours, config.col_tour_start),
    )
    tours = _materialize_column(
        tours,
        "end_hour",
        _resolve_source_column(tours, config.col_tour_end),
    )
    return _materialize_column(
        tours,
        "tourdur",
        _resolve_source_column(tours, config.col_tour_duration),
    )


def _canonicalize_trips(trips: pl.DataFrame, config: Config) -> pl.DataFrame:
    trips = _materialize_column(
        trips,
        "household_id",
        _resolve_source_column(trips, config.col_household_id),
    )
    trips = _materialize_column(
        trips,
        "person_id",
        _resolve_source_column(trips, config.col_person_id),
    )
    trips = _materialize_column(
        trips,
        "tour_id",
        _resolve_source_column(trips, config.col_tour_id),
    )
    trips = _materialize_column(
        trips,
        "trip_id",
        _resolve_source_column(trips, config.col_trip_id),
    )
    trips = _materialize_column(
        trips,
        "trip_mode",
        _resolve_source_column(trips, config.col_trip_mode),
    )
    trips = _materialize_preferred_column(
        trips,
        "trip_purpose",
        config.col_trip_purpose,
        require_non_numeric=True,
    )
    trips = _materialize_column(
        trips,
        "depart_hour",
        _resolve_source_column(trips, config.col_trip_depart),
    )
    trips = _materialize_column(
        trips,
        "tour_mode",
        _resolve_source_column(trips, config.col_tour_mode),
    )
    trips = _materialize_column(
        trips,
        "tour_category",
        _resolve_source_column(trips, config.col_tour_category),
    )
    return _materialize_preferred_column(
        trips,
        "tour_purpose",
        config.col_tour_purpose,
        require_non_numeric=True,
    )


def _canonicalize_joint_participants(
    joint_participants: pl.DataFrame, config: Config
) -> pl.DataFrame:
    joint_participants = _materialize_column(
        joint_participants,
        "person_id",
        _resolve_source_column(joint_participants, config.col_person_id),
    )
    joint_participants = _materialize_column(
        joint_participants,
        "tour_id",
        _resolve_source_column(joint_participants, config.col_tour_id),
    )
    return _cast_if_present(
        joint_participants,
        {
            "person_id": pl.Int64,
            "tour_id": pl.Int64,
        },
    )


def _canonicalize_land_use(land_use: pl.DataFrame, config: Config) -> pl.DataFrame:
    land_use = _materialize_column(
        land_use,
        "MAZ",
        _resolve_source_column(land_use, config.maz_col),
    )
    land_use = _materialize_column(
        land_use,
        "EMPLOYMENT",
        _resolve_source_column(land_use, config.col_total_employment),
    )
    return _materialize_column(
        land_use,
        "employment_count",
        _resolve_source_column(land_use, config.col_total_employment),
    )


def _canonicalize_identifiers_and_core_columns(
    state: _PrepareState, config: Config
) -> _PrepareState:
    state.hh = _canonicalize_households(state.hh, config)
    state.per = _canonicalize_persons(state.per, config)
    state.tours = _canonicalize_tours(state.tours, config)
    state.trips = _canonicalize_trips(state.trips, config)
    state.joint_participants = _canonicalize_joint_participants(
        state.joint_participants, config
    )
    state.land_use = _canonicalize_land_use(state.land_use, config)
    return state
