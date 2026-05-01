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
from processor.summarize.summaries.long_term import (
    school_loc_vs_land_use_enrollment,
    workplace_vs_land_use_employment,
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
