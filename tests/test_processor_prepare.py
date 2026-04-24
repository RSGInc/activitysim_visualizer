from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.models import RunData as ProcessorRunData
from processor.prepare import (
    prepare_data as processor_prepare_data,
    read_run as processor_read_run,
    resolve_skim_path as processor_resolve_skim_path,
    resolve_source_column as processor_resolve_source_column,
    table_availability as processor_table_availability,
    table_unavailable_reasons as processor_table_unavailable_reasons,
)
from runtime.config import Config


def _write_config(tmp_path: Path) -> Config:
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
            ]
        ),
        encoding="utf-8",
    )
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


def test_processor_prepare_module_exposes_canonical_prepare_helpers() -> None:
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
    assert prepared.land_use["EMPLOYMENT"].to_list() == [7, 8]


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
