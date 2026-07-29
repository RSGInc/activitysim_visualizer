from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import openmatrix as omx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.config import Config


def _write_omx(path: Path, *, matrix_name: str = "SOV_TIME") -> None:
    handle = omx.open_file(str(path), "w")
    handle[matrix_name] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()


def _write_network_los(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "skim_time_periods:",
                "  periods:",
                "    - 0",
                "    - 6",
                "    - 12",
                "  labels:",
                "    - EA",
                "    - AM",
            ]
        ),
        encoding="utf-8",
    )


def _write_config(tmp_path: Path, lines: list[str]) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def test_new_config_layout_normalizes_to_existing_runtime_fields(tmp_path: Path) -> None:
    skim_path = tmp_path / "override.omx"
    network_los_path = tmp_path / "network_los.yaml"
    skimjoin_config_path = tmp_path / "skimjoin.yaml"
    _write_omx(skim_path)
    _write_network_los(network_los_path)
    skimjoin_config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                f"  network_los_file: {network_los_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: depart",
                "      outbound_tour_source_column: start",
                "      inbound_tour_source_column: first_inbound_trip_depart",
                "    values_from_network_los: true",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_config(
        tmp_path,
        [
            'name: "Phase 1 New Layout"',
            "root: cache_root",
            "log_level: warning",
            "pipeline:",
            "  steps:",
            "    - prepare",
            "    - skimjoin",
            "    - segment",
            "    - summarize",
            "    - dashboard",
            "  dashboard_mode: export",
            "  overwrite: true",
            "dashboard:",
            '  title: "Refactor Dashboard"',
            "  live:",
            "    pages:",
            "      - overview",
            "      - trip_mode",
            "  enable_maz_geographies: true",
            "  export:",
            "    output_path: exports/dashboard.html",
            "display:",
            "  labels:",
            "    mode:",
            "      mapping:",
            "        WALK: Walk",
            "  run_colors:",
            '    - "#111111"',
            "summarize:",
            "  weighting_modes:",
            "    - weighted",
            "  pnr_tour_modes:",
            "    - PNR_PREMIUM",
            "  geography:",
            "    enabled: true",
            "    landuse_col: COUNTY",
            "    mapping:",
            "      1: Urban",
            "segment:",
            "  dashboard:",
            "    segmentation_type: county",
            "    visibility: segments_only",
            "  definitions:",
            "    county:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: county",
            "      segments:",
            "        - id: urban",
            "          label: Urban",
            "          values: [1]",
            "prepare:",
            "  distance_skim:",
            f"    file: {skim_path.name}",
            "    matrix: SOV_TIME__EA",
            "skimjoin:",
            "  defaults:",
            f"    config_path: {skimjoin_config_path.name}",
            f"    skim_files: [{skim_path.name}]",
            f"    network_los_file: {network_los_path.name}",
            "runs: []",
        ],
    )

    assert config.summary_root == str((tmp_path / "cache_root").resolve())
    assert config.log_level == "WARNING"
    assert config.pipeline.steps == (
        "prepare",
        "skimjoin",
        "segment",
        "summarize",
        "dashboard",
    )
    assert config.pipeline.dashboard_mode == "export"
    assert config.pipeline.overwrite is True
    assert config.dashboard_title == "Refactor Dashboard"
    assert [entry.page_id for entry in config.dashboard_pages or []] == [
        "overview",
        "trip_mode",
    ]
    assert config.enable_maz_geographies is True
    assert config.export_html.enabled is True
    assert config.export_html.output_path == str(
        (tmp_path / "cache_root" / "exports" / "dashboard.html").resolve()
    )
    assert config.run_colors == ["#111111"]
    assert config.weighting_modes == ["weighted"]
    assert config.pnr_tour_modes == ["PNR_PREMIUM"]
    assert config.geography_enabled is True
    assert config.geography_landuse_col == "COUNTY"
    assert config.segmentation.enabled is True
    assert config.segmentation.dashboard.segmentation_type == "county"
    assert config.segmentation.dashboard.visibility == "segments_only"
    assert config.skim_file == str(skim_path.name)
    assert config.skim_matrix == "SOV_TIME__EA"
    assert config.skimjoin_step_enabled() is True
    assert config.skimjoin.config_path == str(skimjoin_config_path.resolve())
    assert config.skimjoin.resolved_skim_files == (str(skim_path.resolve()),)
    assert config.skimjoin.resolved_network_los_file == str(network_los_path.resolve())


