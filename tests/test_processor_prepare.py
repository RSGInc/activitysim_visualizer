from __future__ import annotations

from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.models import RunData as ProcessorRunData
from processor.prepare.availability import (
    table_availability as processor_table_availability,
    table_unavailable_reasons as processor_table_unavailable_reasons,
)
from processor.prepare.enrichment.columns import (
    resolve_source_column as processor_resolve_source_column,
)
from processor.prepare.enrichment.pipeline import (
    prepare_data as processor_prepare_data,
)
from processor.prepare.reader import (
    read_run as processor_read_run,
    resolve_skim_path as processor_resolve_skim_path,
)
from processor.summarize.cache_types import strip_weights
from processor.summarize.summaries import tour, trip
from processor.summarize.summaries.long_term import (
    external_workplace_loc,
    internal_vs_external,
    school_loc_vs_land_use_enrollment,
    vehicle_char_age,
    vehicle_char_body,
    vehicle_char_fuel,
    workplace_vs_land_use_employment,
)
from processor.summarize.summaries.tour_geography import (
    ext_non_mand_tour_loc,
    int_vs_ext_non_mand_tour_freq,
)
from runtime.config import Config


def _write_config(
    tmp_path: Path,
    *,
    extra_lines: list[str] | None = None,
) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        'name: "Processor Prepare Test"',
        "runs: []",
        "summaries:",
        "  root: summary_cache",
        "visualizer:",
        '  dashboard_title: "Processor Prepare Test"',
    ]
    if extra_lines:
        lines.extend(extra_lines)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _raw_run() -> ProcessorRunData:
    return ProcessorRunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [2],
                "hhsize": [3],
                "num_workers": [1],
                "num_adults": [2],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
                "home_zone_id": [10],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": [1],
                "tour_type": ["eatout"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
                "start": [8],
                "end": [10],
                "duration": [2],
                "origin": [10],
                "destination": [20],
                "stop_frequency": ["1out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001],
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "trip_mode": ["DRIVEALONE"],
                "purpose": ["shop"],
                "depart": [8],
                "outbound": [True],
                "trip_num": [1],
                "origin": [10],
                "destination": [20],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(
            {"zone_id": [10, 20], "TAZ": [10, 20], "EMPLOY_TOT": [7, 8]}
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_atwork_subtour_frequency() -> ProcessorRunData:
    return ProcessorRunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [1],
                "hhsize": [2],
                "num_workers": [1],
                "num_adults": [1],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
                "home_zone_id": [10],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": ["eatout"],
                "tour_type": ["eatout"],
                "tour_mode": ["WALK"],
                "tour_category": ["atwork"],
                "atwork_subtour_frequency": ["1_eat"],
                "start": [8],
                "end": [9],
                "duration": [1],
                "origin": [10],
                "destination": [20],
                "stop_frequency": ["0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001],
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "trip_mode": ["WALK"],
                "purpose": ["work"],
                "depart": [8],
                "outbound": [True],
                "trip_num": [1],
                "origin": [10],
                "destination": [20],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame({"zone_id": [10, 20], "TAZ": [10, 20], "EMPLOY_TOT": [7, 8]}),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_student_enrollment_inputs() -> ProcessorRunData:
    return ProcessorRunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2, 3],
                "home_zone_id": [10, 20, 30],
                "auto_ownership": [2, 1, 0],
                "hhsize": [3, 2, 1],
                "num_workers": [1, 0, 0],
                "num_adults": [2, 1, 1],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 201, 301],
                "household_id": [1, 2, 3],
                "ptype": [1, 6, 3],
                "home_zone_id": [10, 20, 30],
                "workplace_zone_id": [10, None, None],
                "school_zone_id": [None, 20, 30],
                "is_worker": [True, False, False],
                "is_student": [False, True, True],
                "is_university": [False, False, True],
                "school_segment": [None, 1, 3],
            }
        ),
        tours=pl.DataFrame(
            {"tour_id": [], "person_id": [], "household_id": []},
            schema={
                "tour_id": pl.Int64,
                "person_id": pl.Int64,
                "household_id": pl.Int64,
            },
        ),
        trips=pl.DataFrame(
            {"trip_id": [], "tour_id": [], "person_id": [], "household_id": []},
            schema={
                "trip_id": pl.Int64,
                "tour_id": pl.Int64,
                "person_id": pl.Int64,
                "household_id": pl.Int64,
            },
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(
            {
                "MAZ": [10, 20, 30],
                "TAZ": [10, 20, 30],
                "EMP_TOTAL": [7, 8, 9],
                "ENROLLGRADEKto8": [0, 50, 0],
                "ENROLLGRADE9to12": [0, 25, 0],
                "COLLEGEENROLL": [0, 0, 100],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_escort_event_inputs() -> ProcessorRunData:
    return ProcessorRunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2, 3],
                "home_zone_id": [10, 20, 30],
                "auto_ownership": [2, 1, 1],
                "hhsize": [2, 2, 1],
                "num_workers": [1, 1, 1],
                "num_adults": [1, 1, 1],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103, 201, 202],
                "household_id": [1, 2, 3, 1, 2],
                "ptype": [1, 2, 1, 6, 7],
                "home_zone_id": [10, 20, 30, 10, 20],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 1002, 1003, 2001, 2002],
                "person_id": [101, 102, 103, 201, 202],
                "household_id": [1, 2, 3, 1, 2],
                "primary_purpose": ["escort", "escort", "escort", "school", "school"],
                "tour_type": ["escort", "escort", "escort", "school", "school"],
                "tour_mode": ["DRIVE", "DRIVE", "DRIVE", "WALK", "WALK"],
                "tour_category": [
                    "non-mandatory",
                    "non-mandatory",
                    "non-mandatory",
                    "mandatory",
                    "mandatory",
                ],
                "start": [8, 8, 8, 8, 8],
                "end": [10, 10, 10, 10, 10],
                "duration": [2, 2, 2, 2, 2],
                "origin": [10, 20, 30, 10, 20],
                "destination": [20, 30, 40, 20, 30],
                "stop_frequency": ["2out_2in", "2out_0in", "0out_1in", "0out_0in", "0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [
                    5001,
                    5002,
                    5003,
                    5004,
                    5005,
                    5006,
                    6001,
                    6002,
                    7001,
                    7002,
                    7003,
                    8001,
                    9001,
                    9002,
                ],
                "tour_id": [
                    1001,
                    1001,
                    1001,
                    1001,
                    1001,
                    1001,
                    2001,
                    2001,
                    1002,
                    1002,
                    1002,
                    2002,
                    1003,
                    1003,
                ],
                "person_id": [
                    101,
                    101,
                    101,
                    101,
                    101,
                    101,
                    201,
                    201,
                    102,
                    102,
                    102,
                    202,
                    103,
                    103,
                ],
                "household_id": [1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3],
                "trip_mode": [
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "WALK",
                    "WALK",
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "DRIVEALONE",
                    "WALK",
                    "DRIVEALONE",
                    "DRIVEALONE",
                ],
                "purpose": [
                    "eatout",
                    "escort",
                    "eatout",
                    "shopping",
                    "home",
                    "eatout",
                    "school",
                    "home",
                    "escort",
                    "escort",
                    "home",
                    "school",
                    "home",
                    "shopping",
                ],
                "depart": [8, 9, 10, 11, 12, 13, 8, 15, 8, 9, 10, 8, 8, 9],
                "outbound": [
                    True,
                    True,
                    True,
                    False,
                    False,
                    False,
                    True,
                    False,
                    True,
                    True,
                    True,
                    True,
                    False,
                    False,
                ],
                "trip_num": [1, 2, 3, 1, 2, 3, 1, 1, 1, 2, 3, 1, 1, 2],
                "origin": [10, 11, 12, 20, 21, 22, 10, 20, 20, 21, 22, 20, 30, 31],
                "destination": [11, 12, 20, 21, 22, 10, 20, 10, 21, 22, 30, 30, 31, 30],
                "escort_participants": [
                    None,
                    "201",
                    None,
                    None,
                    "201",
                    None,
                    "201",
                    "201",
                    "202",
                    "202",
                    None,
                    "202",
                    "999",
                    None,
                ],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(
            {"zone_id": [10, 20, 30, 40], "TAZ": [10, 20, 30, 40], "EMPLOY_TOT": [7, 8, 9, 10]}
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_income_segment(
    *,
    label: str,
    income_segment: int,
) -> ProcessorRunData:
    run = _raw_run()
    return ProcessorRunData(
        label=label,
        run_dir=run.run_dir,
        skim_file=run.skim_file,
        hh=run.hh.with_columns(pl.lit(income_segment).alias("income_segment")),
        per=run.per,
        tours=run.tours,
        trips=run.trips,
        joint_participants=run.joint_participants,
        land_use=run.land_use,
        skim_matrix=run.skim_matrix,
        skim_zone_map=run.skim_zone_map,
    )


def _raw_run_with_escort_linkage_inputs() -> ProcessorRunData:
    return ProcessorRunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [1],
                "hhsize": [2],
                "num_workers": [1],
                "num_adults": [1],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 201],
                "household_id": [1, 1],
                "ptype": [1, 6],
                "home_zone_id": [10, 10],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 1],
                "primary_purpose": ["escort", "school"],
                "tour_type": ["escort", "school"],
                "tour_mode": ["DRIVE", "WALK"],
                "tour_category": ["non-mandatory", "mandatory"],
                "start": [8, 8],
                "end": [10, 10],
                "duration": [2, 2],
                "origin": [10, 10],
                "destination": [20, 20],
                "out_escort_type": ["pure_escort", None],
                "inb_escort_type": ["pure_escort", None],
                "out_escorted_tour_ids": ["2001", None],
                "inb_escorted_tour_ids": ["2001", None],
                "out_chauffeur_tour_id": [None, 1001],
                "inb_chauffeur_tour_id": [None, 1001],
                "stop_frequency": ["1out_0in", "0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001, 5002, 5003, 6001, 6002],
                "tour_id": [1001, 1001, 1001, 2001, 2001],
                "person_id": [101, 101, 101, 201, 201],
                "household_id": [1, 1, 1, 1, 1],
                "trip_mode": ["DRIVE", "DRIVE", "DRIVE", "WALK", "WALK"],
                "purpose": ["shopping", "escort", "home", "school", "home"],
                "depart": [8, 9, 15, 8, 15],
                "outbound": [True, True, False, True, False],
                "trip_num": [1, 2, 1, 1, 1],
                "origin": [10, 15, 20, 10, 20],
                "destination": [15, 20, 10, 20, 10],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(
            {"zone_id": [10, 15, 20], "TAZ": [10, 15, 20], "EMPLOY_TOT": [1, 1, 1]}
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_processor_prepare_feature_modules_expose_canonical_prepare_helpers() -> None:
    assert callable(processor_prepare_data)
    assert callable(processor_read_run)
    assert callable(processor_resolve_skim_path)
    assert callable(processor_resolve_source_column)


def test_processor_prepare_data_exposes_the_same_prepared_contract(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = processor_prepare_data(_raw_run(), config)

    assert isinstance(prepared, ProcessorRunData)
    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]
    assert prepared.tours["start_hour"].to_list() == [8]
    assert prepared.trips["trip_purpose"].to_list() == ["shop"]
    assert prepared.land_use["MAZ"].to_list() == [10, 20]
    assert prepared.land_use["EMPLOYMENT"].to_list() == [7, 8]
    assert prepared.land_use["employment_count"].to_list() == [7.0, 8.0]


def test_processor_prepare_data_derives_first_inbound_trip_depart_on_tours(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=raw.per,
        tours=raw.tours,
        trips=pl.DataFrame(
            {
                "trip_id": [5001, 5002, 5003],
                "tour_id": [1001, 1001, 1001],
                "person_id": [101, 101, 101],
                "household_id": [1, 1, 1],
                "trip_mode": ["DRIVEALONE", "DRIVEALONE", "DRIVEALONE"],
                "purpose": ["shop", "home", "home"],
                "depart": [8, 17, 18],
                "outbound": [True, False, False],
                "trip_num": [1, 1, 2],
                "origin": [10, 20, 21],
                "destination": [20, 21, 10],
            }
        ),
        joint_participants=raw.joint_participants,
        land_use=raw.land_use,
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours["first_inbound_trip_depart"].to_list() == [17]
    assert prepared.tours["start_hour"].to_list() == [8]


def test_processor_prepare_data_materializes_shared_zone_columns_for_maz_models(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
        ],
    )

    prepared = processor_prepare_data(_raw_run(), config)

    assert prepared.trips["o_maz"].to_list() == [10]
    assert prepared.trips["d_maz"].to_list() == [20]
    assert prepared.tours["o_maz"].to_list() == [10]
    assert prepared.tours["d_maz"].to_list() == [20]
    assert prepared.trips["OTAZ"].to_list() == [10]
    assert prepared.trips["DTAZ"].to_list() == [20]
    assert prepared.tours["OTAZ"].to_list() == [10]
    assert prepared.tours["DTAZ"].to_list() == [20]


def test_processor_prepare_data_carries_atwork_subtour_frequency_to_trips(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = processor_prepare_data(_raw_run_with_atwork_subtour_frequency(), config)

    assert prepared.trips["atwork_subtour_frequency"].to_list() == ["1_eat"]


def test_processor_prepare_data_derives_num_joint_tours_from_joint_participants(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=pl.DataFrame(
            {
                "person_id": [101, 102],
                "household_id": [1, 1],
                "ptype": [1, 2],
                "home_zone_id": [10, 10],
            }
        ),
        tours=raw.tours,
        trips=raw.trips,
        joint_participants=pl.DataFrame(
            {
                "tour_id": [2001, 2001, 2002],
                "person_id": [101, 102, 101],
            }
        ),
        land_use=raw.land_use,
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
    )

    prepared = processor_prepare_data(raw, config).per.sort("person_id")

    assert prepared["num_joint_tours"].to_list() == [2, 1]


def test_processor_prepare_data_uses_zone_id_as_maz_fallback_for_trip_skim_distance(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "  maz_col: [MAZ, zone_id]",
            "  taz_col: [TAZ]",
        ],
    )
    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=raw.per,
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": ["work"],
                "tour_type": ["work"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["mandatory"],
                "start": [8],
                "end": [10],
                "duration": [2],
                "origin": [100],
                "destination": [200],
                "stop_frequency": ["0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001],
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "trip_mode": ["DRIVEALONE"],
                "purpose": ["work"],
                "depart": [8],
                "outbound": [True],
                "trip_num": [1],
                "origin": [100],
                "destination": [200],
            }
        ),
        joint_participants=raw.joint_participants,
        land_use=pl.DataFrame(
            {
                "zone_id": [100, 200],
                "TAZ": [1, 2],
                "EMPLOY_TOT": [7, 8],
            }
        ),
        skim_matrix=pl.DataFrame([[0.0, 12.5], [12.5, 0.0]]).to_numpy(),
        skim_zone_map=None,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours["OTAZ"].to_list() == [1]
    assert prepared.tours["DTAZ"].to_list() == [2]
    assert prepared.trips["OTAZ"].to_list() == [1]
    assert prepared.trips["DTAZ"].to_list() == [2]
    assert prepared.trips["od_dist"].to_list() == [12.5]


def test_processor_prepare_data_surfaces_null_distance_fields_without_usable_zone_mapping(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "  maz_col: [MAZ, zone_id]",
            "  taz_col: [TAZ]",
        ],
    )
    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=raw.per,
        tours=raw.tours,
        trips=raw.trips,
        joint_participants=raw.joint_participants,
        land_use=pl.DataFrame(),
        skim_matrix=pl.DataFrame([[0.0, 12.5], [12.5, 0.0]]).to_numpy(),
        skim_zone_map=None,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours["OTAZ"].to_list() == [None]
    assert prepared.tours["DTAZ"].to_list() == [None]
    assert prepared.trips["OTAZ"].to_list() == [None]
    assert prepared.trips["DTAZ"].to_list() == [None]
    assert prepared.tours["SKIMDIST"].to_list() == [None]
    assert prepared.trips["od_dist"].to_list() == [None]
    assert prepared.trips["out_dir_dist"].to_list() == [None]
    assert prepared.prepare_diagnostics["tours.OTAZ"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["tours.DTAZ"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["trips.OTAZ"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["trips.DTAZ"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["tours.SKIMDIST"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["trips.od_dist"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["trips.out_dir_dist"]["unresolved"] == 1
    assert tour.tour_distance(prepared, config).is_empty()
    assert trip.trip_distance(prepared, config).is_empty()
    assert trip.stop_ood_distance(prepared, config).is_empty()


def test_processor_prepare_data_keeps_legitimate_zero_skim_values(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "  maz_col: [MAZ, zone_id]",
            "  taz_col: [TAZ]",
        ],
    )
    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
                "home_zone_id": [100],
                "workplace_zone_id": [100],
                "school_zone_id": [100],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": ["work"],
                "tour_type": ["work"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["mandatory"],
                "start": [8],
                "end": [10],
                "duration": [2],
                "origin": [100],
                "destination": [100],
                "stop_frequency": ["0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001],
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "trip_mode": ["DRIVEALONE"],
                "purpose": ["work"],
                "depart": [8],
                "outbound": [True],
                "trip_num": [1],
                "origin": [100],
                "destination": [100],
            }
        ),
        joint_participants=raw.joint_participants,
        land_use=pl.DataFrame(
            {
                "zone_id": [100],
                "TAZ": [1],
                "EMPLOY_TOT": [7],
            }
        ),
        skim_matrix=pl.DataFrame([[0.0]]).to_numpy(),
        skim_zone_map=None,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.per["distance_to_work"].to_list() == [0.0]
    assert prepared.per["distance_to_school"].to_list() == [0.0]
    assert prepared.tours["SKIMDIST"].to_list() == [0.0]
    assert prepared.trips["od_dist"].to_list() == [0.0]
    assert prepared.trips["out_dir_dist"].to_list() == [0.0]


def test_processor_prepare_data_records_identity_like_taz_mapping_failures(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "  maz_col: [MAZ, zone_id]",
            "  taz_col: [TAZ]",
        ],
    )
    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
                "home_zone_id": [100],
                "workplace_zone_id": [200],
                "school_zone_id": [200],
            }
        ),
        tours=raw.tours.with_columns(
            pl.lit(100).alias("origin"),
            pl.lit(200).alias("destination"),
        ),
        trips=raw.trips.with_columns(
            pl.lit(100).alias("origin"),
            pl.lit(200).alias("destination"),
        ),
        joint_participants=raw.joint_participants,
        land_use=pl.DataFrame(
            {
                "zone_id": [100, 200],
                "TAZ": [100, 200],
                "EMPLOY_TOT": [7, 8],
            }
        ),
        skim_matrix=pl.DataFrame([[0.0, 12.5], [12.5, 0.0]]).to_numpy(),
        skim_zone_map=None,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.per["distance_to_work"].to_list() == [None]
    assert prepared.per["distance_to_school"].to_list() == [None]
    assert prepared.tours["SKIMDIST"].to_list() == [None]
    assert prepared.trips["od_dist"].to_list() == [None]
    assert prepared.prepare_diagnostics["persons.distance_to_work"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["persons.distance_to_school"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["tours.SKIMDIST"]["unresolved"] == 1
    assert prepared.prepare_diagnostics["trips.od_dist"]["unresolved"] == 1
    assert "persons.distance_to_work" in caplog.text
    assert "tours.SKIMDIST" in caplog.text


def test_processor_prepare_data_derives_exact_escort_event_fields_conservatively(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = processor_prepare_data(_raw_run_with_escort_event_inputs(), config)
    trips = prepared.trips.sort("trip_id")

    by_trip = {
        row["trip_id"]: row
        for row in trips.select(
            [
                "trip_id",
                "escort_event_role",
                "escort_event_trip_num",
                "escort_stops_before_event",
                "escort_stops_after_event",
                "escort_event_match_status",
            ]
        ).to_dicts()
    }

    assert by_trip[5002] == {
        "trip_id": 5002,
        "escort_event_role": "dropoff",
        "escort_event_trip_num": 2,
        "escort_stops_before_event": 1,
        "escort_stops_after_event": 1,
        "escort_event_match_status": "matched",
    }
    assert by_trip[5005] == {
        "trip_id": 5005,
        "escort_event_role": "pickup",
        "escort_event_trip_num": 2,
        "escort_stops_before_event": 1,
        "escort_stops_after_event": 1,
        "escort_event_match_status": "matched",
    }
    assert by_trip[7001]["escort_event_match_status"] == "ambiguous"
    assert by_trip[7001]["escort_event_role"] is None
    assert by_trip[7002]["escort_event_match_status"] == "ambiguous"
    assert by_trip[7002]["escort_event_trip_num"] is None
    assert by_trip[9001]["escort_event_match_status"] == "unmatched"
    assert by_trip[9001]["escort_event_role"] is None
    assert by_trip[6001]["escort_event_match_status"] is None


def test_processor_prepare_data_can_fallback_to_escort_tour_linkages_for_event_fields(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = processor_prepare_data(_raw_run_with_escort_linkage_inputs(), config)
    trips = prepared.trips.sort("trip_id")

    by_trip = {
        row["trip_id"]: row
        for row in trips.select(
            [
                "trip_id",
                "escort_event_role",
                "escort_event_trip_num",
                "escort_stops_before_event",
                "escort_stops_after_event",
                "escort_event_match_status",
            ]
        ).to_dicts()
    }

    assert by_trip[5002] == {
        "trip_id": 5002,
        "escort_event_role": "dropoff",
        "escort_event_trip_num": 2,
        "escort_stops_before_event": 1,
        "escort_stops_after_event": 0,
        "escort_event_match_status": "matched",
    }
    assert by_trip[5003] == {
        "trip_id": 5003,
        "escort_event_role": "pickup",
        "escort_event_trip_num": 1,
        "escort_stops_before_event": 0,
        "escort_stops_after_event": 0,
        "escort_event_match_status": "matched",
    }


def test_processor_prepare_data_can_normalize_vot_bins_by_run_label(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  vot_bins:",
            "    output_column: vot_bin",
            "    source_column: income_segment",
            "    mappings:",
            "      estimation-output:",
            "        1: L",
            "        2: M",
            "        3: M",
            "        4: H",
            "      filtered:",
            "        1: L",
            "        2: L",
            "        3: M",
            "        4: M",
            "        5: H",
            "        6: H",
        ],
    )

    estimation_run = _raw_run_with_income_segment(
        label="Estimation Output",
        income_segment=2,
    )
    filtered_run = _raw_run_with_income_segment(
        label="Filtered",
        income_segment=2,
    )

    estimation_prepared = processor_prepare_data(estimation_run, config)
    filtered_prepared = processor_prepare_data(filtered_run, config)

    assert estimation_prepared.trips["vot_bin"].to_list() == ["M"]
    assert estimation_prepared.tours["vot_bin"].to_list() == ["M"]
    assert filtered_prepared.trips["vot_bin"].to_list() == ["L"]
    assert filtered_prepared.tours["vot_bin"].to_list() == ["L"]


def test_config_normalizes_escort_aliases_and_default_category(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  school_esc_outbound: [school_esc_outbound, school_escort_outbound]",
            "  school_esc_inbound: school_escort_inbound",
            "  num_escortees: [num_escortees, num_escorted]",
            "  out_escorted_tour_ids: out_ids",
            "  inb_escorted_tour_ids: in_ids",
            "  out_escorting_type: out_parent_code",
            "  inb_escorting_type: in_parent_code",
        ],
    )

    assert config.col_school_esc_outbound == [
        "school_esc_outbound",
        "school_escort_outbound",
    ]
    assert config.col_school_esc_inbound == ["school_escort_inbound"]
    assert config.col_num_escortees == ["num_escortees", "num_escorted"]
    assert config.col_out_escorted_tour_ids == ["out_ids"]
    assert config.col_inb_escorted_tour_ids == ["in_ids"]
    assert config.col_out_escorting_type == ["out_parent_code"]
    assert config.col_inb_escorting_type == ["in_parent_code"]
    assert config.label_value("escort", "not_escorted") == "No Escort"
    assert config.label_value("escort", "pure_escort") == "Pure Escort"
    assert config.label_value("escort", "ride_share") == "Ride Share"


def test_processor_prepare_normalizes_escort_fields_and_derives_num_escortees(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    raw.tours = pl.DataFrame(
        {
            "tour_id": [1001, 1002, 1003, 1004],
            "person_id": [101, 101, 101, 101],
            "household_id": [1, 1, 1, 1],
            "primary_purpose": ["escort", "escort", "school", "school"],
            "tour_type": ["escort", "escort", "school", "school"],
            "tour_mode": ["DRIVE", "DRIVE", "WALK", "WALK"],
            "tour_category": ["non-mandatory", "non-mandatory", "mandatory", "mandatory"],
            "start": [8, 9, 10, 11],
            "end": [9, 10, 11, 12],
            "duration": [1, 1, 1, 1],
            "school_esc_outbound": ["ride_share", "   ", "pure_escort", None],
            "school_esc_inbound": [None, None, None, ""],
            "out_escort_type": [None, "pure_escort", "ride_share", None],
            "inb_escort_type": [None, None, "ride_share", None],
            "out_escorting_type": [0, 2, 0, 1],
            "inb_escorting_type": [0, 0, 0, 2],
            "out_escorted_tour_ids": [None, "11_12", None, ""],
            "inb_escorted_tour_ids": [None, None, None, "21_22_23"],
            "num_escortees": [None, None, 5, None],
        }
    )

    prepared = processor_prepare_data(raw, config).tours.sort("tour_id")

    assert prepared["school_esc_outbound"].to_list() == [
        "ride_share",
        "pure_escort",
        "pure_escort",
        "pure_escort",
    ]
    assert prepared["school_esc_inbound"].to_list() == [
        "not_escorted",
        "not_escorted",
        "ride_share",
        "ride_share",
    ]
    assert prepared["num_escortees"].to_list() == [0, 2, 5, 3]


def test_processor_read_run_returns_partial_data_when_optional_tables_are_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_households.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10]}).write_csv(
        run_dir / "final_trips.csv"
    )

    loaded = processor_read_run(run_dir, config, label="Run A")

    assert loaded.hh["household_id"].to_list() == [1]
    assert loaded.joint_participants.is_empty()
    assert loaded.land_use.is_empty()
    assert processor_table_availability(loaded)["joint_tour_participants"] == "unavailable"
    assert processor_table_availability(loaded)["land_use"] == "unavailable"
    assert "Cannot find" in processor_table_unavailable_reasons(loaded)["land_use"]


def test_processor_read_run_marks_misnamed_configured_table_as_unavailable(
    tmp_path: Path,
) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Processor Prepare Test"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Processor Prepare Test"',
                "files:",
                "  trips: definitely_not_trips",
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_yaml(config_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_households.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000]}).write_csv(run_dir / "final_trips.csv")
    pl.DataFrame({"tour_id": [], "person_id": []}).write_csv(
        run_dir / "final_joint_tour_participants.csv"
    )
    pl.DataFrame({"zone_id": [1]}).write_csv(run_dir / "final_land_use.csv")

    loaded = processor_read_run(run_dir, config, label="Run A")

    assert loaded.trips.is_empty()
    assert processor_table_availability(loaded)["trips"] == "unavailable"
    assert "definitely_not_trips" in processor_table_unavailable_reasons(loaded)["trips"]


def test_config_normalizes_per_run_file_map_and_rejects_invalid_keys(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path / "valid",
        extra_lines=[
            "files:",
            "  households: final_households",
            "runs:",
            '  - dir: "run_a"',
            '    label: "Run A"',
            "    file_map:",
            "      households: final_hh",
            "      trips: trip_linked",
        ],
    )

    assert config.files["households"] == "final_households"
    assert config.runs[0]["file_map"] == {
        "households": "final_hh",
        "trips": "trip_linked",
    }

    invalid_path = tmp_path / "invalid" / "config.yaml"
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_text(
        "\n".join(
            [
                'name: "Invalid File Map Config"',
                "runs:",
                '  - dir: "run_a"',
                '    label: "Run A"',
                "    file_map:",
                "      households_alias: final_hh",
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Invalid File Map Config"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported table ids"):
        Config.from_yaml(invalid_path)


def test_processor_read_run_uses_per_run_file_map_with_global_fallback(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "files:",
            "  households: final_households",
            "  persons: final_persons",
            "  tours: final_tours",
            "  trips: final_trips",
            "  joint_tour_participants: final_joint_tour_participants",
            "  land_use: final_land_use",
        ],
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_hh.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10]}).write_csv(
        run_dir / "trip_linked.csv"
    )
    pl.DataFrame({"tour_id": [], "person_id": []}).write_csv(
        run_dir / "final_joint_tour_participants.csv"
    )
    pl.DataFrame({"zone_id": [1]}).write_csv(run_dir / "final_land_use.csv")

    loaded = processor_read_run(
        run_dir,
        config,
        label="Run A",
        file_map={"households": "final_hh", "trips": "trip_linked"},
    )

    assert loaded.hh["household_id"].to_list() == [1]
    assert loaded.per["person_id"].to_list() == [10]
    assert loaded.trips["trip_id"].to_list() == [1000]
    assert processor_table_availability(loaded)["households"] == "available"
    assert processor_table_availability(loaded)["persons"] == "available"


