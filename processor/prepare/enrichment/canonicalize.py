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


_CATEGORY_MAPPING_TABLE_ATTRIBUTES = {
    "households": "hh",
    "persons": "per",
    "day": "day",
    "tours": "tours",
    "trips": "trips",
    "vehicles": "vehicles",
    "joint_tour_participants": "joint_participants",
    "land_use": "land_use",
}


def _apply_prepare_category_mappings(
    state: _PrepareState, config: Config
) -> _PrepareState:
    run_mapping = config.prepare_category_mappings.mapping_for_run(state.label)
    if run_mapping is None:
        return state

    for table_name, column_mappings in run_mapping.items():
        attribute = _CATEGORY_MAPPING_TABLE_ATTRIBUTES[table_name]
        table = getattr(state, attribute)
        for target_column, spec in column_mappings.items():
            metric_id = f"category_mappings.{table_name}.{target_column}"
            if spec.source_column not in table.columns:
                state.prepare_diagnostics[metric_id] = {
                    "total": 0,
                    "unresolved": 0,
                    "status": "source_column_missing",
                    "source_column": spec.source_column,
                }
                continue

            source_text = pl.col(spec.source_column).cast(pl.Utf8)
            if spec.output_type == "boolean":
                preserve_source = (
                    spec.preserve_unmapped
                    and table.schema.get(spec.source_column) == pl.Boolean
                )
                default = (
                    pl.col(spec.source_column)
                    if preserve_source
                    else pl.lit(None, dtype=pl.Boolean)
                )
                mapped = source_text.replace_strict(
                    spec.mapping,
                    default=default,
                    return_dtype=pl.Boolean,
                )
            else:
                default = source_text if spec.preserve_unmapped else pl.lit(None)
                mapped = source_text.replace_strict(
                    spec.mapping,
                    default=default,
                    return_dtype=pl.Utf8,
                )

            source_values = table.select(
                source_text.alias("_source_value")
            ).filter(pl.col("_source_value").is_not_null())
            unmatched = source_values.filter(
                ~pl.col("_source_value").is_in(list(spec.mapping))
            )
            unmatched_values = (
                unmatched.select("_source_value")
                .unique(maintain_order=True)
                .head(20)
                .to_series()
                .to_list()
            )
            state.prepare_diagnostics[metric_id] = {
                "total": source_values.height,
                "unresolved": unmatched.height,
                "unresolved_share": (
                    float(unmatched.height) / float(source_values.height)
                    if source_values.height
                    else 0.0
                ),
                "source_column": spec.source_column,
                "unmatched_values": unmatched_values,
            }
            table = table.with_columns(mapped.alias(target_column))
        setattr(state, attribute, table)
    return state