def test_legacy_distance_skim_locations_still_normalize_to_prepare_distance_skim(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skim_path = tmp_path / "legacy.omx"
    network_los_path = tmp_path / "network_los.yaml"
    skimjoin_config_path = tmp_path / "skimjoin.yaml"
    _write_omx(skim_path, matrix_name="SOV_DIST__MD")
    _write_network_los(network_los_path)
    skimjoin_config_path.write_text(
        "\n".join(
            [
                "project:",
                f"  skim_files: [{skim_path.name}]",
                f"  network_los_file: {network_los_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: depart",
                "      outbound_tour_source_column: start",
                "      inbound_tour_source_column: first_inbound_trip_depart",
                "    values_from_network_los: true",
                "modes:",
                "  SOV:",
                "    distance:",
                "      matrix: SOV_DIST__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_config(
        tmp_path,
        [
            'name: "Legacy Distance Skim"',
            "skimjoin:",
            "  defaults:",
            f"    config_path: {skimjoin_config_path.name}",
            f"    skim_files: [{skim_path.name}]",
            f"    network_los_file: {network_los_path.name}",
            "  distance_skim:",
            f"    file: {skim_path.name}",
            "    matrix: SOV_DIST__MD",
            "runs: []",
        ],
    )

    assert config.skim_file == str(skim_path.name)
    assert config.skim_matrix == "SOV_DIST__MD"
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert "skimjoin.distance_skim" in combined_output
    assert "prepare.distance_skim" in combined_output


def test_new_keys_take_precedence_over_legacy_equivalents_and_warn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path,
        [
            'name: "Precedence Test"',
            "root: new_root",
            "log_level: error",
            "processor:",
            "  root: old_root",
            "  summaries:",
            "    weighting_modes: [unweighted]",
            "summaries:",
            "  root: older_root",
            "  weighting_modes: [weighted, unweighted]",
            "visualizer:",
            '  dashboard_title: "Legacy Dashboard"',
            "  log_level: info",
            "  run_colors: ['#aaaaaa']",
            "dashboard:",
            '  title: "New Dashboard"',
            "display:",
            "  run_colors:",
            '    - "#222222"',
            "summarize:",
            "  weighting_modes: [weighted]",
            "runs: []",
        ],
    )

    assert config.summary_root == str((tmp_path / "new_root").resolve())
    assert config.log_level == "ERROR"
    assert config.dashboard_title == "New Dashboard"
    assert config.weighting_modes == ["weighted"]
    assert config.run_colors == ["#222222"]
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert "processor.root" in combined_output
    assert "summaries.root" in combined_output
    assert "visualizer.log_level" in combined_output
    assert "visualizer.dashboard_title" in combined_output
    assert "processor.summaries.weighting_modes" in combined_output
    assert "visualizer.run_colors" in combined_output
    assert "Deprecated config keys were detected. Prefer the canonical schema:" in combined_output


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [prepare, prepare]",
                "runs: []",
            ],
            "duplicate step",
        ),
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [prepare, publish]",
                "runs: []",
            ],
            "unsupported step",
        ),
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [skimjoin, summarize]",
                "runs: []",
            ],
            "without 'prepare'",
        ),
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [segment, dashboard]",
                "runs: []",
            ],
            "without 'summarize'",
        ),
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [dashboard, summarize]",
                "runs: []",
            ],
            "place 'dashboard' last",
        ),
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [summarize]",
                "  dashboard_mode: deploy",
                "runs: []",
            ],
            "dashboard_mode",
        ),
        (
            [
                'name: "Invalid Pipeline"',
                "pipeline:",
                "  steps: [summarize]",
                "  overwrite: maybe",
                "runs: []",
            ],
            "pipeline.overwrite",
        ),
    ],
)
def test_pipeline_validation_rejects_invalid_configurations(
    tmp_path: Path,
    lines: list[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _write_config(tmp_path, lines)


def test_equivalent_old_and_new_configs_produce_matching_runtime_values_and_digests(
    tmp_path: Path,
) -> None:
    shared_root = str((tmp_path / "shared_cache").resolve()).replace("\\", "/")
    old_config = _write_config(
        tmp_path / "old",
        [
            'name: "Equivalent Config"',
            "summaries:",
            f"  root: {shared_root}",
            "  weighting_modes: [weighted]",
            "visualizer:",
            '  dashboard_title: "Equivalent Dashboard"',
            "  log_level: warning",
            "  dashboard_pages:",
            "    - overview",
            "  run_colors:",
            '    - "#333333"',
            "dashboard_labels:",
            "  mode:",
            "    mapping:",
            "      WALK: Walk",
            "runs: []",
        ],
    )
    new_config = _write_config(
        tmp_path / "new",
        [
            'name: "Equivalent Config"',
            f"root: {shared_root}",
            "log_level: warning",
            "dashboard:",
            '  title: "Equivalent Dashboard"',
            "  live:",
            "    pages:",
            "      - overview",
            "display:",
            "  labels:",
            "    mode:",
            "      mapping:",
            "        WALK: Walk",
            "  run_colors:",
            '    - "#333333"',
            "summarize:",
            "  weighting_modes: [weighted]",
            "runs: []",
        ],
    )

    assert old_config.summary_root == new_config.summary_root
    assert old_config.log_level == new_config.log_level
    assert old_config.dashboard_title == new_config.dashboard_title
    assert [entry.page_id for entry in old_config.dashboard_pages or []] == [
        entry.page_id for entry in new_config.dashboard_pages or []
    ]
    assert old_config.run_colors == new_config.run_colors
    assert old_config.weighting_modes == new_config.weighting_modes
    assert old_config.prepare_config_digest == new_config.prepare_config_digest
    assert old_config.summary_config_digest == new_config.summary_config_digest
    assert (
        old_config.presentation_config_digest
        == new_config.presentation_config_digest
    )


def test_dashboard_live_pages_take_precedence_over_dashboard_pages_and_warn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path,
        [
            'name: "Dashboard Live Pages Precedence"',
            "dashboard:",
            "  pages:",
            "    - overview",
            "  live:",
            "    pages:",
            "      - trip_mode",
            "runs: []",
        ],
    )

    assert [entry.page_id for entry in config.dashboard_pages or []] == ["trip_mode"]
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert "dashboard.pages" in combined_output
    assert "dashboard.live.pages" in combined_output


def test_summarize_grouping_flags_take_precedence_over_top_level_and_warn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path,
        [
            'name: "Summarize Grouping Precedence"',
            "group_joint_tour_purposes: false",
            "group_atwork_tour_purposes: false",
            "group_school_tour_purposes: false",
            "summarize:",
            "  group_joint_tour_purposes: true",
            "  group_atwork_tour_purposes: true",
            "  group_school_tour_purposes: true",
            "runs: []",
        ],
    )

    assert config.group_joint_tour_purposes is True
    assert config.group_atwork_tour_purposes is True
    assert config.group_school_tour_purposes is True
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert "group_joint_tour_purposes" in combined_output
    assert "summarize.group_joint_tour_purposes" in combined_output


def test_summarize_pnr_tour_modes_take_precedence_over_legacy_modes_and_warn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path,
        [
            'name: "PNR Mode Precedence"',
            "modes:",
            "  pnr_tour_modes: [PNR_LOCAL]",
            "summarize:",
            "  pnr_tour_modes: [PNR_PREMIUM]",
            "runs: []",
        ],
    )

    assert config.pnr_tour_modes == ["PNR_PREMIUM"]
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert "modes.pnr_tour_modes" in combined_output
    assert "summarize.pnr_tour_modes" in combined_output