def test_processor_read_run_uses_fallback_land_use_when_primary_missing(
    tmp_path: Path,
) -> None:
    shared_land_use = (tmp_path / "shared_land_use.csv").resolve()
    shared_land_use.write_text(
        "\n".join(["zone_id,TAZ", "1,1", "2,2"]),
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        extra_lines=[
            "fallback_files:",
            f"  land_use: {shared_land_use}",
        ],
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_households.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10]}).write_csv(
        run_dir / "final_trips.csv"
    )
    pl.DataFrame({"tour_id": [], "person_id": []}).write_csv(
        run_dir / "final_joint_tour_participants.csv"
    )

    loaded = processor_read_run(run_dir, config, label="Run A")

    assert loaded.land_use["zone_id"].to_list() == [1, 2]
    assert processor_table_availability(loaded)["land_use"] == "available"
    assert "land_use" not in processor_table_unavailable_reasons(loaded)


def test_processor_read_run_marks_misnamed_per_run_override_as_unavailable(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "files:",
            "  households: final_households",
            "  persons: final_persons",
            "  tours: final_tours",
            "  trips: final_trips",
            "  joint_tour_participants: final_joint_tour_participants",
            "  land_use: final_land_use",
        ],
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_households.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000]}).write_csv(run_dir / "final_trips.csv")
    pl.DataFrame({"tour_id": [], "person_id": []}).write_csv(
        run_dir / "final_joint_tour_participants.csv"
    )
    pl.DataFrame({"zone_id": [1]}).write_csv(run_dir / "final_land_use.csv")

    loaded = processor_read_run(
        run_dir,
        config,
        label="Run A",
        file_map={"trips": "definitely_not_trips"},
    )

    assert loaded.trips.is_empty()
    assert processor_table_availability(loaded)["trips"] == "unavailable"
    assert (
        "definitely_not_trips"
        in processor_table_unavailable_reasons(loaded)["trips"]
    )


