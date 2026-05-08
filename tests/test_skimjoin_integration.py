from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import openmatrix as omx
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime_workflows
from processor.skimjoin.pipeline import apply_skimjoin
from processor.summarize import cache as summary_cache
from runtime.config import Config


def _write_main_config(
    tmp_path: Path,
    *,
    run_dir: Path | None = None,
    skimjoin_enabled: bool = True,
    skimjoin_config_name: str = "skimjoin.yaml",
    summary_ids: list[str] | None = None,
) -> Config:
    config_path = tmp_path / "config.yaml"
    run_dir = run_dir or (tmp_path / "run")
    summary_ids = summary_ids or []
    lines = [
        'name: "Skimjoin Integration Test"',
        "summaries:",
        "  root: summary_cache",
        "visualizer:",
        '  dashboard_title: "Skimjoin Integration Test"',
        "zones:",
        "  use_maz: false",
        "runs:",
        f'  - dir: "{str(run_dir).replace("\\", "/")}"',
        '    label: "Run A"',
        "skimjoin:",
        f"  enabled: {'true' if skimjoin_enabled else 'false'}",
        f"  config_path: {skimjoin_config_name}",
        "  summary_ids:",
    ]
    lines.extend(f"    - {summary_id}" for summary_id in summary_ids)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _write_skimjoin_config(
    tmp_path: Path,
    *,
    skim_file: Path,
    extra_lines: list[str] | None = None,
    include_default_mode: bool = True,
) -> Path:
    config_path = tmp_path / "skimjoin.yaml"
    lines = [
        "project:",
        f"  skim_files:",
        f"    - {skim_file.name}",
        "  trips_table: ignored_trips.parquet",
        "  tours_table: ignored_tours.parquet",
        "activitysim:",
        "  mode_column: trip_mode",
        "  tour_id_column: tour_id",
        "  outbound_column: outbound",
        "defaults:",
        "  origin: OTAZ",
        "  destination: DTAZ",
        "  output_prefix: skim_",
        "zone_mapping:",
        "  lookup_name: taz",
    ]
    if include_default_mode:
        lines.extend(
            [
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME",
            ]
        )
    if extra_lines:
        lines.extend(extra_lines)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def _write_prepare_run_inputs(
    run_dir: Path,
    *,
    include_income_segment: bool = False,
    include_origin_parking_zone: bool = False,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    hh = {
        "household_id": [1],
        "home_zone_id": [101],
        "auto_ownership": [1],
        "hhsize": [2],
        "num_workers": [1],
        "num_adults": [1],
    }
    if include_income_segment:
        hh["income_segment"] = [1]

    trips = {
        "trip_id": [5001],
        "tour_id": [1001],
        "person_id": [101],
        "household_id": [1],
        "trip_mode": ["SOV"],
        "purpose": ["shop"],
        "depart": [8],
        "outbound": [True],
        "trip_num": [1],
        "origin": [101],
        "destination": [102],
    }
    if include_origin_parking_zone:
        trips["origin_parking_zone"] = [101]

    pl.DataFrame(hh).write_parquet(run_dir / "final_households.parquet")
    pl.DataFrame(
        {
            "person_id": [101],
            "household_id": [1],
            "ptype": [1],
            "home_zone_id": [101],
        }
    ).write_parquet(run_dir / "final_persons.parquet")
    pl.DataFrame(
        {
            "tour_id": [1001],
            "person_id": [101],
            "household_id": [1],
            "primary_purpose": ["shop"],
            "tour_type": ["shopping"],
            "tour_mode": ["SOV"],
            "tour_category": ["non-mandatory"],
            "start": [8],
            "end": [10],
            "duration": [2],
            "origin": [101],
            "destination": [102],
        }
    ).write_parquet(run_dir / "final_tours.parquet")
    pl.DataFrame(trips).write_parquet(run_dir / "final_trips.parquet")
    pl.DataFrame(
        {"tour_id": [], "person_id": []},
        schema={"tour_id": pl.Int64, "person_id": pl.Int64},
    ).write_parquet(run_dir / "final_joint_tour_participants.parquet")
    pl.DataFrame({"zone_id": [101, 102], "TAZ": [101, 102]}).write_parquet(
        run_dir / "final_land_use.parquet"
    )


def _write_omx(path: Path, *, matrix_name: str = "SOV_TIME") -> None:
    handle = omx.open_file(str(path), "w")
    handle[matrix_name] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()


def test_config_loads_separate_skimjoin_config_and_digest(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)

    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        summary_ids=["skimjoin_trip_component_means"],
    )

    assert config.skimjoin.enabled is True
    assert config.skimjoin.config_path == str((tmp_path / "skimjoin.yaml").resolve())
    assert config.skimjoin.config_digest
    assert config.skimjoin.summary_ids == ["skimjoin_trip_component_means"]
    assert "skimjoin_trip_component_means" in summary_cache.requested_summary_ids(
        config
    )


def test_config_rejects_non_omx_integrated_skimjoin_inputs(tmp_path: Path) -> None:
    skim_cfg = tmp_path / "skimjoin.yaml"
    skim_cfg.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                "    - skims.h5",
                "  trips_table: ignored_trips.parquet",
                "activitysim:",
                "  mode_column: trip_mode",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="OMX skim inputs only"):
        _write_main_config(tmp_path, skimjoin_enabled=True)


def test_run_prepare_workflow_applies_mapping_aware_skimjoin(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(
        tmp_path,
        run_dir=run_dir,
        skimjoin_enabled=True,
        summary_ids=["skimjoin_trip_component_means"],
    )

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )

    prepared = result.prepared_runs[0][1]
    assert prepared.trips["skim_time"].to_list() == [2.0]
    assert prepared.tours["skim_time"].to_list() == [2.0]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"
    manifest = json.loads((prepared_root / "run-a" / "manifest.json").read_text())
    assert manifest["skimjoin_enabled"] is True

    summaries = summary_cache.build_summaries(
        prepared,
        config,
        summary_ids=["skimjoin_trip_component_means"],
    )
    assert summaries["skimjoin_trip_component_means"].height == 1
    assert summaries["skimjoin_trip_component_means"]["mean_value"].to_list() == [2.0]


def test_apply_skimjoin_skips_missing_prepare_columns_gracefully(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir, include_income_segment=False)
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="SOV_L_TIME")
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "dimensions:",
            "  VOT:",
            "    source_column: income_segment",
            "    values:",
            "      1: L",
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_{VOT}_TIME",
        ],
    )
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.prepared_runs[0][1]
    skipped = prepared.skimjoin_reports["skipped_rule_report"]
    assert "skim_time" not in prepared.trips.columns
    assert prepared.skimjoin_manifest["skimjoin_status"] == "no_outputs"
    assert skipped["reason"].to_list() == ["missing_trip_column:income_segment"]
    assert skipped["rule_name"].to_list() == ["SOV.time"]
