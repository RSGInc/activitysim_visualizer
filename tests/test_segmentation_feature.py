from __future__ import annotations

from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.state import DashboardState
from processor.models import RunData
from processor.segmentation import build_analysis_units_for_run
from processor.summarize.cache import (
    create_summary_run,
    load_summary_run_bundle,
    write_summary_run_bundle,
)
from runtime.config import Config


def _write_config(tmp_path: Path, extra_lines: list[str]) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Segmentation Test"',
                "processor:",
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
                "vot_bin": ["L", "H"],
                "home_zone_id": [10, 20],
                "finalweight": [1.0, 1.0],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 201, 202],
                "household_id": [1, 1, 2, 2],
                "person_group": ["adult", "child", "adult", "child"],
                "finalweight": [1.0, 1.0, 1.0, 1.0],
            }
        ),
        day=pl.DataFrame(
            {
                "day_id": [10001, 10002, 20001, 20002],
                "person_id": [101, 102, 201, 202],
                "household_id": [1, 1, 2, 2],
                "day_segment": ["target", "other", "other", "other"],
                "finalweight": [1.0, 1.0, 1.0, 1.0],
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
        vehicles=pl.DataFrame(
            {
                "vehicle_id": [11, 12, 21],
                "household_id": [1, 1, 2],
                "fuel_type": ["gas", "ev", "gas"],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(
            {
                "tour_id": [1001, 1001, 2001, 2001],
                "person_id": [101, 102, 201, 202],
                "participant_role": ["owner", "guest", "owner", "other"],
            }
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


def test_config_parses_multiple_segmentation_definitions(tmp_path: Path) -> None:
    csv_path = tmp_path / "county_lookup.csv"
    csv_path.write_text("HH_ID,county\n1,North\n2,South\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: county",
            "    visibility: segments_only",
            "  definitions:",
            "    county:",
            "      source:",
            "        type: csv_lookup",
            f"        file: {csv_path.resolve().as_posix()}",
            "        join:",
            "          source_table: hh",
            "          source_key_column: household_id",
            "          csv_key_column: HH_ID",
            "        segment_value_column: county",
            "      segments:",
            "        - id: north",
            "          label: North",
            "          values: [North]",
            "    vot:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: vot_bin",
            "      segments:",
            "        - id: low",
            "          label: Low VOT",
            "          values: [L]",
        ],
    )

    assert config.segmentation.enabled is True
    assert config.segmentation.dashboard.segmentation_type == "county"
    assert config.segmentation.dashboard.visibility == "segments_only"
    assert config.segmentation.definition_names() == ("county", "vot")
    assert config.segmentation.definition_by_name("county") is not None


def test_config_accepts_canonical_and_legacy_segmentation_source_tables(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  definitions:",
            "    households:",
            "      source:",
            "        source_table: households",
            "        column: market",
            "      segments:",
            "        - id: urban",
            "          label: Urban",
            "          values: [Urban]",
            "    persons:",
            "      source:",
            "        source_table: persons",
            "        column: person_group",
            "      segments:",
            "        - id: adult",
            "          label: Adult",
            "          values: [adult]",
            "    vehicles:",
            "      source:",
            "        source_table: vehicles",
            "        column: fuel_type",
            "      segments:",
            "        - id: ev",
            "          label: EV",
            "          values: [ev]",
            "    day:",
            "      source:",
            "        source_table: day",
            "        column: day_segment",
            "      segments:",
            "        - id: target",
            "          label: Target",
            "          values: [target]",
            "    joint:",
            "      source:",
            "        source_table: joint_tour_participants",
            "        column: participant_role",
            "      segments:",
            "        - id: guest",
            "          label: Guest",
            "          values: [guest]",
            "    old_hh:",
            "      source:",
            "        source_table: hh",
            "        column: market",
            "      segments:",
            "        - id: rural",
            "          label: Rural",
            "          values: [Rural]",
            "    old_per:",
            "      source:",
            "        source_table: per",
            "        column: person_group",
            "      segments:",
            "        - id: child",
            "          label: Child",
            "          values: [child]",
            "    old_joint:",
            "      source:",
            "        source_table: joint_participants",
            "        column: participant_role",
            "      segments:",
            "        - id: other",
            "          label: Other",
            "          values: [other]",
        ],
    )

    assert {
        definition.name: definition.source.source_table
        for definition in config.segmentation.definitions
        if hasattr(definition.source, "source_table")
    } == {
        "households": "hh",
        "persons": "per",
        "vehicles": "vehicles",
        "day": "day",
        "joint": "joint_participants",
        "old_hh": "hh",
        "old_per": "per",
        "old_joint": "joint_participants",
    }


def test_config_requires_dashboard_segmentation_type_to_exist(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dashboard.segmentation_type"):
        _write_config(
            tmp_path,
            extra_lines=[
                "segmentation:",
                "  enabled: true",
                "  dashboard:",
                "    segmentation_type: county",
                "  definitions:",
                "    vot:",
                "      source:",
                "        type: prepared_column",
                "        source_table: hh",
                "        column: vot_bin",
                "      segments:",
                "        - id: low",
                "          label: Low VOT",
                "          values: [L]",
            ],
        )


def test_summary_digest_changes_for_definition_but_not_dashboard_selection(
    tmp_path: Path,
) -> None:
    base_lines = [
        "segmentation:",
        "  enabled: true",
        "  dashboard:",
        "    segmentation_type: county",
        "    visibility: full_and_segments",
        "  definitions:",
        "    county:",
        "      source:",
        "        type: prepared_column",
        "        source_table: hh",
        "        column: market",
        "      segments:",
        "        - id: urban",
        "          label: Urban",
        "          values: [Urban]",
        "    vot:",
        "      source:",
        "        type: prepared_column",
        "        source_table: hh",
        "        column: vot_bin",
        "      segments:",
        "        - id: low",
        "          label: Low VOT",
        "          values: [L]",
    ]
    config_a = _write_config(tmp_path / "a", extra_lines=base_lines)
    config_b = _write_config(
        tmp_path / "b",
        extra_lines=[
            *base_lines[:4],
            "    segmentation_type: vot",
            "    visibility: segments_only",
            *base_lines[5:],
        ],
    )
    config_c = _write_config(
        tmp_path / "c",
        extra_lines=[
            *base_lines,
            "        - id: rural",
            "          label: Rural",
            "          values: [Rural]",
        ],
    )

    assert config_a.summary_config_digest == config_b.summary_config_digest
    assert (
        config_a.presentation_config_digest
        != config_b.presentation_config_digest
    )
    assert config_a.summary_config_digest != config_c.summary_config_digest


def test_build_analysis_units_supports_multiple_segmentation_types(tmp_path: Path) -> None:
    csv_path = tmp_path / "county_lookup.csv"
    csv_path.write_text("HH_ID,county\n1,North\n2,South\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: county",
            "  definitions:",
            "    county:",
            "      source:",
            "        type: csv_lookup",
            f"        file: {csv_path.resolve().as_posix()}",
            "        join:",
            "          source_table: hh",
            "          source_key_column: household_id",
            "          csv_key_column: HH_ID",
            "        segment_value_column: county",
            "      segments:",
            "        - id: north",
            "          label: North",
            "          values: [North]",
            "        - id: south",
            "          label: South",
            "          values: [South]",
            "    vot:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: vot_bin",
            "      segments:",
            "        - id: low",
            "          label: Low VOT",
            "          values: [L]",
            "        - id: high",
            "          label: High VOT",
            "          values: [H]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    assert [
        (unit.segmentation_type, unit.segment_id) for unit in units
    ] == [
        ("full", "full"),
        ("county", "north"),
        ("county", "south"),
        ("vot", "low"),
        ("vot", "high"),
    ]
    assert units[1].prepared_run.hh["household_id"].to_list() == [1]
    assert units[2].prepared_run.hh["household_id"].to_list() == [2]
    assert units[3].prepared_run.hh["household_id"].to_list() == [1]
    assert units[4].prepared_run.hh["household_id"].to_list() == [2]


def test_build_analysis_units_supports_land_use_anchor_in_multi_type_config(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: county",
            "  definitions:",
            "    county:",
            "      source:",
            "        type: prepared_column",
            "        source_table: land_use",
            "        column: county",
            "      segments:",
            "        - id: north",
            "          label: North",
            "          values: [North]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    assert [(unit.segmentation_type, unit.segment_id) for unit in units] == [
        ("full", "full"),
        ("county", "north"),
    ]
    assert units[1].prepared_run.hh["household_id"].to_list() == [1]


def test_build_analysis_units_supports_vehicle_anchor(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  definitions:",
            "    fuel:",
            "      source:",
            "        type: prepared_column",
            "        source_table: vehicles",
            "        column: fuel_type",
            "      segments:",
            "        - id: ev",
            "          label: EV",
            "          values: [ev]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    ev = units[1].prepared_run
    assert units[1].segment_metadata.source_table == "vehicles"
    assert units[1].segment_metadata.source_key_column == "vehicle_id"
    assert ev.vehicles["vehicle_id"].to_list() == [12]
    assert ev.hh["household_id"].to_list() == [1]
    assert ev.per["person_id"].to_list() == [101, 102]
    assert ev.day["day_id"].to_list() == [10001, 10002]
    assert ev.tours["tour_id"].to_list() == [1001]
    assert ev.trips["trip_id"].to_list() == [5001]
    assert ev.joint_participants["person_id"].to_list() == [101, 102]


def test_build_analysis_units_supports_day_anchor(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  definitions:",
            "    day_segment:",
            "      source:",
            "        type: prepared_column",
            "        source_table: day",
            "        column: day_segment",
            "      segments:",
            "        - id: target",
            "          label: Target",
            "          values: [target]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    target = units[1].prepared_run
    assert units[1].segment_metadata.source_table == "day"
    assert units[1].segment_metadata.source_key_column == "day_id"
    assert target.day["day_id"].to_list() == [10001]
    assert target.hh["household_id"].to_list() == [1]
    assert target.per["person_id"].to_list() == [101]
    assert target.vehicles["vehicle_id"].to_list() == [11, 12]
    assert target.tours["tour_id"].to_list() == [1001]
    assert target.trips["trip_id"].to_list() == [5001]
    assert target.joint_participants["person_id"].to_list() == [101, 102]


def test_build_analysis_units_supports_joint_participants_anchor(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  definitions:",
            "    joint_role:",
            "      source:",
            "        type: prepared_column",
            "        source_table: joint_tour_participants",
            "        column: participant_role",
            "      segments:",
            "        - id: guest",
            "          label: Guest",
            "          values: [guest]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    guest = units[1].prepared_run
    assert units[1].segment_metadata.source_table == "joint_participants"
    assert units[1].segment_metadata.source_key_column is None
    assert guest.joint_participants["person_id"].to_list() == [102]
    assert guest.tours["tour_id"].to_list() == [1001]
    assert guest.trips["trip_id"].to_list() == [5001]
    assert guest.per["person_id"].to_list() == [101, 102]
    assert guest.hh["household_id"].to_list() == [1]
    assert guest.day["day_id"].to_list() == [10001, 10002]
    assert guest.vehicles["vehicle_id"].to_list() == [11, 12]


def test_csv_lookup_segmentation_supports_vehicle_anchor(tmp_path: Path) -> None:
    csv_path = tmp_path / "vehicle_lookup.csv"
    csv_path.write_text("vehicle_id,vehicle_segment\n12,clean\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  definitions:",
            "    vehicle_segment:",
            "      source:",
            "        type: csv_lookup",
            f"        file: {csv_path.resolve().as_posix()}",
            "        join:",
            "          source_table: vehicles",
            "          source_key_column: vehicle_id",
            "          csv_key_column: vehicle_id",
            "        segment_value_column: vehicle_segment",
            "      segments:",
            "        - id: clean",
            "          label: Clean",
            "          values: [clean]",
        ],
    )

    units = build_analysis_units_for_run(
        run_key="run-a",
        run_name="Run A",
        prepared_run=_prepared_run(),
        config=config,
    )

    assert config.segmentation.definitions[0].source.join_source_table == "vehicles"
    assert units[1].segment_metadata.source_key_column == "vehicle_id"
    assert units[1].prepared_run.vehicles["vehicle_id"].to_list() == [12]


def test_new_segmentation_anchors_require_relationship_keys(tmp_path: Path) -> None:
    cases = [
        (
            "vehicles",
            "fuel_type",
            pl.DataFrame({"vehicle_id": [12], "fuel_type": ["ev"]}),
            "vehicles",
            "vehicles segmentation requires a household_id column",
        ),
        (
            "day",
            "day_segment",
            pl.DataFrame({"day_id": [10001], "day_segment": ["target"]}),
            "day",
            "day segmentation requires a person_id or household_id column",
        ),
        (
            "joint_tour_participants",
            "participant_role",
            pl.DataFrame({"tour_id": [1001], "participant_role": ["guest"]}),
            "joint_participants",
            "joint_tour_participants segmentation requires tour_id and person_id columns",
        ),
    ]
    for config_table, column, broken_table, run_attr, message in cases:
        config = _write_config(
            tmp_path / config_table,
            extra_lines=[
                "segmentation:",
                "  enabled: true",
                "  definitions:",
                "    broken:",
                "      source:",
                "        type: prepared_column",
                f"        source_table: {config_table}",
                f"        column: {column}",
                "      segments:",
                "        - id: broken",
                "          label: Broken",
                "          values: [ev, target, guest]",
            ],
        )
        prepared_run = _prepared_run()
        setattr(prepared_run, run_attr, broken_table)

        with pytest.raises(ValueError, match=message):
            build_analysis_units_for_run(
                run_key="run-a",
                run_name="Run A",
                prepared_run=prepared_run,
                config=config,
            )


def test_csv_lookup_segmentation_rejects_one_to_many_membership(tmp_path: Path) -> None:
    csv_path = tmp_path / "county_lookup.csv"
    csv_path.write_text("HH_ID,county\n1,North\n1,South\n", encoding="utf-8")

    with pytest.raises(ValueError, match="multiple segment values"):
        _write_config(
            tmp_path,
            extra_lines=[
                "segmentation:",
                "  enabled: true",
                "  dashboard:",
                "    segmentation_type: county",
                "  definitions:",
                "    county:",
                "      source:",
                "        type: csv_lookup",
                f"        file: {csv_path.resolve().as_posix()}",
                "        join:",
                "          source_table: hh",
                "          source_key_column: household_id",
                "          csv_key_column: HH_ID",
                "        segment_value_column: county",
                "      segments:",
                "        - id: north",
                "          label: North",
                "          values: [North]",
            ],
        )


def test_dashboard_state_filters_to_configured_segmentation_type_and_shows_all_visible_series(
) -> None:
    full_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [1]})}},
    )
    north_county = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [2]})}},
        segmentation_type="county",
        segment_id="north",
        segment_label="North",
        is_full_segment=False,
    )
    south_county = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [3]})}},
        segmentation_type="county",
        segment_id="south",
        segment_label="South",
        is_full_segment=False,
    )
    low_vot = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [4]})}},
        segmentation_type="vot",
        segment_id="low",
        segment_label="Low VOT",
        is_full_segment=False,
    )

    state = DashboardState(
        summary_runs=[full_run, north_county, south_county, low_vot],
        weighting_modes=["weighted"],
        dashboard_segmentation_type="county",
        default_segmentation_visibility="full_and_segments",
    )

    assert state.run_labels == ["Run A (Full)", "Run A (North)", "Run A (South)"]
    summary_set = state.get_summary_table_set("totals", weighting_key="weighted")
    assert summary_set is not None
    assert [label for label, _ in summary_set] == [
        "Run A (Full)",
        "Run A (North)",
        "Run A (South)",
    ]