def test_processor_prepare_derives_default_student_types_and_land_use_overlay(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    assert prepared.per["student_type"].to_list() == [None, "School", "University"]
    school_overlay = prepared.land_use.filter(pl.col("student_type") == "School")
    university_overlay = prepared.land_use.filter(pl.col("student_type") == "University")
    assert school_overlay["enrollment_count"].to_list() == [0.0, 75.0, 0.0]
    assert university_overlay["enrollment_count"].to_list() == [0.0, 0.0, 100.0]
    assert prepared.land_use.filter(pl.col("student_type").is_null())["EMPLOYMENT"].to_list() == [
        7.0,
        8.0,
        9.0,
    ]


def test_long_term_comparisons_use_prepare_time_employment_and_student_derivations(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    workplace = workplace_vs_land_use_employment(prepared, config)
    school = school_loc_vs_land_use_enrollment(prepared, config)

    assert workplace.is_empty() is False
    assert workplace.columns == [
        "geography_type",
        "geography_id",
        "employment_count",
        "worker_count",
    ]
    assert school.is_empty() is False
    assert set(school["student_type"].unique().to_list()) == {"School", "University"}


def test_processor_prepare_adds_configured_geography_aggregation_columns(
    tmp_path: Path,
) -> None:
    geography_csv = tmp_path / "district_lookup.csv"
    geography_csv.write_text(
        "\n".join(["MAZ,district", "10,North", "20,South"]),
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        Urban: [10]",
            "        Rural: [20]",
            "    district:",
            "      source_zone_system: maz",
            f"      file: {geography_csv.name}",
            "      zone_id_col: MAZ",
            "      geography_col: district",
        ],
    )

    prepared = processor_prepare_data(_raw_run(), config)

    assert prepared.hh["home_geo__county"].to_list() == ["Urban"]
    assert prepared.hh["home_geo__district"].to_list() == ["North"]
    assert prepared.per["home_geo__county"].to_list() == ["Urban"]
    assert prepared.per["home_geo__district"].to_list() == ["North"]
    assert prepared.land_use["land_use_geo__county"].to_list() == ["Urban", "Rural"]
    assert prepared.land_use["land_use_geo__district"].to_list() == ["North", "South"]
    assert prepared.tours["origin_geo__county"].to_list() == ["Urban"]
    assert prepared.tours["destination_geo__county"].to_list() == ["Rural"]
    assert prepared.tours["origin_geo__district"].to_list() == ["North"]
    assert prepared.tours["destination_geo__district"].to_list() == ["South"]
    assert prepared.trips["origin_geo__county"].to_list() == ["Urban"]
    assert prepared.trips["destination_geo__district"].to_list() == ["South"]


def test_processor_prepare_skips_geography_aggregation_columns_when_geography_disabled(
    tmp_path: Path,
) -> None:
    geography_csv = tmp_path / "district_lookup.csv"
    geography_csv.write_text(
        "\n".join(["MAZ,district", "10,North", "20,South"]),
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: false",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        Urban: [10]",
            "        Rural: [20]",
            "    district:",
            "      source_zone_system: maz",
            f"      file: {geography_csv.name}",
            "      zone_id_col: MAZ",
            "      geography_col: district",
        ],
    )

    prepared = processor_prepare_data(_raw_run(), config)

    assert "home_geo__county" not in prepared.hh.columns
    assert "home_geo__district" not in prepared.hh.columns
    assert "land_use_geo__county" not in prepared.land_use.columns
    assert "land_use_geo__district" not in prepared.land_use.columns
    assert "origin_geo__county" not in prepared.tours.columns
    assert "destination_geo__district" not in prepared.trips.columns


