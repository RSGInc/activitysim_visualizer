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


def test_summary_failure_policy_defaults_to_record_and_accepts_error(
    tmp_path: Path,
) -> None:
    default_config = _write_config(tmp_path / "default", [])
    strict_config = _write_config(
        tmp_path / "strict",
        ["summarize:", "  failure_policy: error"],
    )

    assert default_config.summary_failure_policy == "record"
    assert strict_config.summary_failure_policy == "error"


def test_summary_failure_policy_rejects_unknown_values(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="summarize.failure_policy must be either 'record' or 'error'",
    ):
        _write_config(
            tmp_path,
            ["summarize:", "  failure_policy: keep-going"],
        )


def test_skimjoin_failure_policy_is_normalized_without_enabling_skimjoin(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        ["skimjoin:", "  failure_policy: error"],
    )

    assert config.skimjoin.enabled is False
    assert config.skimjoin.failure_policy == "error"


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


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["summaries: {}"], "summaries: Use root and summarize"),
        (["visualizer: {}"], "visualizer: Use dashboard and display"),
        (["processor: {}"], "processor: Use root, prepare, and summarize"),
        (["dashboard:", "  pages: []"], "dashboard.pages: Use dashboard.live.pages"),
        (["segment:", "  enabled: true"], "segment.enabled: Use pipeline.steps"),
        (
            ["skimjoin:", "  config_path: skimjoin.yaml"],
            "skimjoin.config_path: Use skimjoin.defaults.config_path",
        ),
    ],
)
def test_removed_config_keys_name_the_canonical_replacement(
    tmp_path: Path,
    lines: list[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _write_config(tmp_path, [*lines, "runs: []"])


def test_unknown_top_level_config_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown top-level config keys: 'dashbaord'"):
        _write_config(tmp_path, ["dashbaord: {}", "runs: []"])


def test_dashboard_host_placeholder_is_validated_and_ignored(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        [
            "pipeline:",
            "  steps: [dashboard]",
            "  dashboard_mode: live",
            "dashboard:",
            "  host:",
            "    account: example-account",
            "    app_id: 12345",
            "    title: Example Dashboard",
            "    verify: true",
            "runs: []",
        ],
    )

    assert config.pipeline.dashboard_mode == "live"
    assert not hasattr(config, "host")


def test_dashboard_host_placeholder_rejects_unknown_fields(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="Unknown dashboard.host config keys: 'acount'",
    ):
        _write_config(
            tmp_path,
            [
                "dashboard:",
                "  host:",
                "    acount: typo",
                "runs: []",
            ],
        )


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["pipeline:", "  steps: [prepare, prepare]"], "duplicate step"),
        (["pipeline:", "  steps: [prepare, publish]"], "unsupported step"),
        (["pipeline:", "  steps: [skimjoin, summarize]"], "without 'prepare'"),
        (["pipeline:", "  steps: [segment, dashboard]"], "without 'summarize'"),
        (["pipeline:", "  steps: [dashboard, summarize]"], "place 'dashboard' last"),
        (["pipeline:", "  dashboard_mode: deploy"], "dashboard_mode"),
        (["pipeline:", "  overwrite: maybe"], "pipeline.overwrite"),
    ],
)
def test_pipeline_validation_rejects_invalid_configurations(
    tmp_path: Path,
    lines: list[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _write_config(tmp_path, [*lines, "runs: []"])
