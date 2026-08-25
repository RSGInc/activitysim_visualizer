from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
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
from processor.summarize.contracts import missing_summary_inputs
from processor.summarize.summaries import tour, trip
from processor.summarize.summaries import tour_profiles, trip_distributions
from processor.summarize.summaries.long_term_geography import (
    external_workplace_loc,
    internal_vs_external,
    park_and_ride_location_residual_histogram,
    park_and_ride_location_residuals,
    school_shadow_pricing_residual_histogram,
    school_shadow_pricing_residuals,
    school_loc_vs_land_use_enrollment,
    wfh,
    workplace_shadow_pricing_residual_histogram,
    workplace_shadow_pricing_residuals,
    workplace_vs_land_use_employment,
)
from processor.summarize.summaries.long_term_distance import (
    schl_tlfd,
    univ_tlfd,
    work_tlfd,
)
from processor.summarize.summaries.long_term_person import (
    license_holding_status,
    telecommute,
)
from processor.summarize.summaries.long_term_vehicle import (
    vehicle_char_age,
    vehicle_char_body,
    vehicle_char_fuel,
)
from processor.summarize.summaries.summary_helpers import (
    _configured_geography_dimensions,
)
from processor.summarize.summaries.tour_geography import (
    avg_mand_tour_distance,
    avg_non_mand_tour_distance,
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
        "root: summary_cache",
        "dashboard:",
        '  title: "Processor Prepare Test"',
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
        land_use=pl.DataFrame(
            {"zone_id": [10, 20], "TAZ": [10, 20], "EMPLOY_TOT": [7, 8]}
        ),
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
                "stop_frequency": [
                    "2out_2in",
                    "2out_0in",
                    "0out_1in",
                    "0out_0in",
                    "0out_0in",
                ],
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
            {
                "zone_id": [10, 20, 30, 40],
                "TAZ": [10, 20, 30, 40],
                "EMPLOY_TOT": [7, 8, 9, 10],
            }
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


def test_processor_prepare_data_normalizes_toc_raw_statewide_survey(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  category_mappings:",
            "    raw_statewide_survey:",
            "      persons:",
            "        has_license:",
            "          source: can_drive",
            "          output_type: boolean",
            "          preserve_unmapped: false",
            "          mapping:",
            "            1: true",
            "            3: false",
            "            995: false",
            "      tours:",
            "        tour_mode:",
            "          mapping:",
            "            2: WALK",
            "            7: BIKE",
            "            8: EBIKE",
            "            13: SOV",
            "        tour_purpose:",
            "          mapping:",
            "            1: loop",
            "            2: work",
            "            3: othmaint",
            "            6: escort",
            "            8: eatout",
            "            14: loop",
            "        tour_category:",
            "          mapping:",
            "            1: mandatory",
            "            2: non_mandatory",
            "            3: atwork",
            "            4: joint",
            "      trips:",
            "        trip_mode:",
            "          source: linked_trip_mode",
            "          mapping:",
            "            2: WALK",
            "            7: BIKE",
            "            13: SOV",
            "            995: MISSING",
            "        trip_purpose:",
            "          source: d_purpose_category",
            "          mapping:",
            "            1: home",
            "            6: escort",
            "            14: home",
            "            995: null",
            "  vot_bins:",
            "    source_column: income_segment",
            "    output_column: vot_bin",
            "    fallback_value: M",
            "    mappings:",
            "      raw_statewide_survey:",
            "        2: L",
        ],
    )
    category_mappings = config.prepare_category_mappings.mapping_for_run(
        "Raw Statewide Survey"
    )
    assert category_mappings is not None
    assert category_mappings["tours"]["tour_mode"].mapping["13"] == "SOV"
    assert (
        config.prepare_signature_payload()["prepare"]["category_mappings"]
        ["raw-statewide-survey"]["persons"]["has_license"]["output_type"]
        == "boolean"
    )
    raw = _raw_run()
    raw.label = "Raw Statewide Survey"
    raw.hh = pl.DataFrame(
        {
            "household_id": [1],
            "num_people": [6],
            "num_vehicles": [5],
            "num_workers": [1],
            "num_adults": [3],
            "income_broad": [2],
            "home_county": ["Lane"],
            "home_mpo": ["Central Lane"],
        }
    )
    raw.per = pl.DataFrame(
        {
            "person_id": [101, 102, 103],
            "household_id": [1, 1, 1],
            "person_type": [1, 4, 7],
            "can_drive": [1, 3, 995],
            "age": [45, 35, 10],
        }
    )
    raw.tours = pl.DataFrame(
        {
            "tour_id": [1001, 1002, 1003, 1004],
            "person_id": [101, 101, 102, 103],
            "household_id": [1, 1, 1, 1],
            "tour_purpose": [2, 6, 3, 14],
            "tour_category": [1, 2, 3, 4],
            "tour_mode": [13, 7, 2, 8],
            "tour_start_hour": [3, 2, 19, 8],
            "tour_start_minute": [0, 30, 56, 15],
            "tour_end_hour": [4, 3, 20, 9],
            "tour_end_minute": [0, 0, 30, 0],
            "duration_minutes": [60, 30, 34, 90],
            "distance_miles": [1.5, 2.5, 3.5, 4.5],
            "joint_num_participants": [1, 1, 1, 3],
            "stop_frequency": ["0out_0in"] * 4,
            "school_esc_outbound": [None, "ride_share", None, None],
            "school_esc_inbound": [None] * 4,
            "out_escorted_tour_ids": [None, "1004", None, None],
            "inb_escorted_tour_ids": [None] * 4,
        }
    )
    raw.trips = pl.DataFrame(
        {
            "trip_id": [5001, 5002, 5003, 5004],
            "tour_id": [1001, 1002, 1003, 1004],
            "person_id": [101, 101, 102, 103],
            "household_id": [1, 1, 1, 1],
            "linked_trip_mode": [13, 7, 2, 995],
            "d_purpose_category": [1, 14, 6, 995],
            "depart_hour": [3, 2, 19, 8],
            "depart_minute": [0, 30, 56, 15],
            "distance_miles": [1.25, 2.25, 3.25, 4.25],
            "outbound": [True, True, True, True],
            "trip_num": [1, 1, 1, 1],
        }
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.hh["HHSIZE"].to_list() == [5]
    assert prepared.hh["HHVEH"].to_list() == [4]
    assert prepared.hh["LICENSEDDRIVERS"].to_list() == [1]
    assert prepared.per["has_license"].to_list() == [True, False, False]

    tours = prepared.tours.sort("tour_id")
    assert tours["tour_mode"].to_list() == ["SOV", "BIKE", "WALK", "EBIKE"]
    assert tours["tour_purpose"].to_list() == [
        "work",
        "escort",
        "othmaint",
        "loop",
    ]
    assert tours["tour_category"].to_list() == [
        "mandatory",
        "non_mandatory",
        "atwork",
        "joint",
    ]
    assert tours["start"].to_list() == [1, 48, 34, 11]
    assert tours["end"].to_list() == [3, 1, 36, 13]
    assert tours["tourdur"].to_list() == [2, 1, 2, 3]
    assert tours["SKIMDIST"].to_list() == [1.5, 2.5, 3.5, 4.5]
    assert tours["NUMBER_HH"].to_list() == [1, 1, 1, 3]
    assert tours["vot_bin"].to_list() == ["L", "L", "L", "L"]

    trips = prepared.trips.sort("trip_id")
    assert trips["trip_mode"].to_list() == ["SOV", "BIKE", "WALK", "MISSING"]
    assert trips["trip_purpose"].to_list() == ["home", "home", "escort", None]
    assert trips["depart"].to_list() == [1, 48, 34, 11]
    assert trips["od_dist"].to_list() == [1.25, 2.25, 3.25, 4.25]
    assert trips["prepared_non_motorized_distance"].to_list() == [
        1.25,
        2.25,
        3.25,
        4.25,
    ]
    assert trips["vot_bin"].to_list() == ["L", "L", "L", "L"]
    assert set(license_holding_status(prepared, config)["license_holding_status"]) == {
        "has_license",
        "no_license",
    }

    raw.label = "Regional: Filtered & Attributed"
    raw.tours = raw.tours.with_columns(
        pl.Series("tour_mode", ["SOV", "BIKE", "WALK", "EBIKE"]),
        pl.Series(
            "tour_category",
            ["mandatory", "non_mandatory", "atwork", "joint"],
        ),
        pl.Series(
            "primary_purpose", ["work", "escort", "othmaint", "eatout"]
        ),
    )
    labeled = processor_prepare_data(raw, config).tours.sort("tour_id")

    assert labeled["tour_mode"].to_list() == ["SOV", "BIKE", "WALK", "EBIKE"]
    assert labeled["tour_purpose"].to_list() == [
        "work",
        "escort",
        "othmaint",
        "eatout",
    ]
    assert labeled["tour_category"].to_list() == [
        "mandatory",
        "non_mandatory",
        "atwork",
        "joint",
    ]


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


def test_processor_prepare_data_carries_and_maps_pnr_zone_to_tours_and_trips(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "columns:",
            "  pnr_zone_id: [pnr_stop_zone]",
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
                "primary_purpose": [1],
                "tour_type": ["eatout"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
                "start": [8],
                "end": [10],
                "duration": [2],
                "origin": [10],
                "destination": [20],
                "pnr_stop_zone": [30],
                "stop_frequency": ["1out_0in"],
            }
        ),
        trips=raw.trips,
        joint_participants=raw.joint_participants,
        land_use=pl.DataFrame(
            {
                "zone_id": [10, 20, 30],
                "TAZ": [1, 2, 3],
                "EMPLOY_TOT": [7, 8, 9],
            }
        ),
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours["pnr_zone_id"].to_list() == [30]
    assert prepared.tours["pnr_taz"].to_list() == [3]
    assert prepared.trips["pnr_zone_id"].to_list() == [30]
    assert prepared.trips["pnr_taz"].to_list() == [3]
    assert prepared.prepare_diagnostics["tours.pnr_taz"]["unresolved"] == 0
    assert prepared.prepare_diagnostics["trips.pnr_taz"]["unresolved"] == 0


def test_processor_prepare_data_uses_person_worker_flags_for_autosuff_when_configured(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  auto_sufficiency_basis: workers",
            "columns:",
            "  is_worker: [worker_flag]",
        ],
    )

    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2],
                "home_zone_id": [10, 20],
                "auto_ownership": [1, 1],
                "hhsize": [2, 2],
                "num_workers": [99, 99],
                "num_adults": [2, 2],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 201, 202],
                "household_id": [1, 1, 2, 2],
                "ptype": [1, 2, 1, 2],
                "home_zone_id": [10, 10, 20, 20],
                "worker_flag": [True, True, True, False],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 2],
                "primary_purpose": ["work", "work"],
                "tour_type": ["work", "work"],
                "tour_mode": ["DRIVE", "DRIVE"],
                "tour_category": ["mandatory", "mandatory"],
                "start": [8, 8],
                "end": [10, 10],
                "duration": [2, 2],
                "origin": [10, 20],
                "destination": [20, 10],
                "stop_frequency": ["0out_0in", "0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001, 6001],
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 2],
                "trip_mode": ["DRIVEALONE", "DRIVEALONE"],
                "purpose": ["work", "work"],
                "depart": [8, 8],
                "outbound": [True, True],
                "trip_num": [1, 1],
                "origin": [10, 20],
                "destination": [20, 10],
            }
        ),
        joint_participants=raw.joint_participants,
        land_use=raw.land_use,
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours.sort("tour_id")["AUTOSUFF"].to_list() == [1, 2]
    assert prepared.trips.sort("trip_id")["AUTOSUFF"].to_list() == [1, 2]
    summary = tour_profiles.tour_mode(prepared, config).sort(
        ["tour_mode", "tour_purpose"]
    )
    assert summary.filter(pl.col("tour_purpose") == "work").to_dicts() == [
        {
            "tour_mode": "DRIVE",
            "tour_purpose": "work",
            "tour_count_zero_auto": 0.0,
            "tour_count_auto_deficient": 1.0,
            "tour_count_auto_sufficient": 1.0,
            "tour_count_all_households": 2.0,
        }
    ]