def test_long_term_comparison_summaries_emit_configured_geography_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        West: [10]",
            "        Central: [20]",
            "        East: [30]",
        ],
    )
    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    workplace = workplace_vs_land_use_employment(prepared, config)
    school = school_loc_vs_land_use_enrollment(prepared, config)

    assert "county" in workplace["geography_type"].to_list()
    assert (
        workplace.filter(pl.col("geography_type") == "county")
        .sort("geography_id")
        .select(["geography_id", "employment_count", "worker_count"])
        .to_dicts()
        == [
            {"geography_id": "Central", "employment_count": 8.0, "worker_count": 0.0},
            {"geography_id": "East", "employment_count": 9.0, "worker_count": 0.0},
            {"geography_id": "West", "employment_count": 7.0, "worker_count": 1.0},
        ]
    )
    assert "county" in school["geography_type"].to_list()
    assert (
        school.filter(pl.col("geography_type") == "county")
        .sort(["geography_id", "student_type"])
        .select(["geography_id", "student_type", "enrollment_count", "student_count"])
        .to_dicts()
        == [
            {
                "geography_id": "Central",
                "student_type": "School",
                "enrollment_count": 75.0,
                "student_count": 1.0,
            },
            {
                "geography_id": "Central",
                "student_type": "University",
                "enrollment_count": 0.0,
                "student_count": 0.0,
            },
            {
                "geography_id": "East",
                "student_type": "School",
                "enrollment_count": 0.0,
                "student_count": 0.0,
            },
            {
                "geography_id": "East",
                "student_type": "University",
                "enrollment_count": 100.0,
                "student_count": 1.0,
            },
            {
                "geography_id": "West",
                "student_type": "School",
                "enrollment_count": 0.0,
                "student_count": 0.0,
            },
            {
                "geography_id": "West",
                "student_type": "University",
                "enrollment_count": 0.0,
                "student_count": 0.0,
            },
        ]
    )
    assert (
        workplace.filter(pl.col("geography_type") == "all_geographies")
        .select(["geography_id", "employment_count", "worker_count"])
        .to_dicts()
        == [
            {
                "geography_id": "all_geographies",
                "employment_count": 24.0,
                "worker_count": 1.0,
            }
        ]
    )
    assert (
        school.filter(pl.col("geography_type") == "all_geographies")
        .sort("student_type")
        .select(["geography_id", "student_type", "enrollment_count", "student_count"])
        .to_dicts()
        == [
            {
                "geography_id": "all_geographies",
                "student_type": "School",
                "enrollment_count": 75.0,
                "student_count": 1.0,
            },
            {
                "geography_id": "all_geographies",
                "student_type": "University",
                "enrollment_count": 100.0,
                "student_count": 1.0,
            },
        ]
    )