def _toc_model_period_expr(hour_column: str, minute_column: str) -> pl.Expr:
    hour = pl.col(hour_column).cast(pl.Int64, strict=False)
    minute = pl.col(minute_column).cast(pl.Int64, strict=False)
    minutes_after_3_am = (hour * 60 + minute - 180 + 1440) % 1440
    return (
        pl.when(hour.is_between(0, 23) & minute.is_between(0, 59))
        .then((minutes_after_3_am // 30) + 1)
        .otherwise(None)
        .cast(pl.Int32)
    )


def _is_toc_raw_survey(state: _PrepareState) -> bool:
    return (
        {"num_people", "num_vehicles"}.issubset(state.hh.columns)
        and {"can_drive", "person_type"}.issubset(state.per.columns)
        and {
            "tour_start_hour",
            "tour_start_minute",
            "tour_end_hour",
            "tour_end_minute",
            "tour_mode",
            "tour_purpose",
            "duration_minutes",
            "distance_miles",
        }.issubset(state.tours.columns)
        and {
            "linked_trip_mode",
            "d_purpose_category",
            "depart_hour",
            "depart_minute",
            "distance_miles",
        }.issubset(state.trips.columns)
    )


def _normalize_toc_raw_survey(
    state: _PrepareState, config: Config
) -> _PrepareState:
    if not _is_toc_raw_survey(state):
        return state

    state.hh = state.hh.with_columns(
        pl.col("num_people").alias("hhsize"),
        pl.col("num_vehicles").alias("auto_ownership"),
    )
    state.tours = state.tours.with_columns(
        _toc_model_period_expr("tour_start_hour", "tour_start_minute").alias("start"),
        _toc_model_period_expr("tour_start_hour", "tour_start_minute").alias(
            "start_hour"
        ),
        _toc_model_period_expr("tour_end_hour", "tour_end_minute").alias("end"),
        _toc_model_period_expr("tour_end_hour", "tour_end_minute").alias("end_hour"),
        pl.col("distance_miles").cast(pl.Float64, strict=False).alias("SKIMDIST"),
    )
    if "joint_num_participants" in state.tours.columns:
        state.tours = state.tours.with_columns(
            pl.col("joint_num_participants")
            .cast(pl.Int64, strict=False)
            .alias("number_of_participants")
        )

    state.trips = state.trips.with_columns(
        _toc_model_period_expr("depart_hour", "depart_minute").alias("depart"),
        pl.col("distance_miles").cast(pl.Float64, strict=False).alias("od_dist"),
        pl.col("distance_miles")
        .cast(pl.Float64, strict=False)
        .alias("prepared_non_motorized_distance"),
    )
    return state


def _canonicalize_households(hh: pl.DataFrame, config: Config) -> pl.DataFrame:
    hh = _materialize_column(
        hh,
        "household_id",
        _resolve_source_column(hh, config.col_household_id),
    )
    return _materialize_column(
        hh,
        "home_zone_id",
        _resolve_source_column(hh, config.col_home_zone_id),
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
    per = _materialize_column(
        per,
        "person_type",
        _resolve_source_column(
            per, config.col_ptype, fallbacks=("person_type", "ptype")
        ),
        overwrite=True,
    )
    per = _materialize_column(
        per,
        "home_zone_id",
        _resolve_source_column(per, config.col_home_zone_id),
    )
    per = _materialize_column(
        per,
        "workplace_zone_id",
        _resolve_source_column(per, config.col_workplace_zone_id),
    )
    per = _materialize_column(
        per,
        "school_zone_id",
        _resolve_source_column(per, config.col_school_zone_id),
    )
    per = _materialize_column(
        per,
        "has_license",
        _resolve_source_column(per, config.col_has_license),
    )
    per = _materialize_column(
        per,
        "mandatory_tour_frequency",
        _resolve_source_column(per, config.col_mandatory_tour_frequency),
    )
    per = _materialize_column(
        per,
        "is_student",
        _resolve_source_column(per, config.col_is_student),
    )
    per = _materialize_column(
        per,
        "is_university",
        _resolve_source_column(per, config.col_is_university),
    )
    per = _materialize_column(
        per,
        "school_segment",
        _resolve_source_column(per, config.col_school_segment),
    )
    per = _materialize_column(
        per,
        "is_worker",
        _resolve_source_column(per, config.col_is_worker),
    )
    per = _materialize_column(
        per,
        "adult",
        _resolve_source_column(per, config.col_adult),
    )
    per = _materialize_column(
        per,
        "SCHG",
        _resolve_source_column(per, config.col_schg),
    )
    return _materialize_column(
        per,
        "pstudent",
        _resolve_source_column(per, config.col_pstudent),
    )


def _canonicalize_day(day: pl.DataFrame, config: Config) -> pl.DataFrame:
    day = _materialize_column(
        day,
        "household_id",
        _resolve_source_column(day, config.col_household_id, fallbacks=("hh_id",)),
    )
    day = _materialize_column(
        day,
        "person_id",
        _resolve_source_column(day, config.col_person_id),
    )
    day = _materialize_column(
        day,
        "day_id",
        _resolve_source_column(day, config.col_day_id),
    )
    return _materialize_column(
        day,
        "day_weight",
        _resolve_source_column(day, config.col_day_weight),
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
        fallbacks=("tour_purpose", "primary_purpose", "tour_type", "purpose"),
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
    tours = _materialize_column(
        tours,
        "tourdur",
        _resolve_source_column(tours, config.col_tour_duration),
    )
    tours = _materialize_column(
        tours,
        "origin",
        _resolve_source_column(tours, config.col_tour_origin),
    )
    tours = _materialize_column(
        tours,
        "destination",
        _resolve_source_column(tours, config.col_tour_destination),
    )
    tours = _materialize_column(
        tours,
        "stop_frequency",
        _resolve_source_column(tours, config.col_stop_frequency),
    )
    return _materialize_column(
        tours,
        "pnr_zone_id",
        _resolve_source_column(tours, config.col_pnr_zone_id),
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
        "origin",
        _resolve_source_column(trips, config.col_trip_origin),
    )
    trips = _materialize_column(
        trips,
        "destination",
        _resolve_source_column(trips, config.col_trip_destination),
    )
    trips = _materialize_column(
        trips,
        "outbound",
        _resolve_source_column(trips, config.col_trip_outbound),
    )
    trips = _materialize_column(
        trips,
        "trip_num",
        _resolve_source_column(trips, config.col_trip_num),
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


def _canonicalize_vehicles(vehicles: pl.DataFrame, config: Config) -> pl.DataFrame:
    vehicles = _materialize_column(
        vehicles,
        "household_id",
        _resolve_source_column(vehicles, config.col_household_id),
    )
    vehicles = _materialize_column(
        vehicles,
        "vehicle_id",
        _resolve_source_column(vehicles, config.col_vehicle_id),
    )
    vehicles = _materialize_column(
        vehicles,
        "vehicle_num",
        _resolve_source_column(vehicles, config.col_vehicle_num),
    )
    return _materialize_column(
        vehicles,
        "vehicle_type",
        _resolve_source_column(vehicles, config.col_vehicle_type),
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
        "TAZ",
        _resolve_source_column(land_use, config.taz_col),
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
    state = _apply_prepare_category_mappings(state, config)
    state.hh = _canonicalize_households(state.hh, config)
    state.per = _canonicalize_persons(state.per, config)
    state.day = _canonicalize_day(state.day, config)
    state.tours = _canonicalize_tours(state.tours, config)
    state.trips = _canonicalize_trips(state.trips, config)
    state.vehicles = _canonicalize_vehicles(state.vehicles, config)
    state.joint_participants = _canonicalize_joint_participants(
        state.joint_participants, config
    )
    state.land_use = _canonicalize_land_use(state.land_use, config)
    return _normalize_toc_raw_survey(state, config)
