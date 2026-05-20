from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.state import DashboardState
from processor.segmentation import build_analysis_units_for_run
from processor.models import RunData
from processor.summarize.cache import create_summary_run
from runtime.config import Config


def _write_config(tmp_path: Path, extra_lines: list[str]) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Segmentation Test"',
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Segmentation Dashboard"',
                "runs: []",
                *extra_lines,
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


def _prepared_run() -> RunData:
    return RunData(
        label="Run A",
        run_dir="C:/runs/run-a",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2],
                "market": ["Urban", "Rural"],
                "home_zone_id": [10, 20],
                "finalweight": [1.0, 1.0],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 201],
                "household_id": [1, 2],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 2],
                "finalweight": [1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001, 6001],
                "tour_id": [1001, 2001],
                "person_id": [101, 201],
                "household_id": [1, 2],
                "finalweight": [1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [1001, 2001], "person_id": [101, 201]}
        ),
        land_use=pl.DataFrame(
            {
                "MAZ": [10, 20],
                "TAZ": [100, 200],
                "county": ["North", "South"],
            }
        ),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_config_parses_csv_segmentation_source(tmp_path: Path) -> None:
    csv_path = tmp_path / "county_lookup.csv"
    csv_path.write_text("HH_ID,county\n1,North\n2,South\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard_visibility: segments_only",
            "  source:",
            "    type: csv_lookup",
                f"    file: {csv_path.resolve().as_posix()}",
            "    join:",
            "      source_table: hh",
            "      source_key_column: household_id",
            "      csv_key_column: HH_ID",
            "    segment_value_column: county",
            "  segments:",
            "    - id: north",
            "      label: North",
            "      values: [North]",
        ],
    )

    assert config.segmentation.enabled is True
    assert config.segmentation.dashboard_visibility == "segments_only"
    assert config.segmentation.source is not None
    assert config.segmentation.source.type == "csv_lookup"


def test_build_analysis_units_supports_csv_lookup_segmentation(tmp_path: Path) -> None:
    csv_path = tmp_path / "county_lookup.csv"
    csv_path.write_text("HH_ID,county\n1,North\n2,South\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  source:",
            "    type: csv_lookup",
                f"    file: {csv_path.resolve().as_posix()}",
            "    join:",
            "      source_table: hh",
            "      source_key_column: household_id",
            "      csv_key_column: HH_ID",
            "    segment_value_column: county",
            "  segments:",
            "    - id: north",
            "      label: North",
            "      values: [North]",
            "    - id: south",
            "      label: South",
            "      values: [South]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    assert [unit.segment_id for unit in units] == ["full", "north", "south"]
    assert units[1].prepared_run.hh["household_id"].to_list() == [1]
    assert units[2].prepared_run.hh["household_id"].to_list() == [2]


def test_dashboard_state_renders_all_segment_series_for_segmented_runs() -> None:
    full_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [1]})}},
    )
    north_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [2]})}},
        segment_id="north",
        segment_label="North",
        is_full_segment=False,
    )

    state = DashboardState(
        summary_runs=[full_run, north_run],
        weighting_modes=["weighted"],
        default_segmentation_visibility="full_and_segments",
    )

    assert state.has_segmented_summary_series is True
    assert state.run_labels == ["Run A (Full)", "Run A (North)"]
    summary_set = state.get_summary_table_set("totals", weighting_key="weighted")
    assert summary_set is not None
    assert [label for label, _ in summary_set] == ["Run A (Full)", "Run A (North)"]


def test_build_analysis_units_supports_land_use_anchor(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  source:",
            "    type: prepared_column",
            "    source_table: land_use",
            "    column: county",
            "  segments:",
            "    - id: north",
            "      label: North",
            "      values: [North]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    assert [unit.segment_id for unit in units] == ["full", "north"]
    assert units[1].prepared_run.hh["household_id"].to_list() == [1]