def test_geography_summaries_include_all_geographies_rollups(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: true",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {
                "person_id": [101, 102],
                "home_zone_id": [10, 20],
                "is_worker": [True, True],
                "is_external_worker": [True, False],
                "external_workplace_zone_id": [30, None],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "person_id": [101, 102],
                "tour_category": ["non_mandatory", "non_mandatory"],
                "is_external_tour": [True, False],
                "destination": [30, 20],
                "finalweight": [1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    external_workplace = external_workplace_loc(prepared, config)
    nonmandatory_mix = int_vs_ext_non_mand_tour_freq(prepared, config)
    external_tour_locations = ext_non_mand_tour_loc(prepared, config)

    assert (
        external_workplace.filter(pl.col("geography_type") == "all_geographies")
        .select(["geography_id", "external_worker_count", "all_worker_count"])
        .to_dicts()
        == [
            {
                "geography_id": "all_geographies",
                "external_worker_count": 1.0,
                "all_worker_count": 2.0,
            }
        ]
    )
    assert (
        nonmandatory_mix.filter(pl.col("geography_type") == "all_geographies")
        .select(
            [
                "geography_id",
                "internal_nonmandatory_tour_count",
                "external_nonmandatory_tour_count",
            ]
        )
        .to_dicts()
        == [
            {
                "geography_id": "all_geographies",
                "internal_nonmandatory_tour_count": 1.0,
                "external_nonmandatory_tour_count": 1.0,
            }
        ]
    )
    assert (
        external_tour_locations.filter(pl.col("geography_type") == "all_geographies")
        .select(["geography_id", "external_nonmandatory_tour_count"])
        .to_dicts()
        == [{"geography_id": "all_geographies", "external_nonmandatory_tour_count": 1.0}]
    )


def test_geography_summaries_include_configured_aggregation_levels(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        West: [10]",
            "        East: [20, 30]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {
                "person_id": [101, 102],
                "home_zone_id": [10, 20],
                "home_geo__county": ["West", "East"],
                "is_worker": [True, True],
                "is_external_worker": [True, False],
                "external_workplace_zone_id": [30, None],
                "work_geo__county": ["East", None],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "person_id": [101, 102],
                "tour_category": ["non_mandatory", "non_mandatory"],
                "is_external_tour": [True, False],
                "destination": [30, 20],
                "finalweight": [1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    worker_summary = internal_vs_external(prepared, config)
    workplace_summary = external_workplace_loc(prepared, config)
    tour_summary = int_vs_ext_non_mand_tour_freq(prepared, config)

    assert "county" in worker_summary["geography_type"].to_list()
    assert (
        workplace_summary.filter(pl.col("geography_type") == "county")
        .select(["geography_id", "external_worker_count"])
        .to_dicts()
        == [{"geography_id": "East", "external_worker_count": 1.0}]
    )
    assert (
        tour_summary.filter(pl.col("geography_type") == "county")
        .sort("geography_id")
        .select(
            [
                "geography_id",
                "internal_nonmandatory_tour_count",
                "external_nonmandatory_tour_count",
            ]
        )
        .to_dicts()
        == [
            {
                "geography_id": "East",
                "internal_nonmandatory_tour_count": 1.0,
                "external_nonmandatory_tour_count": 0.0,
            },
            {
                "geography_id": "West",
                "internal_nonmandatory_tour_count": 0.0,
                "external_nonmandatory_tour_count": 1.0,
            },
        ]
    )


def test_student_type_config_supports_custom_person_segmentation(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "student_types:",
            "  - label: Elementary/Middle School",
            "    land_use_columns: [ENROLLGRADEKto8]",
            "    person:",
            "      school_segment: [1]",
            "  - label: High School",
            "    land_use_columns: [ENROLLGRADE9to12]",
            "    person:",
            "      SCHG: [2]",
            "  - label: University",
            "    land_use_columns: [COLLEGEENROLL]",
            "    person:",
            "      is_university: true",
        ],
    )

    run = _raw_run_with_student_enrollment_inputs()
    run = ProcessorRunData(
        label=run.label,
        run_dir=run.run_dir,
        skim_file=run.skim_file,
        hh=run.hh,
        per=run.per.with_columns(pl.Series("SCHG", [None, 2, None])),
        tours=run.tours,
        trips=run.trips,
        joint_participants=run.joint_participants,
        land_use=run.land_use,
        skim_matrix=run.skim_matrix,
        skim_zone_map=run.skim_zone_map,
    )

    prepared = processor_prepare_data(run, config)

    assert prepared.per["student_type"].to_list() == [
        None,
        "Elementary/Middle School",
        "University",
    ]


def test_student_type_config_supports_local_config_enrollment_columns(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "student_types:",
            "  - label: School",
            "    land_use_columns: [Elementary_Enrolment, Secondary_Enrolment]",
            "  - label: University",
            "    land_use_columns: [PostSecFTE]",
        ],
    )

    run = _raw_run_with_student_enrollment_inputs()
    run = ProcessorRunData(
        label=run.label,
        run_dir=run.run_dir,
        skim_file=run.skim_file,
        hh=run.hh,
        per=run.per,
        tours=run.tours,
        trips=run.trips,
        joint_participants=run.joint_participants,
        land_use=pl.DataFrame(
            {
                "zone_id": [10, 20, 30],
                "TAZ": [10, 20, 30],
                "EMP_Total": [7, 8, 9],
                "Elementary_Enrolment": [0, 50, 0],
                "Secondary_Enrolment": [0, 25, 0],
                "PostSecFTE": [0, 0, 100],
            }
        ),
        skim_matrix=run.skim_matrix,
        skim_zone_map=run.skim_zone_map,
    )

    prepared = processor_prepare_data(run, config)
    school = school_loc_vs_land_use_enrollment(prepared, config)
    workplace = workplace_vs_land_use_employment(prepared, config)

    base_land_use = prepared.land_use.filter(pl.col("student_type").is_null())

    assert base_land_use["MAZ"].to_list() == [10, 20, 30]
    assert base_land_use["employment_count"].to_list() == [7.0, 8.0, 9.0]
    assert set(school["student_type"].unique().to_list()) == {"School", "University"}
    assert workplace.is_empty() is False


def test_student_type_config_rejects_custom_multi_school_segmentation_without_person_rules(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="person is required"):
        _write_config(
            tmp_path,
            extra_lines=[
                "student_types:",
                "  - label: Elementary/Middle School",
                "    land_use_columns: [ENROLLGRADEKto8]",
                "  - label: High School",
                "    land_use_columns: [ENROLLGRADE9to12]",
                "  - label: University",
                "    land_use_columns: [COLLEGEENROLL]",
            ],
        )


def test_config_accepts_day_and_vehicle_file_and_fallback_mappings(
    tmp_path: Path,
) -> None:
    fallback_day = (tmp_path / "shared_day.csv").resolve()
    fallback_day.write_text("day_id,person_id,household_id\n1,10,1\n", encoding="utf-8")
    fallback_vehicles = (tmp_path / "shared_vehicles.csv").resolve()
    fallback_vehicles.write_text(
        "vehicle_id,household_id,vehicle_type\n1,1,Car_5_Gas\n",
        encoding="utf-8",
    )

    config = _write_config(
        tmp_path,
        extra_lines=[
            "files:",
            "  day: day",
            "  vehicles: final_vehicles",
            "fallback_files:",
            f"  day: {fallback_day}",
            f"  vehicles: {fallback_vehicles}",
            "runs:",
            '  - dir: "run_a"',
            '    label: "Run A"',
            "    file_map:",
            "      day: survey_day",
            "      vehicles: vehicles_snapshot",
        ],
    )

    assert config.files["day"] == "day"
    assert config.files["vehicles"] == "final_vehicles"
    assert config.runs[0]["file_map"]["day"] == "survey_day"
    assert config.runs[0]["file_map"]["vehicles"] == "vehicles_snapshot"
    assert config.fallback_files["day"].endswith("shared_day.csv")
    assert config.fallback_files["vehicles"].endswith("shared_vehicles.csv")


def test_processor_read_run_loads_day_and_vehicle_tables(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "files:",
            "  households: final_households",
            "  persons: final_persons",
            "  day: day",
            "  tours: final_tours",
            "  trips: final_trips",
            "  vehicles: final_vehicles",
            "  joint_tour_participants: final_joint_tour_participants",
            "  land_use: final_land_use",
        ],
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_households.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"day_id": [100], "person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "day.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10]}).write_csv(
        run_dir / "final_trips.csv"
    )
    pl.DataFrame(
        {"vehicle_id": [200], "household_id": [1], "vehicle_type": ["Car_8_Gas"]}
    ).write_csv(run_dir / "final_vehicles.csv")
    pl.DataFrame({"tour_id": [], "person_id": []}).write_csv(
        run_dir / "final_joint_tour_participants.csv"
    )
    pl.DataFrame({"zone_id": [1]}).write_csv(run_dir / "final_land_use.csv")

    loaded = processor_read_run(run_dir, config, label="Run A")

    assert loaded.day["day_id"].to_list() == [100]
    assert loaded.vehicles["vehicle_id"].to_list() == [200]
    assert processor_table_availability(loaded)["day"] == "available"
    assert processor_table_availability(loaded)["vehicles"] == "available"


