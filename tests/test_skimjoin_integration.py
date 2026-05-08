from __future__ import annotations

import math
import json
from pathlib import Path
import sys

import numpy as np
import openmatrix as omx
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime_workflows
from processor.models import RunData
from processor.prepare.cache import load_prepared_run_cache, write_prepared_run_cache
from processor.skimjoin.annotate.trips import annotate_trips
from processor.skimjoin.inventory import inventory_skim_files
from processor.skimjoin.pipeline import apply_skimjoin
from processor.summarize import cache as summary_cache
from processor.summarize.contracts import empty_summary_frame
from processor.summarize.summaries import skimjoin as skimjoin_summaries
from runtime.config import Config


def _write_main_config(
    tmp_path: Path,
    *,
    run_dir: Path | None = None,
    skimjoin_enabled: bool = True,
    skimjoin_config_name: str = "skimjoin.yaml",
) -> Config:
    config_path = tmp_path / "config.yaml"
    run_dir = run_dir or (tmp_path / "run")
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
    ]
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _write_skimjoin_config(
    tmp_path: Path,
    *,
    skim_file: Path | None = None,
    skim_files: list[Path] | None = None,
    zone_mapping_extra_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
    include_default_mode: bool = True,
) -> Path:
    config_path = tmp_path / "skimjoin.yaml"
    resolved_skim_files = list(skim_files or ([] if skim_file is None else [skim_file]))
    lines = [
        "project:",
        f"  skim_files:",
    ]
    lines.extend(f"    - {path.name}" for path in resolved_skim_files)
    lines.extend(
        [
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
    )
    if zone_mapping_extra_lines:
        lines.extend(zone_mapping_extra_lines)
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
    trip_id_column_name: str = "trip_id",
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
    trips[trip_id_column_name] = [5001]
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


def _write_omx_with_lookup(
    path: Path,
    *,
    matrix_name: str,
    lookup_name: str,
    values: np.ndarray | None = None,
) -> None:
    handle = omx.open_file(str(path), "w")
    handle[matrix_name] = (
        values if values is not None else np.array([[1.0, 2.0], [3.0, 4.0]])
    )
    handle.create_mapping(lookup_name, np.array([101, 102], dtype=np.uint32))
    handle.close()


def test_config_loads_separate_skimjoin_config_and_digest(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)

    config = _write_main_config(tmp_path, skimjoin_enabled=True)

    assert config.skimjoin.enabled is True
    assert config.skimjoin.config_path == str((tmp_path / "skimjoin.yaml").resolve())
    assert config.skimjoin.config_digest
    assert "skimjoin_trip_component_stats" in summary_cache.requested_summary_ids(
        config
    )
    assert "skimjoin_trip_component_ecdf" in summary_cache.requested_summary_ids(
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
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

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
        summary_ids=[
            "skimjoin_trip_component_stats",
            "skimjoin_trip_component_ecdf",
            "skimjoin_tour_component_stats",
            "skimjoin_tour_component_ecdf",
        ],
    )
    trip_stats = summaries["skimjoin_trip_component_stats"]
    trip_ecdf = summaries["skimjoin_trip_component_ecdf"]
    tour_stats = summaries["skimjoin_tour_component_stats"]
    tour_ecdf = summaries["skimjoin_tour_component_ecdf"]

    assert trip_stats.to_dicts() == [
        {
            "trip_mode": "SOV",
            "component": "skim_time",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 2.0,
            "std": 0.0,
            "min": 2.0,
            "max": 2.0,
            "median": 2.0,
            "mode": 2.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        }
    ]
    assert tour_stats.to_dicts() == [
        {
            "tour_mode": "SOV",
            "component": "skim_time",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 2.0,
            "std": 0.0,
            "min": 2.0,
            "max": 2.0,
            "median": 2.0,
            "mode": 2.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        }
    ]
    assert trip_ecdf.height == 101
    assert tour_ecdf.height == 101
    assert trip_ecdf["value"].unique().to_list() == [2.0]
    assert tour_ecdf["value"].unique().to_list() == [2.0]


def test_run_prepare_workflow_supports_file_specific_zone_lookup_overrides(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    auto_path = tmp_path / "auto.omx"
    fare_path = tmp_path / "fares.omx"
    _write_omx(auto_path)
    _write_omx_with_lookup(
        fare_path,
        matrix_name="FARE",
        lookup_name="zone_number",
        values=np.array([[5.0, 7.5], [8.5, 9.0]]),
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[auto_path, fare_path],
        include_default_mode=False,
        zone_mapping_extra_lines=[
            "  file_lookup_names:",
            "    fares.omx: zone_number",
        ],
        extra_lines=[
            "modes:",
            "  SOV:",
            "    fare:",
            "      matrix: FARE",
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
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"
    assert prepared.trips["skim_fare"].to_list() == [7.5]
    assert prepared.tours["skim_fare"].to_list() == [7.5]


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


def test_run_prepare_workflow_handles_trips_without_canonical_trip_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir, trip_id_column_name="linked_trip_id")
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
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
    assert "trip_id" not in prepared.trips.columns
    assert prepared.trips["skim_time"].to_list() == [2.0]
    assert prepared.tours["skim_time"].to_list() == [2.0]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"


def test_annotate_trips_handles_late_matrix_names_in_missing_report_without_schema_failure(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="OTHER_MATRIX")
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "dimensions:",
            "  TOD:",
            "    source_column: time_period",
            "    values:",
            "      1: MD",
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_L_TIME__{TOD}",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": list(range(1, 123)),
            "trip_mode": ["SOV"] * 122,
            "OTAZ": [101] * 122,
            "DTAZ": [102] * 122,
            "time_period": [None] * 121 + [1],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(trips, normalized, inventory)

    assert annotated.height == 122
    assert lookup_summary.is_empty()
    assert missing.height == 122
    assert missing.schema["matrix_name"] == pl.String
    assert missing.filter(pl.col("reason") == "missing_matrix")["matrix_name"].to_list() == [
        "SOV_L_TIME__MD"
    ]
    assert (
        missing.filter(
            pl.col("reason") == "missing_dimension_value:TOD"
        )["matrix_name"].null_count()
        == 121
    )


def test_apply_skimjoin_records_failure_and_keeps_base_tables_when_annotation_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()
    original_trips = prepared.trips.clone()
    original_tours = prepared.tours.clone()

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)

    result = apply_skimjoin(prepared, config)

    assert result.trips.to_dicts() == original_trips.to_dicts()
    assert result.tours.to_dicts() == original_tours.to_dicts()
    assert result.skimjoin_manifest["skimjoin_status"] == "failed"
    assert "annotation exploded" in str(result.skimjoin_manifest["skimjoin_failure_detail"])
    assert result.skimjoin_manifest["skimjoin_applied_outputs"] == []
    assert result.skimjoin_reports["failure_report"]["stage"].to_list() == [
        "integrated_skimjoin"
    ]


def test_apply_skimjoin_records_failure_and_keeps_base_tables_when_tour_aggregation_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()
    original_trips = prepared.trips.clone()
    original_tours = prepared.tours.clone()

    def _boom(*args, **kwargs):
        raise RuntimeError("tour aggregation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.aggregate_tours_from_trips", _boom)

    result = apply_skimjoin(prepared, config)

    assert result.trips.to_dicts() == original_trips.to_dicts()
    assert result.tours.to_dicts() == original_tours.to_dicts()
    assert result.skimjoin_manifest["skimjoin_status"] == "failed"
    assert "tour aggregation exploded" in str(
        result.skimjoin_manifest["skimjoin_failure_detail"]
    )
    assert result.skimjoin_reports["failure_report"]["error_type"].to_list() == [
        "RuntimeError"
    ]


def test_prepared_cache_round_trip_preserves_skimjoin_failure_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)
    prepared = apply_skimjoin(prepared, config)

    cache_entry = write_prepared_run_cache(
        prepared,
        config,
        run_key="run-a",
        output_root=tmp_path / "prepared_cache",
    )
    loaded = load_prepared_run_cache(
        cache_entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label=prepared.label,
        expected_run_key="run-a",
    )

    assert loaded.skimjoin_manifest["skimjoin_status"] == "failed"
    assert loaded.skimjoin_manifest["skimjoin_failure_detail"] == "ValueError: annotation exploded"


def _skimjoin_ready_run_data() -> RunData:
    return RunData(
        label="Skimjoin Ready",
        run_dir="C:/runs/skimjoin-ready",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "tour_mode": ["SOV"],
                "finalweight": [1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1001],
                "trip_mode": ["SOV"],
                "outbound": [True],
                "origin": [101],
                "destination": [102],
                "finalweight": [1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _skim_summary_run_data() -> RunData:
    return RunData(
        label="Skim Summary Test",
        run_dir="C:/runs/skim",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_mode": ["DRIVE", "DRIVE", "DRIVE", "WALK", "WALK"],
                "skim_time": [10.0, 0.0, None, 5.0, 5.0],
                "skim_cost": [2.0, 4.0, 4.0, 1.0, None],
                "finalweight": [2.0, 1.0, 3.0, 1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_mode": ["DRIVE", "DRIVE", "DRIVE", "WALK", "WALK"],
                "skim_time": [10.0, 0.0, None, 5.0, 5.0],
                "skim_cost": [2.0, 4.0, 4.0, 1.0, None],
                "finalweight": [2.0, 1.0, 3.0, 1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_trip_skim_component_stats_and_ecdf_follow_weighted_contract(tmp_path: Path) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = _skim_summary_run_data()

    weighted_stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)
    weighted_ecdf = skimjoin_summaries.trip_skim_component_ecdf(prepared, config)

    drive_time = weighted_stats.filter(
        (pl.col("trip_mode") == "DRIVE") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]
    drive_cost = weighted_stats.filter(
        (pl.col("trip_mode") == "DRIVE") & (pl.col("component") == "skim_cost")
    ).to_dicts()[0]

    assert drive_time == {
        "trip_mode": "DRIVE",
        "component": "skim_time",
        "n_total": 6.0,
        "n_valid": 3.0,
        "mean": pytest.approx(20.0 / 3.0),
        "std": pytest.approx(math.sqrt(200.0 / 9.0)),
        "min": 0.0,
        "max": 10.0,
        "median": 10.0,
        "mode": 10.0,
        "zero_share": pytest.approx(1.0 / 3.0),
        "missing_share": 0.5,
    }
    assert drive_cost == {
        "trip_mode": "DRIVE",
        "component": "skim_cost",
        "n_total": 6.0,
        "n_valid": 6.0,
        "mean": pytest.approx(20.0 / 6.0),
        "std": pytest.approx(math.sqrt(8.0 / 9.0)),
        "min": 2.0,
        "max": 4.0,
        "median": 4.0,
        "mode": 4.0,
        "zero_share": 0.0,
        "missing_share": 0.0,
    }

    drive_time_ecdf = weighted_ecdf.filter(
        (pl.col("trip_mode") == "DRIVE") & (pl.col("component") == "skim_time")
    )
    assert drive_time_ecdf.height == 101
    assert drive_time_ecdf.filter(pl.col("percentile") == 0.0)["value"].to_list() == [0.0]
    assert drive_time_ecdf.filter(pl.col("percentile") == 0.34)["value"].to_list() == [10.0]
    assert drive_time_ecdf.filter(pl.col("percentile") == 1.0)["value"].to_list() == [10.0]
    assert drive_time_ecdf["n_valid"].unique().to_list() == [3.0]


def test_skimjoin_failure_keeps_non_skim_summaries_available_and_skim_summaries_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.prepared_runs[0][1]
    summaries = summary_cache.build_summaries(
        prepared,
        config,
        summary_ids=["population_totals", "skimjoin_trip_component_stats"],
    )

    assert prepared.skimjoin_manifest["skimjoin_status"] == "failed"
    assert not summaries["population_totals"].is_empty()
    assert summaries["skimjoin_trip_component_stats"].is_empty()


def test_tour_skim_component_summaries_follow_unweighted_mode(tmp_path: Path) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = summary_cache.strip_weights(_skim_summary_run_data())

    stats = skimjoin_summaries.tour_skim_component_stats(prepared, config)
    ecdf = skimjoin_summaries.tour_skim_component_ecdf(prepared, config)

    drive_time = stats.filter(
        (pl.col("tour_mode") == "DRIVE") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]
    assert drive_time["n_total"] == 3.0
    assert drive_time["n_valid"] == 2.0
    assert drive_time["mean"] == 5.0
    assert drive_time["mode"] == 0.0
    assert drive_time["zero_share"] == 0.5
    assert drive_time["missing_share"] == pytest.approx(1.0 / 3.0)

    drive_time_ecdf = ecdf.filter(
        (pl.col("tour_mode") == "DRIVE") & (pl.col("component") == "skim_time")
    )
    assert drive_time_ecdf.filter(pl.col("percentile") == 0.5)["value"].to_list() == [0.0]
    assert drive_time_ecdf.filter(pl.col("percentile") == 0.51)["value"].to_list() == [10.0]


def test_skim_component_summaries_return_typed_empty_frames_without_numeric_skim_columns(
    tmp_path: Path,
) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = RunData(
        label="Empty",
        run_dir="C:/runs/empty",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame({"tour_mode": ["DRIVE"], "skim_label": ["x"], "finalweight": [1.0]}),
        trips=pl.DataFrame({"trip_mode": ["DRIVE"], "skim_label": ["x"], "finalweight": [1.0]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    trip_stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)
    trip_ecdf = skimjoin_summaries.trip_skim_component_ecdf(prepared, config)
    tour_stats = skimjoin_summaries.tour_skim_component_stats(prepared, config)
    tour_ecdf = skimjoin_summaries.tour_skim_component_ecdf(prepared, config)

    assert trip_stats.schema == empty_summary_frame(
        skimjoin_summaries.trip_skim_component_stats
    ).schema
    assert trip_ecdf.schema == empty_summary_frame(
        skimjoin_summaries.trip_skim_component_ecdf
    ).schema
    assert tour_stats.schema == empty_summary_frame(
        skimjoin_summaries.tour_skim_component_stats
    ).schema
    assert tour_ecdf.schema == empty_summary_frame(
        skimjoin_summaries.tour_skim_component_ecdf
    ).schema
    assert trip_stats.is_empty()
    assert trip_ecdf.is_empty()
    assert tour_stats.is_empty()
    assert tour_ecdf.is_empty()


def test_skim_component_summaries_handle_late_float_values_without_schema_inference_failures(
    tmp_path: Path,
) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = RunData(
        label="Schema Mix",
        run_dir="C:/runs/schema-mix",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(
            {
                "trip_mode": ["DRIVE", "DRIVE"],
                "skim_time": pl.Series("skim_time", [1.0, 15.69609], dtype=pl.Float64),
                "finalweight": [1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)
    ecdf = skimjoin_summaries.trip_skim_component_ecdf(prepared, config)

    drive_time = stats.to_dicts()[0]
    assert drive_time["component"] == "skim_time"
    assert drive_time["max"] == pytest.approx(15.69609)
    assert ecdf.filter(pl.col("percentile") == 1.0)["value"].to_list() == [
        pytest.approx(15.69609)
    ]