def test_processor_prepare_data_uses_person_adult_flags_for_autosuff_when_configured(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  auto_sufficiency_basis: adults",
            "columns:",
            "  adult: [adult_flag]",
        ],
    )

    raw = _raw_run()
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2],
                "home_zone_id": [10, 20],
                "auto_ownership": [1, 1],
                "hhsize": [2, 2],
                "num_workers": [1, 1],
                "num_adults": [99, 99],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 201, 202],
                "household_id": [1, 1, 2, 2],
                "ptype": [1, 2, 1, 2],
                "home_zone_id": [10, 10, 20, 20],
                "adult_flag": [True, True, True, False],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 2],
                "primary_purpose": ["work", "work"],
                "tour_type": ["work", "work"],
                "tour_mode": ["DRIVE", "DRIVE"],
                "tour_category": ["mandatory", "mandatory"],
                "start": [8, 8],
                "end": [10, 10],
                "duration": [2, 2],
                "origin": [10, 20],
                "destination": [20, 10],
                "stop_frequency": ["0out_0in", "0out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001, 6001],
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 2],
                "trip_mode": ["DRIVEALONE", "DRIVEALONE"],
                "purpose": ["work", "work"],
                "depart": [8, 8],
                "outbound": [True, True],
                "trip_num": [1, 1],
                "origin": [10, 20],
                "destination": [20, 10],
            }
        ),
        joint_participants=raw.joint_participants,
        land_use=raw.land_use,
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours.sort("tour_id")["AUTOSUFF"].to_list() == [1, 2]
    assert prepared.trips.sort("trip_id")["AUTOSUFF"].to_list() == [1, 2]