def test_processor_read_run_uses_fallback_day_and_vehicles_when_primary_missing(
    tmp_path: Path,
) -> None:
    shared_day = (tmp_path / "shared_day.csv").resolve()
    shared_day.write_text("day_id,person_id,household_id\n1,10,1\n", encoding="utf-8")
    shared_vehicles = (tmp_path / "shared_vehicles.csv").resolve()
    shared_vehicles.write_text(
        "vehicle_id,household_id,vehicle_type\n1,1,Car_5_Gas\n",
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        extra_lines=[
            "fallback_files:",
            f"  day: {shared_day}",
            f"  vehicles: {shared_vehicles}",
        ],
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pl.DataFrame({"household_id": [1]}).write_csv(run_dir / "final_households.csv")
    pl.DataFrame({"person_id": [10], "household_id": [1]}).write_csv(
        run_dir / "final_persons.csv"
    )
    pl.DataFrame({"tour_id": [100], "household_id": [1], "person_id": [10]}).write_csv(
        run_dir / "final_tours.csv"
    )
    pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10]}).write_csv(
        run_dir / "final_trips.csv"
    )
    pl.DataFrame({"tour_id": [], "person_id": []}).write_csv(
        run_dir / "final_joint_tour_participants.csv"
    )

    loaded = processor_read_run(run_dir, config, label="Run A")

    assert loaded.day["day_id"].to_list() == [1]
    assert loaded.vehicles["vehicle_id"].to_list() == [1]
    assert processor_table_availability(loaded)["day"] == "available"
    assert processor_table_availability(loaded)["vehicles"] == "available"


