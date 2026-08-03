"""Final casts and RunData reconstruction for prepare enrichment."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.columns import _cast_if_present
from processor.prepare.enrichment.types import _PrepareState


def _cast_dynamic_geo_columns(df: pl.DataFrame) -> pl.DataFrame:
    geo_columns = {
        column: pl.Utf8 for column in df.columns if "_geo__" in column
    }
    if not geo_columns:
        return df
    return _cast_if_present(df, geo_columns)


def _cast_households(hh: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            hh,
            {
                "household_id": pl.Int64,
                "finalweight": pl.Float64,
                "HHVEH": pl.Int32,
                "HHSIZE": pl.Int32,
                "WORKERS": pl.Int32,
                "LICENSEDDRIVERS": pl.Int32,
                "ADULTS": pl.Int32,
                "HGEO": pl.Utf8,
            },
        )
    )


def _cast_persons(per: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            per,
            {
                "household_id": pl.Int64,
                "person_id": pl.Int64,
                "finalweight": pl.Float64,
                "HGEO": pl.Utf8,
                "WGEO": pl.Utf8,
                "is_worker": pl.Utf8,
                "adult": pl.Utf8,
                "student_type": pl.Utf8,
                "work_from_home": pl.Utf8,
                "mandatory_tour_frequency": pl.Utf8,
                "distance_to_work": pl.Float64,
                "distance_to_school": pl.Float64,
            },
        )
    )


def _cast_day(day: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            day,
            {
                "day_id": pl.Int64,
                "household_id": pl.Int64,
                "person_id": pl.Int64,
                "person_type": pl.Utf8,
                "travel_date": pl.Utf8,
                "day_num": pl.Int32,
                "travel_dow": pl.Int32,
                "daily_activity_pattern": pl.Utf8,
                "finalweight": pl.Float64,
            },
        )
    )


def _cast_tours(tours: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            tours,
            {
                "household_id": pl.Int64,
                "person_id": pl.Int64,
                "tour_id": pl.Int64,
                "tour_category": pl.Utf8,
                "tour_mode": pl.Utf8,
                "tour_purpose": pl.Utf8,
                "summary_tour_purpose": pl.Utf8,
                "school_esc_outbound": pl.Utf8,
                "school_esc_inbound": pl.Utf8,
                "start_hour": pl.Int32,
                "end_hour": pl.Int32,
                "start_period": pl.Utf8,
                "end_period": pl.Utf8,
                "first_inbound_trip_depart": pl.Int32,
                "first_inbound_trip_period": pl.Utf8,
                "tourdur": pl.Int32,
                "o_maz": pl.Int64,
                "d_maz": pl.Int64,
                "pnr_zone_id": pl.Int64,
                "OTAZ": pl.Int32,
                "DTAZ": pl.Int32,
                "pnr_taz": pl.Int32,
                "income_segment": pl.Int64,
                "vot_bin": pl.Utf8,
                "SKIMDIST": pl.Float64,
                "NUMBER_HH": pl.Int32,
                "AUTOSUFF": pl.Int32,
                "LICENSEDDRIVERS": pl.Int32,
                "num_escortees": pl.Int64,
                "finalweight": pl.Float64,
            },
        )
    )


def _cast_trips(trips: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            trips,
            {
                "household_id": pl.Int64,
                "person_id": pl.Int64,
                "tour_id": pl.Int64,
                "trip_id": pl.Int64,
                "trip_mode": pl.Utf8,
                "trip_purpose": pl.Utf8,
                "tour_mode": pl.Utf8,
                "tour_purpose": pl.Utf8,
                "summary_tour_purpose": pl.Utf8,
                "tour_category": pl.Utf8,
                "depart_hour": pl.Int32,
                "trip_period": pl.Utf8,
                "o_maz": pl.Int64,
                "d_maz": pl.Int64,
                "pnr_zone_id": pl.Int64,
                "OTAZ": pl.Int32,
                "DTAZ": pl.Int32,
                "pnr_taz": pl.Int32,
                "parking_zone": pl.Int64,
                "origin_parking_zone": pl.Int64,
                "income_segment": pl.Int64,
                "vot_bin": pl.Utf8,
                "od_dist": pl.Float64,
                "prepared_non_motorized_distance": pl.Float64,
                "out_dir_dist": pl.Float64,
                "stops": pl.Int32,
                "inbound": pl.Int32,
                "trip_num": pl.Int32,
                "escort_event_role": pl.Utf8,
                "escort_event_trip_num": pl.Int32,
                "escort_stops_before_event": pl.Int32,
                "escort_stops_after_event": pl.Int32,
                "escort_event_match_status": pl.Utf8,
                "AUTOSUFF": pl.Int32,
                "LICENSEDDRIVERS": pl.Int32,
                "num_participants": pl.Int32,
                "finalweight": pl.Float64,
            },
        )
    )


def _cast_land_use(land_use: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            land_use,
            {
                "MAZ": pl.Int64,
                "TAZ": pl.Int64,
                "EMPLOYMENT": pl.Float64,
                "employment_count": pl.Float64,
                "student_type": pl.Utf8,
                "enrollment_count": pl.Float64,
            },
        )
    )


def _cast_vehicles(vehicles: pl.DataFrame) -> pl.DataFrame:
    return _cast_dynamic_geo_columns(
        _cast_if_present(
            vehicles,
            {
                "household_id": pl.Int64,
                "vehicle_id": pl.Int64,
                "vehicle_num": pl.Int32,
                "vehicle_type": pl.Utf8,
                "body_type": pl.Utf8,
                "fuel_type": pl.Utf8,
                "vehicle_age": pl.Int64,
                "finalweight": pl.Float64,
            },
        )
    )


def _cast_prepared_tables(state: _PrepareState) -> _PrepareState:
    state.hh = state.hh.drop(
        ["_autosuff_workers", "_autosuff_adults"],
        strict=False,
    )
    state.tours = state.tours.drop(
        ["_autosuff_workers", "_autosuff_adults"],
        strict=False,
    )
    state.trips = state.trips.drop(
        ["_autosuff_workers", "_autosuff_adults"],
        strict=False,
    )
    state.hh = _cast_households(state.hh)
    state.per = _cast_persons(state.per)
    state.day = _cast_day(state.day)
    state.tours = _cast_tours(state.tours)
    state.trips = _cast_trips(state.trips)
    state.vehicles = _cast_vehicles(state.vehicles)
    state.land_use = _cast_land_use(state.land_use)
    return state