def test_processor_prepare_data_leaves_autosuff_absent_when_basis_inputs_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  auto_sufficiency_basis: adults",
        ],
    )

    prepared = processor_prepare_data(_raw_run(), config)

    assert "AUTOSUFF" not in prepared.tours.columns
    assert "AUTOSUFF" not in prepared.trips.columns
    assert prepared.prepare_diagnostics["tours.AUTOSUFF"]["missing_columns"] == (
        "_autosuff_adults",
    )
    assert prepared.prepare_diagnostics["trips.AUTOSUFF"]["missing_columns"] == (
        "_autosuff_adults",
    )


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


def test_processor_prepare_data_uses_joint_participant_count_with_tour_fallback(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    tours = pl.concat([raw.tours] * 3).with_columns(
        pl.Series("tour_id", [1001, 1002, 1003]),
        pl.Series("tour_category", ["joint", "joint", "joint"]),
        pl.Series(
            "number_of_participants",
            [4, 3, None],
            dtype=pl.Int64,
        ),
        pl.Series("SKIMDIST", [5.0, 10.0, 15.0]),
    )
    trips = pl.concat([raw.trips] * 3).with_columns(
        pl.Series("trip_id", [5001, 5002, 5003]),
        pl.Series("tour_id", [1001, 1002, 1003]),
    )
    raw = ProcessorRunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=pl.concat(
            [
                raw.per,
                raw.per.with_columns(
                    pl.lit(102, dtype=raw.per.schema["person_id"]).alias("person_id"),
                    pl.lit(2, dtype=raw.per.schema["ptype"]).alias("ptype"),
                ),
            ]
        ),
        tours=tours,
        trips=trips,
        joint_participants=pl.DataFrame(
            {
                "tour_id": [1001, 1001],
                "person_id": [101, 102],
            }
        ),
        land_use=raw.land_use,
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.tours.sort("tour_id")["NUMBER_HH"].to_list() == [2, 3, 1]
    assert prepared.trips.sort("tour_id")["num_participants"].to_list() == [2, 3, 1]

    distance = tour_profiles.tour_distance(prepared, config).filter(
        pl.col("tour_purpose") != "all_tour_purposes"
    )
    assert distance.select("distance_bin", "tour_count").to_dicts() == [
        {"distance_bin": "5", "tour_count": 2.0},
        {"distance_bin": "10", "tour_count": 3.0},
        {"distance_bin": "15", "tour_count": 1.0},
    ]


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


def test_processor_prepare_data_adds_non_motorized_distance_from_csv(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "maz_maz_walk.csv"
    pl.DataFrame(
        {
            "OMAZ": [100, 200],
            "DMAZ": [200, 100],
            "DISTWALK": [0.5, 0.75],
        }
    ).write_csv(csv_path)
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "  maz_col: [MAZ, zone_id]",
            "  taz_col: [TAZ]",
            "prepare:",
            "  non_motorized_distance_skim:",
            "    file: maz_maz_walk.csv",
            "    matrix: null",
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
        trips=pl.DataFrame(
            {
                "trip_id": [1, 2, 3],
                "tour_id": [1001, 1001, 1001],
                "person_id": [101, 101, 101],
                "household_id": [1, 1, 1],
                "trip_mode": ["WALK", "BIKE", "WALK"],
                "origin": [100, 200, 999],
                "destination": [200, 100, 100],
            }
        ),
        joint_participants=raw.joint_participants,
        land_use=pl.DataFrame(
            {
                "zone_id": [100, 200, 999],
                "TAZ": [1, 2, 3],
                "EMPLOY_TOT": [7, 8, 9],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.trips["prepared_non_motorized_distance"].to_list() == [
        0.5,
        0.75,
        None,
    ]
    diagnostics = prepared.prepare_diagnostics["trips.prepared_non_motorized_distance"]
    assert diagnostics["source_type"] == "csv"
    assert diagnostics["value_column"] == "DISTWALK"
    assert diagnostics["unresolved"] == 1
    assert diagnostics["eligible_non_motorized_unresolved"] == 1


def test_processor_prepare_data_adds_non_motorized_distance_from_omx(
    tmp_path: Path,
) -> None:
    import openmatrix as omx

    omx_path = tmp_path / "walk.omx"
    handle = omx.open_file(str(omx_path), "w")
    handle["WLK_DIST"] = np.array([[0.0, 1.25], [1.5, 0.0]])
    handle.close()
    config = _write_config(
        tmp_path,
        extra_lines=[
            "zones:",
            "  use_maz: true",
            "  maz_col: [MAZ, zone_id]",
            "  taz_col: [TAZ]",
            "prepare:",
            "  non_motorized_distance_skim:",
            "    file: walk.omx",
            "    matrix: WLK_DIST",
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
        trips=pl.DataFrame(
            {
                "trip_id": [1, 2],
                "tour_id": [1001, 1001],
                "person_id": [101, 101],
                "household_id": [1, 1],
                "trip_mode": ["WALK", "BIKE"],
                "origin": [100, 200],
                "destination": [200, 100],
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
        skim_matrix=None,
        skim_zone_map=None,
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.trips["prepared_non_motorized_distance"].to_list() == [
        1.25,
        1.5,
    ]
    diagnostics = prepared.prepare_diagnostics["trips.prepared_non_motorized_distance"]
    assert diagnostics["source_type"] == "omx"
    assert diagnostics["matrix"] == "WLK_DIST"


def test_processor_prepare_data_leaves_non_motorized_distance_absent_without_config(
    tmp_path: Path,
) -> None:
    prepared = processor_prepare_data(_raw_run(), _write_config(tmp_path))

    assert "prepared_non_motorized_distance" not in prepared.trips.columns


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
    assert tour_profiles.tour_distance(prepared, config).is_empty()
    assert trip_distributions.trip_distance(prepared, config).is_empty()
    assert trip_distributions.stop_ood_distance(prepared, config).is_empty()


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


def test_config_normalizes_prepare_aliases_for_hard_coded_prepare_inputs(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  home_zone_id: [hh_home_zone, person_home_zone]",
            "  workplace_zone_id: person_work_zone",
            "  school_zone_id: person_school_zone",
            "  has_license: license_flag",
            "  mandatory_tour_frequency: mtf_src",
            "  is_student: [student_flag, student_src]",
            "  is_university: university_flag",
            "  school_segment: school_segment_src",
            "  schg: schg_src",
            "  pstudent: pstudent_src",
            "  tour_origin: tour_origin_src",
            "  tour_destination: tour_destination_src",
            "  trip_origin: trip_origin_src",
            "  trip_destination: trip_destination_src",
            "  stop_frequency: stop_pattern_src",
            "  trip_outbound: trip_outbound_src",
            "  trip_num: trip_num_src",
            "  day_id: day_identifier",
            "  day_weight: day_weight_src",
            "  vehicle_id: vehicle_identifier",
            "  vehicle_num: vehicle_sequence",
            "  vehicle_type: vehicle_type_src",
        ],
    )

    assert config.col_home_zone_id == ["hh_home_zone", "person_home_zone"]
    assert config.col_workplace_zone_id == ["person_work_zone"]
    assert config.col_school_zone_id == ["person_school_zone"]
    assert config.col_has_license == ["license_flag"]
    assert config.col_mandatory_tour_frequency == ["mtf_src"]
    assert config.col_is_student == ["student_flag", "student_src"]
    assert config.col_is_university == ["university_flag"]
    assert config.col_school_segment == ["school_segment_src"]
    assert config.col_schg == ["schg_src"]
    assert config.col_pstudent == ["pstudent_src"]
    assert config.col_tour_origin == ["tour_origin_src"]
    assert config.col_tour_destination == ["tour_destination_src"]
    assert config.col_trip_origin == ["trip_origin_src"]
    assert config.col_trip_destination == ["trip_destination_src"]
    assert config.col_stop_frequency == ["stop_pattern_src"]
    assert config.col_trip_outbound == ["trip_outbound_src"]
    assert config.col_trip_num == ["trip_num_src"]
    assert config.col_day_id == ["day_identifier"]
    assert config.col_day_weight == ["day_weight_src"]
    assert config.col_vehicle_id == ["vehicle_identifier"]
    assert config.col_vehicle_num == ["vehicle_sequence"]
    assert config.col_vehicle_type == ["vehicle_type_src"]


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
            "tour_category": [
                "non-mandatory",
                "non-mandatory",
                "mandatory",
                "mandatory",
            ],
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
    assert (
        processor_table_availability(loaded)["joint_tour_participants"] == "unavailable"
    )
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
                "root: summary_cache",
                "dashboard:",
                '  title: "Processor Prepare Test"',
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
    assert (
        "definitely_not_trips" in processor_table_unavailable_reasons(loaded)["trips"]
    )


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
                "root: summary_cache",
                "dashboard:",
                '  title: "Invalid File Map Config"',
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
        "definitely_not_trips" in processor_table_unavailable_reasons(loaded)["trips"]
    )


def test_processor_prepare_derives_default_student_types_and_land_use_overlay(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    assert prepared.per["student_type"].to_list() == [None, "School", "University"]
    school_overlay = prepared.land_use.filter(pl.col("student_type") == "School")
    university_overlay = prepared.land_use.filter(
        pl.col("student_type") == "University"
    )
    assert school_overlay["enrollment_count"].to_list() == [0.0, 75.0, 0.0]
    assert university_overlay["enrollment_count"].to_list() == [0.0, 0.0, 100.0]
    assert prepared.land_use.filter(pl.col("student_type").is_null())[
        "EMPLOYMENT"
    ].to_list() == [
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
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          Urban: [10]",
            "          Rural: [20]",
            "      district:",
            "        source_zone_system: maz",
            f"        file: {geography_csv.name}",
            "        zone_id_col: MAZ",
            "        geography_col: district",
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


def test_processor_prepare_copies_native_home_geographies_to_persons(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run()
    raw.hh = raw.hh.with_columns(
        pl.lit("Household County").alias("home_county"),
        pl.lit("Household MPO").alias("home_mpo"),
    )
    raw.per = raw.per.with_columns(pl.lit("Person County").alias("home_county"))

    prepared = processor_prepare_data(raw, config)

    assert prepared.hh["home_county"].to_list() == ["Household County"]
    assert prepared.hh["home_mpo"].to_list() == ["Household MPO"]
    assert prepared.per["home_county"].to_list() == ["Person County"]
    assert prepared.per["home_mpo"].to_list() == ["Household MPO"]


def test_summary_geography_dimensions_include_native_home_geographies(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
        ],
    )
    df = pl.DataFrame(
        {
            "home_zone_id": [10],
            "home_taz": [10],
            "home_county": ["A"],
            "home_mpo": ["B"],
            "home_geo__county": ["West"],
            "work_geo__county": ["West"],
        }
    )

    assert _configured_geography_dimensions(
        df,
        config=config,
        base_type="maz",
        base_col="home_zone_id",
        role_prefix="home",
    ) == [
        ("maz", "home_zone_id"),
        ("home_taz", "home_taz"),
        ("home_county", "home_county"),
        ("home_mpo", "home_mpo"),
        ("county", "home_geo__county"),
    ]
    assert _configured_geography_dimensions(
        df,
        config=config,
        base_type="work_taz",
        base_col="work_taz",
        role_prefix="work",
    ) == [("county", "work_geo__county")]


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
            "summarize:",
            "  geography:",
            "    enabled: false",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          Urban: [10]",
            "          Rural: [20]",
            "      district:",
            "        source_zone_system: maz",
            f"        file: {geography_csv.name}",
            "        zone_id_col: MAZ",
            "        geography_col: district",
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
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          Central: [20]",
            "          East: [30]",
        ],
    )
    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    workplace = workplace_vs_land_use_employment(prepared, config)
    school = school_loc_vs_land_use_enrollment(prepared, config)

    assert "county" in workplace["geography_type"].to_list()
    assert workplace.filter(pl.col("geography_type") == "county").sort(
        "geography_id"
    ).select(["geography_id", "employment_count", "worker_count"]).to_dicts() == [
        {"geography_id": "Central", "employment_count": 8.0, "worker_count": 0.0},
        {"geography_id": "East", "employment_count": 9.0, "worker_count": 0.0},
        {"geography_id": "West", "employment_count": 7.0, "worker_count": 1.0},
    ]
    assert "county" in school["geography_type"].to_list()
    assert school.filter(pl.col("geography_type") == "county").sort(
        ["geography_id", "student_type"]
    ).select(
        ["geography_id", "student_type", "enrollment_count", "student_count"]
    ).to_dicts() == [
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
    assert workplace.filter(pl.col("geography_type") == "all_geographies").select(
        ["geography_id", "employment_count", "worker_count"]
    ).to_dicts() == [
        {
            "geography_id": "all_geographies",
            "employment_count": 24.0,
            "worker_count": 1.0,
        }
    ]
    assert school.filter(pl.col("geography_type") == "all_geographies").sort(
        "student_type"
    ).select(
        ["geography_id", "student_type", "enrollment_count", "student_count"]
    ).to_dicts() == [
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


def test_shadow_pricing_residual_summaries_emit_configured_geography_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          Central: [20]",
            "          East: [30]",
        ],
    )
    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    workplace = workplace_shadow_pricing_residuals(prepared, config)
    school = school_shadow_pricing_residuals(prepared, config)

    assert workplace.filter(pl.col("geography_type") == "county").sort(
        "geography_id"
    ).select(
        [
            "geography_id",
            "target_count",
            "modeled_count",
            "residual_count",
            "absolute_residual_count",
            "percent_error",
        ]
    ).to_dicts() == [
        {
            "geography_id": "Central",
            "target_count": 8.0,
            "modeled_count": 0.0,
            "residual_count": -8.0,
            "absolute_residual_count": 8.0,
            "percent_error": -100.0,
        },
        {
            "geography_id": "East",
            "target_count": 9.0,
            "modeled_count": 0.0,
            "residual_count": -9.0,
            "absolute_residual_count": 9.0,
            "percent_error": -100.0,
        },
        {
            "geography_id": "West",
            "target_count": 7.0,
            "modeled_count": 1.0,
            "residual_count": -6.0,
            "absolute_residual_count": 6.0,
            "percent_error": pytest.approx(-85.71428571428571),
        },
    ]
    assert school.filter(pl.col("geography_type") == "county").sort(
        ["geography_id", "student_type"]
    ).select(
        [
            "geography_id",
            "student_type",
            "target_count",
            "modeled_count",
            "residual_count",
            "absolute_residual_count",
            "percent_error",
        ]
    ).to_dicts() == [
        {
            "geography_id": "Central",
            "student_type": "School",
            "target_count": 75.0,
            "modeled_count": 1.0,
            "residual_count": -74.0,
            "absolute_residual_count": 74.0,
            "percent_error": pytest.approx(-98.66666666666667),
        },
        {
            "geography_id": "Central",
            "student_type": "University",
            "target_count": 0.0,
            "modeled_count": 0.0,
            "residual_count": 0.0,
            "absolute_residual_count": 0.0,
            "percent_error": None,
        },
        {
            "geography_id": "East",
            "student_type": "School",
            "target_count": 0.0,
            "modeled_count": 0.0,
            "residual_count": 0.0,
            "absolute_residual_count": 0.0,
            "percent_error": None,
        },
        {
            "geography_id": "East",
            "student_type": "University",
            "target_count": 100.0,
            "modeled_count": 1.0,
            "residual_count": -99.0,
            "absolute_residual_count": 99.0,
            "percent_error": -99.0,
        },
        {
            "geography_id": "West",
            "student_type": "School",
            "target_count": 0.0,
            "modeled_count": 0.0,
            "residual_count": 0.0,
            "absolute_residual_count": 0.0,
            "percent_error": None,
        },
        {
            "geography_id": "West",
            "student_type": "University",
            "target_count": 0.0,
            "modeled_count": 0.0,
            "residual_count": 0.0,
            "absolute_residual_count": 0.0,
            "percent_error": None,
        },
    ]


def test_workplace_shadow_pricing_residuals_preserve_modeled_only_rows(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          North: [10]",
            "          South: [20]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {
                "person_id": [101],
                "workplace_zone_id": [10],
                "is_worker": [True],
                "finalweight": [2.0],
                "work_geo__county": ["North"],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(
            {
                "MAZ": [20],
                "employment_count": [5.0],
                "land_use_geo__county": ["South"],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = workplace_shadow_pricing_residuals(prepared, config).sort(
        ["geography_type", "geography_id"]
    )

    assert summary.filter(pl.col("geography_type") == "county").select(
        [
            "geography_id",
            "target_count",
            "modeled_count",
            "residual_count",
            "absolute_residual_count",
            "percent_error",
        ]
    ).to_dicts() == [
        {
            "geography_id": "North",
            "target_count": 0.0,
            "modeled_count": 2.0,
            "residual_count": 2.0,
            "absolute_residual_count": 2.0,
            "percent_error": None,
        },
        {
            "geography_id": "South",
            "target_count": 5.0,
            "modeled_count": 0.0,
            "residual_count": -5.0,
            "absolute_residual_count": 5.0,
            "percent_error": -100.0,
        },
    ]


def test_shadow_pricing_histogram_summaries_include_dynamic_count_bins(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          Central: [20]",
            "          East: [30]",
        ],
    )
    prepared = processor_prepare_data(_raw_run_with_student_enrollment_inputs(), config)

    workplace = workplace_shadow_pricing_residual_histogram(prepared, config)
    school = school_shadow_pricing_residual_histogram(prepared, config)

    assert "county" in workplace["geography_type"].to_list()
    assert "county" in school["geography_type"].to_list()
    assert set(school["student_type"].unique().to_list()) == {
        "All",
        "School",
        "University",
    }
    assert set(workplace.columns) == {
        "geography_type",
        "bin_start",
        "bin_end",
        "geography_count",
    }
    assert set(school.columns) == {
        "geography_type",
        "student_type",
        "bin_start",
        "bin_end",
        "geography_count",
    }
    assert (
        workplace.filter(pl.col("geography_type") == "county")["geography_count"].sum()
        == 3.0
    )
    assert (
        school.filter(
            (pl.col("geography_type") == "county")
            & (pl.col("student_type") == "University")
        )["geography_count"].sum()
        == 3.0
    )
    assert (
        school.filter(
            (pl.col("geography_type") == "county") & (pl.col("student_type") == "All")
        )["geography_count"].sum()
        == 6.0
    )
    assert (
        workplace.filter(pl.col("geography_type") == "county")
        .select(["bin_start", "bin_end"])
        .n_unique()
        >= 1
    )


def test_park_and_ride_location_residuals_roll_up_used_lots_only(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  pnr_lot_capacity: [PNR_CAP]",
            "summarize:",
            "  pnr_tour_modes: [PNR_TRANSIT, PNR_LOCAL, PNR_PREMIUM]",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      district:",
            "        source_zone_system: maz",
            "        mapping:",
            "          North: [1, 2]",
            "          South: [3, 4, 5]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_mode": [
                    "PNR_TRANSIT",
                    "PNR_LOCAL",
                    "WALK",
                    "PNR_PREMIUM",
                    "PNR_LOCAL",
                ],
                "pnr_zone_id": [1, 2, None, 3, 4],
                "finalweight": [2.0, 3.0, 99.0, 5.0, 40.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(
            {
                "MAZ": [1, 2, 3, 4, 5],
                "TAZ": [100, 100, 200, 200, 200],
                "PNR_CAP": [10.0, 20.0, 30.0, 40.0, 50.0],
                "land_use_geo__district": ["North", "North", "South", "South", "South"],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = park_and_ride_location_residuals(prepared, config)

    assert summary.filter(pl.col("geography_type") == "maz").sort(
        "geography_id"
    ).select(
        [
            "geography_id",
            "pnr_tour_count",
            "pnr_lot_capacity",
            "residual_count",
            "absolute_residual_count",
            "percent_error",
        ]
    ).to_dicts() == [
        {
            "geography_id": "1",
            "pnr_tour_count": 2.0,
            "pnr_lot_capacity": 10.0,
            "residual_count": -8.0,
            "absolute_residual_count": 8.0,
            "percent_error": -80.0,
        },
        {
            "geography_id": "2",
            "pnr_tour_count": 3.0,
            "pnr_lot_capacity": 20.0,
            "residual_count": -17.0,
            "absolute_residual_count": 17.0,
            "percent_error": -85.0,
        },
        {
            "geography_id": "3",
            "pnr_tour_count": 5.0,
            "pnr_lot_capacity": 30.0,
            "residual_count": -25.0,
            "absolute_residual_count": 25.0,
            "percent_error": pytest.approx(-83.33333333333334),
        },
        {
            "geography_id": "4",
            "pnr_tour_count": 40.0,
            "pnr_lot_capacity": 40.0,
            "residual_count": 0.0,
            "absolute_residual_count": 0.0,
            "percent_error": 0.0,
        },
    ]
    assert summary.filter(pl.col("geography_type") == "district").sort(
        "geography_id"
    ).select(["geography_id", "pnr_tour_count", "pnr_lot_capacity"]).to_dicts() == [
        {"geography_id": "North", "pnr_tour_count": 5.0, "pnr_lot_capacity": 30.0},
        {"geography_id": "South", "pnr_tour_count": 45.0, "pnr_lot_capacity": 70.0},
    ]
    assert summary.filter(pl.col("geography_type") == "taz").sort(
        "geography_id"
    ).select(["geography_id", "pnr_tour_count", "pnr_lot_capacity"]).to_dicts() == [
        {"geography_id": "100", "pnr_tour_count": 5.0, "pnr_lot_capacity": 30.0},
        {"geography_id": "200", "pnr_tour_count": 45.0, "pnr_lot_capacity": 70.0},
    ]
    assert summary.filter(pl.col("geography_type") == "all_geographies").select(
        ["geography_id", "pnr_tour_count", "pnr_lot_capacity"]
    ).to_dicts() == [
        {
            "geography_id": "all_geographies",
            "pnr_tour_count": 50.0,
            "pnr_lot_capacity": 100.0,
        }
    ]


def test_park_and_ride_location_residuals_support_taz_only_inputs(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  pnr_lot_capacity: [PNR_CAP]",
            "summarize:",
            "  pnr_tour_modes: [PNR_TRANSIT]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_mode": ["PNR_TRANSIT", "PNR_TRANSIT", "WALK"],
                "pnr_taz": [10, 20, 20],
                "finalweight": [2.0, 3.0, 99.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(
            {
                "TAZ": [10, 20, 30],
                "PNR_CAP": [12.0, 30.0, 40.0],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )

    assert missing_summary_inputs(park_and_ride_location_residuals, prepared) == {}
    summary = park_and_ride_location_residuals(prepared, config)

    assert summary.filter(pl.col("geography_type") == "taz").sort(
        "geography_id"
    ).select(["geography_id", "pnr_tour_count", "pnr_lot_capacity"]).to_dicts() == [
        {"geography_id": "10", "pnr_tour_count": 2.0, "pnr_lot_capacity": 12.0},
        {"geography_id": "20", "pnr_tour_count": 3.0, "pnr_lot_capacity": 30.0},
    ]
    assert summary.filter(pl.col("geography_type") == "all_geographies").select(
        ["geography_id", "pnr_tour_count", "pnr_lot_capacity"]
    ).to_dicts() == [
        {
            "geography_id": "all_geographies",
            "pnr_tour_count": 5.0,
            "pnr_lot_capacity": 42.0,
        }
    ]


def test_park_and_ride_location_residual_histogram_uses_zero_bin_and_configured_modes(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  pnr_lot_capacity: [PNR_CAP]",
            "summarize:",
            "  pnr_tour_modes: [PNR_TRANSIT, PNR_LOCAL]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_mode": ["PNR_TRANSIT", "PNR_LOCAL", "PNR_PREMIUM"],
                "pnr_zone_id": [1, 2, 3],
                "finalweight": [10.0, 20.0, 30.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(
            {
                "MAZ": [1, 2, 3],
                "PNR_CAP": [10.0, 25.0, 30.0],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )

    histogram = park_and_ride_location_residual_histogram(prepared, config)

    assert set(histogram.columns) == {
        "geography_type",
        "bin_start",
        "bin_end",
        "geography_count",
    }
    zero_bin = histogram.filter(
        (pl.col("geography_type") == "maz")
        & (pl.col("bin_start") == 0.0)
        & (pl.col("bin_end") == 0.0)
    )
    assert zero_bin["geography_count"].to_list() == [1.0]
    assert (
        histogram.filter(pl.col("geography_type") == "maz")["geography_count"].sum()
        == 2.0
    )


def test_geography_summaries_include_all_geographies_rollups(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
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

    assert external_workplace.filter(
        pl.col("geography_type") == "all_geographies"
    ).select(
        ["geography_id", "external_worker_count", "all_worker_count"]
    ).to_dicts() == [
        {
            "geography_id": "all_geographies",
            "external_worker_count": 1.0,
            "all_worker_count": 2.0,
        }
    ]
    assert nonmandatory_mix.filter(
        pl.col("geography_type") == "all_geographies"
    ).select(
        [
            "geography_id",
            "internal_nonmandatory_tour_count",
            "external_nonmandatory_tour_count",
        ]
    ).to_dicts() == [
        {
            "geography_id": "all_geographies",
            "internal_nonmandatory_tour_count": 1.0,
            "external_nonmandatory_tour_count": 1.0,
        }
    ]
    assert external_tour_locations.filter(
        pl.col("geography_type") == "all_geographies"
    ).select(["geography_id", "external_nonmandatory_tour_count"]).to_dicts() == [
        {"geography_id": "all_geographies", "external_nonmandatory_tour_count": 1.0}
    ]


def test_geography_summaries_include_configured_aggregation_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          East: [20, 30]",
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
    assert workplace_summary.filter(pl.col("geography_type") == "county").select(
        ["geography_id", "external_worker_count"]
    ).to_dicts() == [{"geography_id": "East", "external_worker_count": 1.0}]
    assert tour_summary.filter(pl.col("geography_type") == "county").sort(
        "geography_id"
    ).select(
        [
            "geography_id",
            "internal_nonmandatory_tour_count",
            "external_nonmandatory_tour_count",
        ]
    ).to_dicts() == [
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


def test_mandatory_distance_summaries_include_configured_geography_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          East: [20, 30]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103],
                "household_id": [1, 1, 1],
                "home_zone_id": [10, 20, 20],
                "home_geo__county": ["West", "East", "East"],
                "workplace_zone_id": [30, 30, None],
                "school_zone_id": [None, 20, 30],
                "is_worker": [True, True, False],
                "is_student": [False, True, True],
                "person_type": ["1", "7", "3"],
                "distance_to_work": [0.5, 20.0, None],
                "distance_to_school": [None, 5.0, 15.0],
                "finalweight": [1.0, 2.0, 3.0],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    work_distance = work_tlfd(prepared, config)
    school_distance = schl_tlfd(prepared, config)
    university_distance = univ_tlfd(prepared, config)
    mandatory_distance = avg_mand_tour_distance(prepared, config)

    assert work_distance.filter(
        (pl.col("geography_type") == "county")
        & (pl.col("geography_id") == "West")
        & (pl.col("distance_bin") == 0)
    )["person_count"].to_list() == [1.0]
    assert work_distance.filter(
        (pl.col("geography_type") == "county")
        & (pl.col("geography_id") == "East")
        & (pl.col("distance_bin") == 20)
    )["person_count"].to_list() == [2.0]
    assert school_distance.filter(
        (pl.col("geography_type") == "county")
        & (pl.col("geography_id") == "East")
        & (pl.col("distance_bin") == 5)
    )["person_count"].to_list() == [2.0]
    assert university_distance.filter(
        (pl.col("geography_type") == "county")
        & (pl.col("geography_id") == "East")
        & (pl.col("distance_bin") == 15)
    )["person_count"].to_list() == [3.0]
    assert mandatory_distance.filter(
        (pl.col("mandatory_tour_purpose") == "work")
        & (pl.col("geography_type") == "county")
        & (pl.col("geography_id") == "East")
    ).select(["average_tour_distance", "person_count"]).to_dicts() == [
        {"average_tour_distance": 20.0, "person_count": 2.0}
    ]
    assert mandatory_distance.filter(
        pl.col("geography_type") == "all_geographies"
    ).sort("mandatory_tour_purpose").select(
        [
            "mandatory_tour_purpose",
            "geography_id",
            "average_tour_distance",
            "person_count",
        ]
    ).to_dicts() == [
        {
            "mandatory_tour_purpose": "school",
            "geography_id": "all_geographies",
            "average_tour_distance": 5.0,
            "person_count": 2.0,
        },
        {
            "mandatory_tour_purpose": "university",
            "geography_id": "all_geographies",
            "average_tour_distance": 15.0,
            "person_count": 3.0,
        },
        {
            "mandatory_tour_purpose": "work",
            "geography_id": "all_geographies",
            "average_tour_distance": 13.5,
            "person_count": 3.0,
        },
    ]


def test_mandatory_distance_summary_requires_home_geography(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = ProcessorRunData(
        label="Statewide",
        run_dir="C:/runs/statewide",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame({"finalweight": [1.0]}),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    assert missing_summary_inputs(avg_mand_tour_distance, prepared) == {
        "per": "missing required columns: home_zone_id"
    }
    assert avg_mand_tour_distance(prepared, config).is_empty()


def test_telecommute_summary_includes_configured_geography_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          East: [20, 30]",
        ],
    )
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103],
                "household_id": [1, 1, 1],
                "home_zone_id": [10, 20, 20],
                "home_geo__county": ["West", "East", "East"],
                "is_worker": [True, True, True],
                "work_from_home": [False, False, True],
                "telecommute_frequency": ["never", "often", "sometimes"],
                "finalweight": [1.0, 2.0, 3.0],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = telecommute(prepared, config)

    assert summary.filter(pl.col("geography_type") == "county").sort(
        ["geography_id", "telecommute_frequency"]
    ).to_dicts() == [
        {
            "geography_type": "county",
            "geography_id": "East",
            "telecommute_frequency": "often",
            "person_count": 2.0,
        },
        {
            "geography_type": "county",
            "geography_id": "West",
            "telecommute_frequency": "never",
            "person_count": 1.0,
        },
    ]
    assert summary.filter(pl.col("geography_type") == "all_geographies").sort(
        "telecommute_frequency"
    ).to_dicts() == [
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "telecommute_frequency": "never",
            "person_count": 1.0,
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "telecommute_frequency": "often",
            "person_count": 2.0,
        },
    ]


def test_work_from_home_summary_includes_native_home_geographies(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = ProcessorRunData(
        label="Prepared",
        run_dir="C:/runs/prepared",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1, 2], "finalweight": [1.0, 1.0]}),
        per=pl.DataFrame(
            {
                "person_id": [101, 201],
                "household_id": [1, 2],
                "home_zone_id": [10, 20],
                "home_county": ["North", "South"],
                "home_mpo": ["Metro", "Metro"],
                "is_worker": [True, True],
                "work_from_home": [True, False],
                "finalweight": [2.0, 3.0],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = wfh(prepared, config)

    assert summary.filter(pl.col("geography_type") == "home_county").sort(
        "geography_id"
    ).to_dicts() == [
        {
            "geography_type": "home_county",
            "geography_id": "North",
            "worker_count": 2.0,
            "work_from_home_worker_count": 2.0,
        },
        {
            "geography_type": "home_county",
            "geography_id": "South",
            "worker_count": 3.0,
            "work_from_home_worker_count": 0.0,
        },
    ]
    assert summary.filter(pl.col("geography_type") == "home_mpo").to_dicts() == [
        {
            "geography_type": "home_mpo",
            "geography_id": "Metro",
            "worker_count": 5.0,
            "work_from_home_worker_count": 2.0,
        }
    ]


def test_nonmandatory_average_tour_distance_includes_configured_geography_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "summarize:",
            "  geography:",
            "    enabled: true",
            "    aggregations:",
            "      county:",
            "        source_zone_system: taz",
            "        mapping:",
            "          West: [10]",
            "          East: [20, 30]",
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
                "household_id": [1, 1],
                "home_zone_id": [10, 20],
                "home_geo__county": ["West", "East"],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 1002, 1003],
                "person_id": [101, 101, 102],
                "tour_category": [
                    "non_mandatory",
                    "non_mandatory",
                    "non_mandatory",
                ],
                "tour_purpose": ["shopping", "shopping", "eatout"],
                "SKIMDIST": [4.0, 6.0, 10.0],
                "finalweight": [1.0, 3.0, 2.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = avg_non_mand_tour_distance(prepared, config)

    assert summary.filter(pl.col("geography_type") == "county").sort(
        ["nonmandatory_tour_purpose", "geography_id"]
    ).to_dicts() == [
        {
            "nonmandatory_tour_purpose": "eatout",
            "geography_type": "county",
            "geography_id": "East",
            "average_tour_distance": 10.0,
            "tour_count": 2.0,
        },
        {
            "nonmandatory_tour_purpose": "shopping",
            "geography_type": "county",
            "geography_id": "West",
            "average_tour_distance": 5.5,
            "tour_count": 4.0,
        },
    ]
    assert summary.filter(pl.col("geography_type") == "all_geographies").sort(
        "nonmandatory_tour_purpose"
    ).to_dicts() == [
        {
            "nonmandatory_tour_purpose": "eatout",
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "average_tour_distance": 10.0,
            "tour_count": 2.0,
        },
        {
            "nonmandatory_tour_purpose": "shopping",
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "average_tour_distance": 5.5,
            "tour_count": 4.0,
        },
    ]


def test_student_type_config_supports_custom_person_segmentation(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  student_types:",
            "    - label: Elementary/Middle School",
            "      land_use_columns: [ENROLLGRADEKto8]",
            "      person:",
            "        school_segment: [1]",
            "    - label: High School",
            "      land_use_columns: [ENROLLGRADE9to12]",
            "      person:",
            "        SCHG: [2]",
            "    - label: University",
            "      land_use_columns: [COLLEGEENROLL]",
            "      person:",
            "        is_university: true",
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
            "prepare:",
            "  student_types:",
            "    - label: School",
            "      land_use_columns: [Elementary_Enrolment, Secondary_Enrolment]",
            "    - label: University",
            "      land_use_columns: [PostSecFTE]",
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
                "prepare:",
                "  student_types:",
                "    - label: Elementary/Middle School",
                "      land_use_columns: [ENROLLGRADEKto8]",
                "    - label: High School",
                "      land_use_columns: [ENROLLGRADE9to12]",
                "    - label: University",
                "      land_use_columns: [COLLEGEENROLL]",
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
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  day_id: day_identifier",
            "  day_weight: day_weight_src",
            "  vehicle_id: vehicle_identifier",
            "  vehicle_num: vehicle_sequence",
            "  vehicle_type: vehicle_type_src",
        ],
    )
    raw = _raw_run()
    raw.day = pl.DataFrame(
        {
            "day_identifier": [100, 101],
            "person_id": [101, 999],
            "household_id": [1, 999],
            "travel_date": ["2023-06-02", "2023-06-03"],
            "day_num": [1, 2],
            "travel_dow": [5, 6],
            "daily_activity_pattern": ["M", "N"],
            "day_weight_src": [2.5, None],
        }
    )
    raw.vehicles = pl.DataFrame(
        {
            "vehicle_identifier": [1001, 1002],
            "household_id": [1, 999],
            "vehicle_sequence": [1, 1],
            "vehicle_type_src": ["SUV_12_Hybrid", "Car_5_Gas"],
        }
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.day["day_id"].to_list() == [100, 101]
    assert prepared.day["person_type"].to_list() == ["1", None]
    assert prepared.day["finalweight"].to_list() == [2.5, 1.0]
    assert prepared.vehicles["vehicle_id"].to_list() == [1001, 1002]
    assert prepared.vehicles["vehicle_num"].to_list() == [1, 1]
    assert prepared.vehicles["body_type"].to_list() == ["SUV", "Car"]
    assert prepared.vehicles["fuel_type"].to_list() == ["Hybrid", "Gas"]
    assert prepared.vehicles["vehicle_age"].to_list() == [12, 5]
    assert prepared.vehicles["finalweight"].to_list() == [1.0, 1.0]


def test_processor_prepare_uses_canonical_student_aliases_for_student_type_derivation(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "columns:",
            "  is_student: student_flag",
            "  is_university: university_flag",
            "  school_segment: school_segment_src",
            "  schg: schg_src",
            "  pstudent: pstudent_src",
            "prepare:",
            "  student_types:",
            "    - label: School",
            "      land_use_columns: [ENROLLGRADEKto8]",
            "      person:",
            "        is_university: false",
            "        school_segment: [K12]",
            "    - label: University",
            "      land_use_columns: [COLLEGEENROLL]",
            "      person:",
            "        is_university: true",
            "        pstudent: ['2']",
        ],
    )
    raw = _raw_run()
    raw.per = pl.DataFrame(
        {
            "person_id": [101, 102, 103],
            "household_id": [1, 1, 1],
            "ptype": [1, 3, 3],
            "home_zone_id": [10, 10, 10],
            "student_flag": [False, True, True],
            "university_flag": [False, False, True],
            "school_segment_src": ["none", "K12", "College"],
            "schg_src": ["0", "9", "16"],
            "pstudent_src": ["0", "1", "2"],
        }
    )
    raw.land_use = pl.DataFrame(
        {
            "zone_id": [10],
            "TAZ": [10],
            "EMPLOY_TOT": [7],
            "ENROLLGRADEKto8": [11],
            "COLLEGEENROLL": [13],
        }
    )

    prepared = processor_prepare_data(raw, config)

    assert prepared.per["student_type"].to_list() == [None, "School", "University"]


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
    prepared.vehicles = prepared.vehicles.with_columns(
        pl.Series("finalweight", [2.0, 3.0])
    )

    age = vehicle_char_age(prepared, config)
    fuel = vehicle_char_fuel(prepared, config)
    body = vehicle_char_body(prepared, config)
    unweighted = strip_weights(prepared)
    unweighted_age = vehicle_char_age(unweighted, config)

    assert age["vehicle_count"].to_list() == [3.0, 2.0]
    assert fuel["vehicle_count"].to_list() == [3.0, 2.0]
    assert body["vehicle_count"].to_list() == [3.0, 2.0]
    assert unweighted_age["vehicle_count"].to_list() == [1.0, 1.0]