def test_processor_prepare_enriches_day_and_vehicles(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    raw.day = pl.DataFrame(
        {
            "day_id": [100, 101],
            "person_id": [101, 999],
            "household_id": [1, 999],
            "travel_date": ["2023-06-02", "2023-06-03"],
            "day_num": [1, 2],
            "travel_dow": [5, 6],
            "daily_activity_pattern": ["M", "N"],
            "day_weight": [2.5, None],
        }
    )
    raw.vehicles = pl.DataFrame(
        {
            "vehicle_id": [1001, 1002],
            "household_id": [1, 999],
            "vehicle_num": [1, 1],
            "vehicle_type": ["SUV_12_Hybrid", "Car_5_Gas"],
        }
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.day["person_type"].to_list() == ["1", None]
    assert prepared.day["finalweight"].to_list() == [2.5, 1.0]
    assert prepared.vehicles["body_type"].to_list() == ["SUV", "Car"]
    assert prepared.vehicles["fuel_type"].to_list() == ["Hybrid", "Gas"]
    assert prepared.vehicles["vehicle_age"].to_list() == [12, 5]
    assert prepared.vehicles["finalweight"].to_list() == [1.0, 1.0]


def test_vehicle_long_term_summaries_use_prepared_vehicle_table_and_unweighted_reset(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    raw.vehicles = pl.DataFrame(
        {
            "vehicle_id": [1, 2],
            "household_id": [1, 1],
            "vehicle_num": [1, 2],
            "vehicle_type": ["SUV_12_Hybrid", "Car_5_Gas"],
        }
    )
    prepared = processor_prepare_data(raw, config)
    prepared.vehicles = prepared.vehicles.with_columns(pl.Series("finalweight", [2.0, 3.0]))

    age = vehicle_char_age(prepared, config)
    fuel = vehicle_char_fuel(prepared, config)
    body = vehicle_char_body(prepared, config)
    unweighted = strip_weights(prepared)
    unweighted_age = vehicle_char_age(unweighted, config)

    assert age["vehicle_count"].to_list() == [3.0, 2.0]
    assert fuel["vehicle_count"].to_list() == [3.0, 2.0]
    assert body["vehicle_count"].to_list() == [3.0, 2.0]
    assert unweighted_age["vehicle_count"].to_list() == [1.0, 1.0]