def test_dashboard_state_segments_only_hides_full_for_selected_type() -> None:
    full_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [1]})}},
    )
    north_county = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [2]})}},
        segmentation_type="county",
        segment_id="north",
        segment_label="North",
        is_full_segment=False,
    )

    state = DashboardState(
        summary_runs=[full_run, north_county],
        weighting_modes=["weighted"],
        dashboard_segmentation_type="county",
        default_segmentation_visibility="segments_only",
    )

    assert state.run_labels == ["Run A (North)"]


def test_dashboard_state_segments_only_keeps_full_runs_when_no_segmented_series_exist(
) -> None:
    full_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [1]})}},
    )

    state = DashboardState(
        summary_runs=[full_run],
        weighting_modes=["weighted"],
        dashboard_segmentation_type="county",
        default_segmentation_visibility="segments_only",
    )

    assert state.has_segmented_summary_series is False
    assert state.run_labels == ["Run A"]
    summary_set = state.get_summary_table_set("totals", weighting_key="weighted")
    assert summary_set is not None
    assert [label for label, _ in summary_set] == ["Run A"]


def test_summary_cache_round_trip_persists_multiple_segmentation_types(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: county",
            "  definitions:",
            "    county:",
            "      source:",
            "        type: prepared_column",
            "        source_table: land_use",
            "        column: county",
            "      segments:",
            "        - id: north",
            "          label: North",
            "          values: [North]",
            "    vot:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: vot_bin",
            "      segments:",
            "        - id: low",
            "          label: Low VOT",
            "          values: [L]",
        ],
    )
    runs = [
        create_summary_run(
            label="Run A",
            run_key="run-a",
            summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [1]})}},
        ),
        create_summary_run(
            label="Run A",
            run_key="run-a",
            summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [2]})}},
            segmentation_type="county",
            segment_id="north",
            segment_label="North",
            is_full_segment=False,
        ),
        create_summary_run(
            label="Run A",
            run_key="run-a",
            summaries_by_mode={"weighted": {"totals": pl.DataFrame({"x": [3]})}},
            segmentation_type="vot",
            segment_id="low",
            segment_label="Low VOT",
            is_full_segment=False,
        ),
    ]

    cache_dir = write_summary_run_bundle(runs, config, output_root=tmp_path / "cache")
    loaded = load_summary_run_bundle(
        cache_dir,
        config,
        expected_modes=["weighted"],
    )

    assert [
        (run.segmentation_type, run.segment_id) for run in loaded
    ] == [
        ("full", "full"),
        ("county", "north"),
        ("vot", "low"),
    ]
