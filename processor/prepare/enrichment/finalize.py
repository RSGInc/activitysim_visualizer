"""Final casts and RunData reconstruction for prepare enrichment."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.prepare.availability import attach_table_availability
from processor.prepare.enrichment.columns import _cast_if_present
from processor.prepare.enrichment.types import _PrepareState


def _cast_households(hh: pl.DataFrame) -> pl.DataFrame:
    return _cast_if_present(
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


def _cast_persons(per: pl.DataFrame) -> pl.DataFrame:
    return _cast_if_present(
        per,
        {
            "household_id": pl.Int64,
            "person_id": pl.Int64,
            "finalweight": pl.Float64,
            "HGEO": pl.Utf8,
            "WGEO": pl.Utf8,
            "is_worker": pl.Utf8,
            "student_type": pl.Utf8,
            "work_from_home": pl.Utf8,
            "mandatory_tour_frequency": pl.Utf8,
            "distance_to_work": pl.Float64,
            "distance_to_school": pl.Float64,
        },
    )


def _cast_tours(tours: pl.DataFrame) -> pl.DataFrame:
    return _cast_if_present(
        tours,
        {
            "household_id": pl.Int64,
            "person_id": pl.Int64,
            "tour_id": pl.Int64,
            "tour_category": pl.Utf8,
            "tour_mode": pl.Utf8,
            "tour_purpose": pl.Utf8,
            "summary_tour_purpose": pl.Utf8,
            "start_hour": pl.Int32,
            "end_hour": pl.Int32,
            "tourdur": pl.Int32,
            "OTAZ": pl.Int32,
            "DTAZ": pl.Int32,
            "income_segment": pl.Int64,
            "vot_bin": pl.Utf8,
            "SKIMDIST": pl.Float64,
            "NUMBER_HH": pl.Int32,
            "AUTOSUFF": pl.Int32,
            "LICENSEDDRIVERS": pl.Int32,
            "finalweight": pl.Float64,
        },
    )


def _cast_trips(trips: pl.DataFrame) -> pl.DataFrame:
    return _cast_if_present(
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
            "OTAZ": pl.Int32,
            "DTAZ": pl.Int32,
            "parking_zone": pl.Int64,
            "origin_parking_zone": pl.Int64,
            "income_segment": pl.Int64,
            "vot_bin": pl.Utf8,
            "od_dist": pl.Float64,
            "out_dir_dist": pl.Float64,
            "stops": pl.Int32,
            "inbound": pl.Int32,
            "trip_num": pl.Int32,
            "AUTOSUFF": pl.Int32,
            "LICENSEDDRIVERS": pl.Int32,
            "num_participants": pl.Int32,
            "finalweight": pl.Float64,
        },
    )


def _cast_land_use(land_use: pl.DataFrame) -> pl.DataFrame:
    return _cast_if_present(
        land_use,
        {
            "MAZ": pl.Int64,
            "EMPLOYMENT": pl.Float64,
            "employment_count": pl.Float64,
            "student_type": pl.Utf8,
            "enrollment_count": pl.Float64,
        },
    )


def _cast_prepared_tables(state: _PrepareState) -> _PrepareState:
    state.hh = _cast_households(state.hh)
    state.per = _cast_persons(state.per)
    state.tours = _cast_tours(state.tours)
    state.trips = _cast_trips(state.trips)
    state.land_use = _cast_land_use(state.land_use)
    return state


def _finalize_prepared_run(state: _PrepareState) -> RunData:
    return attach_table_availability(
        RunData(
            label=state.label,
            run_dir=state.run_dir,
            skim_file=state.skim_file,
            hh=state.hh,
            per=state.per,
            tours=state.tours,
            trips=state.trips,
            joint_participants=state.joint_participants,
            land_use=state.land_use,
            skim_matrix=state.skim,
            skim_zone_map=state.skim_map,
            hh_weight_col=state.hh_weight_col,
            person_weight_col=state.person_weight_col,
            trip_weight_col=state.trip_weight_col,
        ),
        table_states=state.table_states,
        table_reasons=state.table_reasons,
    )
