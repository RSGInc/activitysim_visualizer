from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime.workflows as runtime_workflows
import run as cli_run
from runtime.workflows import PreparedRunsArtifact, SummaryRunsArtifact, WorkflowPlan
from processor.models import RunData
from processor.prepare.availability import attach_table_availability
from processor.prepare.cache import (
    build_prepared_manifest_identity,
    write_prepared_run_cache,
)
from runtime.config import Config
from runtime.config.models import SkimjoinSettings
from processor.summarize.contracts import (
    empty_summary_frame,
    get_summary_contract,
    summary_contract,
)
from processor.summarize import cache as summary_cache
from processor.summarize.cache import (
    build_run_fingerprint,
    create_summary_run,
    write_summary_run_cache,
)
from processor.summarize.summary_specs import SummarySpec
from runtime.workflows import prepare as prepare_workflow


def _write_config(
    tmp_path: Path,
    *,
    runs: list[dict],
    dashboard_pages: list[str] | None = None,
    export_html_lines: list[str] | None = None,
    display_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        'name: "Workflow Test Config"',
        "root: summary_cache",
        "summarize:",
        "  weighting_modes:",
        "    - weighted",
        "    - unweighted",
        "dashboard:",
        '  title: "Workflow Test Dashboard"',
    ]
    if display_lines:
        lines.append("display:")
        lines.extend(f"  {line}" for line in display_lines)
    if dashboard_pages is not None:
        lines.extend(["  live:", "    pages:"])
        lines.extend(f"      - {page_id}" for page_id in dashboard_pages)
    if export_html_lines:
        lines.append("  export:")
        lines.extend(f"    {line}" for line in export_html_lines)
    lines.append("runs:")
    for run_entry in runs:
        lines.append("  -")
        if "dir" in run_entry:
            run_dir = str(run_entry["dir"]).replace("\\", "/")
            lines.append(f'    dir: "{run_dir}"')
        lines.append(f'    label: "{run_entry["label"]}"')
        prepared_table_map = run_entry.get("prepared_table_map")
        if prepared_table_map:
            lines.append("    prepared_table_map:")
            for table_id, path in prepared_table_map.items():
                normalized_path = str(Path(path).resolve()).replace("\\", "/")
                lines.append(f'      {table_id}: "{normalized_path}"')
        summary_table_map = run_entry.get("summary_table_map")
        if summary_table_map:
            lines.append("    summary_table_map:")
            for summary_id, path in summary_table_map.items():
                normalized_path = str(Path(path).resolve()).replace("\\", "/")
                lines.append(f'      {summary_id}: "{normalized_path}"')
    if extra_lines:
        lines.extend(extra_lines)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _workflow_plan(
    config: Config,
    *,
    skimjoin: bool | None = None,
    segment: bool | None = None,
) -> WorkflowPlan:
    steps = list(config.pipeline.steps)
    for step, enabled, dependency in (
        ("skimjoin", skimjoin, "prepare"),
        ("segment", segment, "summarize"),
    ):
        if enabled is None:
            continue
        steps = [candidate for candidate in steps if candidate != step]
        if enabled:
            insert_at = steps.index(dependency) + 1
            steps.insert(insert_at, step)
    return WorkflowPlan.for_steps(config, steps)


def _simple_summary_run(label: str, run_key: str) -> object:
    return create_summary_run(
        label=label,
        run_key=run_key,
        summaries_by_mode={
            "weighted": {"totals": pl.DataFrame({"population": [100.0]})},
            "unweighted": {"totals": pl.DataFrame({"population": [50.0]})},
        },
        source_run_dir=f"C:/runs/{run_key}",
    )


def _simple_summary_mode_build(label: str, run_key: str) -> tuple[dict, dict]:
    summary_run = _simple_summary_run(label, run_key)
    return (
        summary_run.summaries_by_mode,
        {
            mode: {"totals": {"state": "available"}}
            for mode in summary_run.summaries_by_mode
        },
    )


def _fake_run_data(label: str, run_dir: str) -> RunData:
    return RunData(
        label=label,
        run_dir=run_dir,
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _write_custom_prepared_tables(
    root: Path,
    *,
    file_format: str = "parquet",
) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    tables = {
        "households": pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        "persons": pl.DataFrame({"person_id": [10], "household_id": [1], "finalweight": [1.0]}),
        "tours": pl.DataFrame({"tour_id": [100], "person_id": [10], "household_id": [1], "finalweight": [1.0]}),
        "trips": pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10], "finalweight": [1.0]}),
        "joint_tour_participants": pl.DataFrame({"tour_id": [], "person_id": []}),
        "land_use": pl.DataFrame({"zone_id": [1], "TAZ": [1]}),
    }
    paths: dict[str, str] = {}
    for table_id, table in tables.items():
        path = root / f"{table_id}.{file_format}"
        if file_format == "parquet":
            table.write_parquet(path)
        else:
            table.write_csv(path)
        paths[table_id] = str(path.resolve())
    return paths


def _write_inconsistent_custom_prepared_tables(
    root: Path,
    *,
    file_format: str = "parquet",
) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    tables = {
        "households": pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        "persons": pl.DataFrame(
            {"person_id": [10], "household_id": [1], "finalweight": [1.0]}
        ),
        "tours": pl.DataFrame(
            {
                "tour_id": [100],
                "person_id": [10],
                "household_id": [1],
                "finalweight": [1.0],
            }
        ),
        "trips": pl.DataFrame(
            {
                "trip_id": [1000, 1001],
                "tour_id": [100, 999],
                "person_id": [10, 999],
                "household_id": [1, 999],
                "finalweight": [1.0, 1.0],
            }
        ),
        "joint_tour_participants": pl.DataFrame({"tour_id": [], "person_id": []}),
        "land_use": pl.DataFrame({"zone_id": [1], "TAZ": [1]}),
    }
    paths: dict[str, str] = {}
    for table_id, table in tables.items():
        path = root / f"{table_id}.{file_format}"
        if file_format == "parquet":
            table.write_parquet(path)
        else:
            table.write_csv(path)
        paths[table_id] = str(path.resolve())
    return paths


def _write_summary_table(path: Path, value: float) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "households": [value],
            "population": [value],
            "tours": [value],
            "trips": [value],
            "stops": [value],
            "vehicle_trips": [value],
            "vmt": [value],
            "pmt": [value],
            "employment": [value],
        }
    ).write_csv(path)
    return str(path.resolve())


def _write_auto_vmt_validation_summary(path: Path, value: float) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "TOD": ["Daily"],
            "SOV": [value],
            "HOV2": [0.0],
            "HOV3": [0.0],
            "Truck": [0.0],
            "Total": [value],
        }
    ).write_csv(path)
    return str(path.resolve())


def _prepared_identity(
    *,
    config: Config,
    run_key: str,
    label: str,
    run_dir: str,
) -> dict[str, object]:
    return build_prepared_manifest_identity(
        run_key=run_key,
        config=config,
        run_fingerprint=build_run_fingerprint(
            label=label,
            run_dir=run_dir,
            skim_file=None,
            hh_weight_col=None,
            person_weight_col=None,
            trip_weight_col=None,
        ),
    )


def test_load_runtime_config_rejects_unknown_summary_table_map_id(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "unknown.csv"
    _write_summary_table(summary_path, 1.0)
    _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {"unknown_summary": summary_path},
            }
        ],
    )

    with pytest.raises(ValueError, match="unsupported summary ids"):
        runtime_workflows.load_runtime_config(tmp_path / "config.yaml")


def test_load_runtime_config_rejects_old_demo_validation_summary_ids(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "vmtSummary.csv"
    _write_auto_vmt_validation_summary(summary_path, 1.0)
    _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {"demo_auto_vmt_summary": summary_path},
            }
        ],
    )

    with pytest.raises(ValueError, match="unsupported summary ids"):
        runtime_workflows.load_runtime_config(tmp_path / "config.yaml")


def test_non_default_summary_specs_remain_registered_but_not_default_built(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, runs=[{"label": "External"}])

    spec = summary_cache.SUMMARY_SPEC_BY_ID["auto_vmt_validation_summary"]

    assert spec.build_by_default is False
    assert (
        summary_cache.SUMMARY_FILENAME_BY_ID["auto_vmt_validation_summary"]
        == "auto_vmt_validation_summary.csv"
    )
    assert "auto_vmt_validation_summary" not in summary_cache.DEFAULT_SUMMARY_IDS
    assert "auto_vmt_validation_summary" not in summary_cache.requested_summary_ids(
        config
    )


def test_validation_scaffold_summaries_are_registered_with_empty_contracts(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, runs=[{"label": "External"}])
    expected_ids = {
        "link_validation_summary",
        "count_location_counts_validation_summary",
        "count_location_volumes_validation_summary",
        "count_location_scatter_validation_summary",
        "count_location_fit_validation_summary",
        "county_flows_validation_summary",
        "county_flows_joja_validation_summary",
        "commercial_vehicle_validation_summary",
        "commercial_vehicle_vmt_validation_summary",
        "external_trip_validation_summary",
        "external_vmt_validation_summary",
        "auto_vmt_validation_summary",
        "work_from_home_validation_summary",
    }

    for summary_id in expected_ids:
        spec = summary_cache.SUMMARY_SPEC_BY_ID[summary_id]
        contract = get_summary_contract(spec.builder)

        assert spec.build_by_default is False
        assert contract is not None
        assert empty_summary_frame(spec.builder).schema == dict(contract.schema)
        assert summary_cache.SUMMARY_FILENAME_BY_ID[summary_id] == f"{summary_id}.csv"
        assert summary_id not in summary_cache.DEFAULT_SUMMARY_IDS
        assert summary_id not in summary_cache.requested_summary_ids(config)


def test_run_summary_workflow_loads_summary_only_run_without_prepared_inputs(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "totals.csv"
    _write_summary_table(summary_path, 11.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {"totals": summary_path},
            }
        ],
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )

    assert result.prepared.runs == []
    assert [run.label for run in result.runs] == ["External"]
    assert (
        result.runs[0].summaries_by_mode["weighted"]["totals"]["population"][0]
        == 11.0
    )
    assert (
        result.runs[0].summaries_by_mode["unweighted"]["totals"]["population"][0]
        == 11.0
    )


def test_summary_only_run_loads_non_default_summary_table_map_id(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "vmtSummary.csv"
    _write_auto_vmt_validation_summary(summary_path, 42.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {
                    "auto_vmt_validation_summary": summary_path,
                },
            }
        ],
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )

    weighted = result.runs[0].summaries_by_mode["weighted"]
    assert weighted["auto_vmt_validation_summary"].to_dicts() == [
        {
            "TOD": "Daily",
            "SOV": 42.0,
            "HOV2": 0.0,
            "HOV3": 0.0,
            "Truck": 0.0,
            "Total": 42.0,
        }
    ]
    assert not (
        Path(config.summary_root)
        / "external"
        / "summary_tables"
        / "weighted"
        / "totals.csv"
    ).exists()


def test_summary_only_run_bypasses_skimjoin_when_pipeline_enables_it(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "totals.csv"
    _write_summary_table(summary_path, 41.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {"totals": summary_path},
            }
        ],
        extra_lines=[
            "pipeline:",
            "  steps:",
            "    - prepare",
            "    - skimjoin",
            "    - summarize",
            "skimjoin:",
            "  create_hypothetical_skim_tables: true",
            "  defaults:",
        ],
    )

    prepare_result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
        plan=_workflow_plan(config, skimjoin=True),
    )
    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
        prepared=prepare_result,
        plan=_workflow_plan(config, skimjoin=True),
    )

    assert prepare_result.runs == []
    assert [run.label for run in result.runs] == ["External"]
    assert (
        result.runs[0].summaries_by_mode["weighted"]["totals"]["population"][0]
        == 41.0
    )
    loaded = runtime_workflows.load_summary_runs_from_cache(
        config=config,
        cache_root=Path(config.summary_root),
        explicit_cache_dirs=None,
        run_entries=config.runs,
        required_summary_ids=("totals",),
    )
    assert loaded[0].summaries_by_mode["weighted"]["totals"]["population"][0] == 41.0


def test_run_summary_workflow_overlays_summary_table_map_on_generated_summaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    summary_path = tmp_path / "outside" / "totals.csv"
    _write_summary_table(summary_path, 99.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "dir": str(run_dir),
                "label": "Run A",
                "summary_table_map": {"totals": summary_path},
            }
        ],
    )
    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals", "population_totals"])
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config, summary_ids=None: (
            {
                "weighted": {
                    summary_id: pl.DataFrame({"metric": [summary_id], "value": [1.0]})
                    for summary_id in summary_ids
                },
                "unweighted": {
                    summary_id: pl.DataFrame({"metric": [summary_id], "value": [2.0]})
                    for summary_id in summary_ids
                },
            },
            {
                mode: {
                    summary_id: {"state": "available"}
                    for summary_id in summary_ids
                }
                for mode in ("weighted", "unweighted")
            },
        ),
    )
    monkeypatch.setattr(
        prepare_workflow,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or "Run A",
            str(run_dir),
        ),
    )
    monkeypatch.setattr(prepare_workflow, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    weighted = result.runs[0].summaries_by_mode["weighted"]
    assert weighted["totals"]["population"][0] == 99.0
    assert weighted["population_totals"].to_dicts() == [
        {"metric": "population_totals", "value": 1.0}
    ]


def test_run_summary_workflow_reuses_all_existing_prepared_runs_when_cache_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    config = _write_config(
        tmp_path,
        runs=[
            {"dir": str(run_a_dir), "label": "Run A"},
            {"dir": str(run_b_dir), "label": "Run B"},
        ],
    )
    prepared_a = _fake_run_data("Run A", str(run_a_dir))
    prepared_b = _fake_run_data("Run B", str(run_b_dir))
    existing_result = PreparedRunsArtifact(
        runs=[("Run A", prepared_a), ("Run B", prepared_b)],
        by_key={
            "run-a": ("Run A", prepared_a),
            "run-b": ("Run B", prepared_b),
        },
        run_keys=["run-a", "run-b"],
    )
    summary_build_labels: list[str] = []

    def fake_build_mode_summaries_with_metadata(rd, config, summary_ids=None):
        summary_build_labels.append(rd.label)
        requested = list(summary_ids or [])
        return (
            {
                mode: {
                    summary_id: pl.DataFrame({"run": [rd.label]})
                    for summary_id in requested
                }
                for mode in config.weighting_modes
            },
            {
                mode: {
                    summary_id: {"state": "available"}
                    for summary_id in requested
                }
                for mode in config.weighting_modes
            },
        )

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        fake_build_mode_summaries_with_metadata,
    )
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("existing prepared runs should be reused")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("existing prepared runs should be reused")
        ),
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        prepared_prefer_cache=False,
        write_cache=False,
        prepared=existing_result,
    )

    assert summary_build_labels == ["Run A", "Run B"]
    assert result.prepared.by_key["run-a"][1] is prepared_a
    assert result.prepared.by_key["run-b"][1] is prepared_b
    assert result.prepared.run_keys == ["run-a", "run-b"]


def test_prepare_then_summary_does_not_rerun_skimjoin_for_existing_prepared_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    config = _write_config(
        tmp_path,
        runs=[
            {"dir": str(run_a_dir), "label": "Run A"},
            {"dir": str(run_b_dir), "label": "Run B"},
        ],
        extra_lines=[
            "pipeline:",
            "  steps:",
            "    - prepare",
            "    - skimjoin",
            "    - summarize",
        ],
    )
    read_labels: list[str] = []
    skimjoin_labels: list[str] = []

    def fake_read_run(run_dir, config, label=None, **kwargs):
        run_label = label or Path(run_dir).name
        read_labels.append(run_label)
        return _fake_run_data(run_label, str(run_dir))

    def fake_apply_skimjoin(rd, config):
        skimjoin_labels.append(rd.label)
        return rd

    def fake_build_mode_summaries_with_metadata(rd, config, summary_ids=None):
        requested = list(summary_ids or [])
        return (
            {
                mode: {
                    summary_id: pl.DataFrame({"run": [rd.label]})
                    for summary_id in requested
                }
                for mode in config.weighting_modes
            },
            {
                mode: {
                    summary_id: {"state": "available"}
                    for summary_id in requested
                }
                for mode in config.weighting_modes
            },
        )

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        fake_build_mode_summaries_with_metadata,
    )
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=fake_read_run,
        prepare_data=lambda rd, config: rd,
    )
    def fake_resolve_skimjoin(config, entry):
        return SkimjoinSettings(
            enabled=True,
            config_path="mock_skimjoin.yaml",
            config_digest="mock-digest",
        )

    monkeypatch.setattr(
        "runtime.config.resolve_run_skimjoin_settings",
        fake_resolve_skimjoin,
    )
    monkeypatch.setattr(
        "runtime.config.normalize_prepare.resolve_run_skimjoin_settings",
        fake_resolve_skimjoin,
    )
    monkeypatch.setattr(prepare_workflow, "apply_skimjoin", fake_apply_skimjoin)

    prepare_result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
        plan=_workflow_plan(config, skimjoin=True),
    )
    runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        prepared_prefer_cache=False,
        write_cache=False,
        prepared=prepare_result,
        plan=_workflow_plan(config, skimjoin=True),
    )

    assert read_labels == ["Run A", "Run B"]
    assert skimjoin_labels == ["Run A", "Run B"]


def test_run_summary_workflow_does_not_build_non_default_registered_summaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    build_calls: list[list[str] | None] = []

    def fake_build_mode_summaries_with_metadata(rd, config, summary_ids=None):
        build_calls.append(list(summary_ids) if summary_ids is not None else None)
        requested = list(summary_ids or [])
        return (
            {
                mode: {
                    summary_id: pl.DataFrame({"value": [1.0]})
                    for summary_id in requested
                }
                for mode in config.weighting_modes
            },
            {
                mode: {
                    summary_id: {"state": "available"}
                    for summary_id in requested
                }
                for mode in config.weighting_modes
            },
        )

    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        fake_build_mode_summaries_with_metadata,
    )
    monkeypatch.setattr(
        prepare_workflow,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or "Run A",
            str(run_dir),
        ),
    )
    monkeypatch.setattr(prepare_workflow, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )

    assert build_calls
    assert all("auto_vmt_validation_summary" not in call for call in build_calls if call)
    assert (
        "auto_vmt_validation_summary"
        not in result.runs[0].summaries_by_mode["weighted"]
    )
    assert not (
        Path(config.summary_root)
        / "run-a"
        / "summary_tables"
        / "weighted"
        / "auto_vmt_validation_summary.csv"
    ).exists()


def test_mixed_run_preserves_generated_defaults_and_overlays_non_default_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    summary_path = tmp_path / "outside" / "vmtSummary.csv"
    _write_auto_vmt_validation_summary(summary_path, 88.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "dir": str(run_dir),
                "label": "Run A",
                "summary_table_map": {
                    "auto_vmt_validation_summary": summary_path,
                },
            }
        ],
    )
    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config, summary_ids=None: (
            {
                mode: {
                    "totals": pl.DataFrame({"population": [1.0]}),
                }
                for mode in config.weighting_modes
            },
            {
                mode: {"totals": {"state": "available"}}
                for mode in config.weighting_modes
            },
        ),
    )
    monkeypatch.setattr(
        prepare_workflow,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or "Run A",
            str(run_dir),
        ),
    )
    monkeypatch.setattr(prepare_workflow, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    weighted = result.runs[0].summaries_by_mode["weighted"]
    assert weighted["totals"].to_dicts() == [{"population": 1.0}]
    assert weighted["auto_vmt_validation_summary"].to_dicts() == [
        {
            "TOD": "Daily",
            "SOV": 88.0,
            "HOV2": 0.0,
            "HOV3": 0.0,
            "Truck": 0.0,
            "Total": 88.0,
        }
    ]


def test_summary_table_map_file_identity_invalidates_summary_cache(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "totals.csv"
    _write_summary_table(summary_path, 11.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {"totals": summary_path},
            }
        ],
    )
    runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )
    _write_summary_table(summary_path, 12.0)

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert (
        result.runs[0].summaries_by_mode["weighted"]["totals"]["population"][0]
        == 12.0
    )


def test_dashboard_only_loads_summary_table_map_without_cache(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "totals.csv"
    _write_summary_table(summary_path, 21.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {"totals": summary_path},
            }
        ],
    )

    loaded = runtime_workflows.load_summary_runs_from_cache(
        config=config,
        cache_root=Path(config.summary_root),
        explicit_cache_dirs=None,
        run_entries=config.runs,
        required_summary_ids=("totals",),
    )

    assert [run.label for run in loaded] == ["External"]
    assert loaded[0].summaries_by_mode["weighted"]["totals"]["population"][0] == 21.0


def test_dashboard_only_loads_non_default_summary_table_map_id(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "vmtSummary.csv"
    _write_auto_vmt_validation_summary(summary_path, 31.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {
                    "auto_vmt_validation_summary": summary_path,
                },
            }
        ],
    )

    loaded = runtime_workflows.load_summary_runs_from_cache(
        config=config,
        cache_root=Path(config.summary_root),
        explicit_cache_dirs=None,
        run_entries=config.runs,
        required_summary_ids=("auto_vmt_validation_summary",),
    )

    assert [run.label for run in loaded] == ["External"]
    loaded_table = loaded[0].summaries_by_mode["weighted"]["auto_vmt_validation_summary"]
    assert loaded_table.to_dicts() == [
        {
            "TOD": "Daily",
            "SOV": 31.0,
            "HOV2": 0.0,
            "HOV3": 0.0,
            "Truck": 0.0,
            "Total": 31.0,
        }
    ]


def test_dashboard_only_respects_empty_required_summary_ids_for_optional_only_page(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "vmtSummary.csv"
    _write_auto_vmt_validation_summary(summary_path, 17.0)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {
                    "auto_vmt_validation_summary": summary_path,
                },
            }
        ],
    )

    loaded = runtime_workflows.load_summary_runs_from_cache(
        config=config,
        cache_root=Path(config.summary_root),
        explicit_cache_dirs=None,
        run_entries=config.runs,
        required_summary_ids=(),
    )

    assert loaded[0].summaries_by_mode["weighted"]["auto_vmt_validation_summary"][
        "SOV"
    ][0] == 17.0


def test_summary_table_map_contract_rejects_missing_external_columns(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "outside" / "vmtSummary.csv"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"TOD": ["Daily"], "SOV": [1.0]}).write_csv(summary_path)
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "External",
                "summary_table_map": {
                    "auto_vmt_validation_summary": summary_path,
                },
            }
        ],
    )

    with pytest.raises(
        ValueError,
        match=r"summary_table_map\['auto_vmt_validation_summary'\] is missing required columns",
    ):
        runtime_workflows.run_summary_workflow(
            config=config,
            cache_root=Path(config.summary_root),
            prepared_root=Path(config.summary_root),
            run_entries=config.runs,
            prefer_cache=False,
            write_cache=False,
        )


def test_prune_summary_runs_keeps_optional_summary_ids_when_requested() -> None:
    summary_run = create_summary_run(
        label="External",
        run_key="external",
        summaries_by_mode={
            "weighted": {
                "totals": pl.DataFrame({"population": [1.0]}),
                "auto_vmt_validation_summary": pl.DataFrame(
                    {
                        "TOD": ["Daily"],
                        "SOV": [2.0],
                        "HOV2": [0.0],
                        "HOV3": [0.0],
                        "Truck": [0.0],
                        "Total": [2.0],
                    }
                ),
            },
            "unweighted": {
                "totals": pl.DataFrame({"population": [1.0]}),
                "auto_vmt_validation_summary": pl.DataFrame(
                    {
                        "TOD": ["Daily"],
                        "SOV": [2.0],
                        "HOV2": [0.0],
                        "HOV3": [0.0],
                        "Truck": [0.0],
                        "Total": [2.0],
                    }
                ),
            },
        },
    )

    pruned = runtime_workflows.prune_summary_runs(
        [summary_run],
        ("totals", "auto_vmt_validation_summary"),
    )

    assert set(pruned[0].summaries_by_mode["weighted"]) == {
        "totals",
        "auto_vmt_validation_summary",
    }


def test_run_prepare_workflow_uses_cache_hit_without_raw_read_or_prepare_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    prepared_run = _fake_run_data("Run A", str(run_dir))
    write_prepared_run_cache(
        prepared_run,
        config,
        run_key="run-a",
        output_root=prepared_root,
        run_fingerprint=build_run_fingerprint(
            label="Run A",
            run_dir=config.runs[0]["dir"],
            skim_file=None,
            hh_weight_col=None,
            person_weight_col=None,
            trip_weight_col=None,
        ),
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called on a prepared-cache hit")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called on a prepared-cache hit")
        ),
    )


def _segmented_run_data(label: str, run_dir: str) -> RunData:
    return RunData(
        label=label,
        run_dir=run_dir,
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2],
                "market": ["Urban", "Rural"],
                "finalweight": [1.0, 1.0],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [10, 20],
                "household_id": [1, 2],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [100, 200],
                "person_id": [10, 20],
                "household_id": [1, 2],
                "finalweight": [1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [1000, 2000],
                "tour_id": [100, 200],
                "person_id": [10, 20],
                "household_id": [1, 2],
                "finalweight": [1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame({"tour_id": [100, 200], "person_id": [10, 20]}),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert [label for label, _ in result.runs] == ["Run A"]
    assert result.run_keys == ["run-a"]


def test_run_prepare_workflow_rebuilds_and_writes_prepared_cache_on_cache_miss(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    read_calls: list[str] = []
    prepare_calls: list[str] = []

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
        prepare_data=lambda rd, config: (
            prepare_calls.append(rd.label),
            rd,
        )[1],
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert read_calls == ["Run A"]
    assert prepare_calls == ["Run A"]


def test_run_prepare_workflow_skips_integrated_skimjoin_when_apply_skimjoin_is_false(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    config.skimjoin = SkimjoinSettings(
        enabled=True,
        config_path="skimjoin.yaml",
        config_digest="digest-123",
        normalized_config=object(),
    )
    config.prepare_config_digest = "prepare-before"
    config.summary_config_digest = "summary-before"

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or Path(run_dir).name,
            str(run_dir),
        ),
        prepare_data=lambda rd, config: rd,
    )
    monkeypatch.setattr(
        prepare_workflow,
        "apply_skimjoin",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("apply_skimjoin should not be called when skimjoin is disabled for the effective workflow")
        ),
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=runtime_workflows.prepared_cache_root(config, create=True),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
        plan=_workflow_plan(config, skimjoin=False),
    )

    assert [label for label, _ in result.runs] == ["Run A"]


def test_run_prepare_workflow_applies_integrated_skimjoin_when_enabled_for_effective_workflow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    config.skimjoin = SkimjoinSettings(
        enabled=True,
        config_path="skimjoin.yaml",
        config_digest="digest-123",
        normalized_config=object(),
    )
    config.pipeline = replace(
        config.pipeline,
        steps=("prepare", "skimjoin", "summarize", "dashboard"),
    )
    skimjoin_calls: list[str] = []

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or Path(run_dir).name,
            str(run_dir),
        ),
        prepare_data=lambda rd, config: rd,
    )
    monkeypatch.setattr(
        prepare_workflow,
        "apply_skimjoin",
        lambda rd, config: (
            skimjoin_calls.append(rd.label),
            rd,
        )[1],
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=runtime_workflows.prepared_cache_root(config, create=True),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
        plan=_workflow_plan(config, skimjoin=True),
    )

    assert [label for label, _ in result.runs] == ["Run A"]
    assert skimjoin_calls == ["Run A"]


def test_run_summary_workflow_without_segment_step_builds_only_full_summary_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
        extra_lines=[
            "segment:",
            "  dashboard:",
            "    segmentation_type: market",
            "  definitions:",
            "    market:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: market",
            "      segments:",
            "        - id: urban",
            "          label: Urban",
            "          values: [Urban]",
            "        - id: rural",
            "          label: Rural",
            "          values: [Rural]",
        ],
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: _segmented_run_data(
            label or Path(run_dir).name,
            str(run_dir),
        ),
        prepare_data=lambda rd, config: rd,
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config: _simple_summary_mode_build(rd.label, Path(rd.run_dir).name),
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
        plan=_workflow_plan(config, segment=False),
    )

    assert [(run.segmentation_type, run.segment_id) for run in result.runs] == [
        ("full", "full")
    ]


def test_run_summary_workflow_with_segment_step_builds_full_and_segmented_summary_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
        extra_lines=[
            "pipeline:",
            "  steps: [segment, summarize, dashboard]",
            "segment:",
            "  dashboard:",
            "    segmentation_type: market",
            "  definitions:",
            "    market:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: market",
            "      segments:",
            "        - id: urban",
            "          label: Urban",
            "          values: [Urban]",
            "        - id: rural",
            "          label: Rural",
            "          values: [Rural]",
        ],
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: _segmented_run_data(
            label or Path(run_dir).name,
            str(run_dir),
        ),
        prepare_data=lambda rd, config: rd,
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config: _simple_summary_mode_build(rd.label, Path(rd.run_dir).name),
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
        plan=_workflow_plan(config, segment=True),
    )

    assert [(run.segmentation_type, run.segment_id) for run in result.runs] == [
        ("full", "full"),
        ("market", "urban"),
        ("market", "rural"),
    ]


def test_run_prepare_workflow_loads_custom_prepared_tables_without_raw_prepare(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared_map = _write_custom_prepared_tables(tmp_path / "custom_prepared")
    config = _write_config(
        tmp_path,
        runs=[
            {
                "label": "Prepared Run",
                "prepared_table_map": prepared_map,
            }
        ],
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called for custom prepared runs")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called for custom prepared runs")
        ),
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=runtime_workflows.prepared_cache_root(config, create=True),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert [label for label, _ in result.runs] == ["Prepared Run"]
    assert result.runs[0][1].hh["household_id"].to_list() == [1]


def test_run_prepare_workflow_warns_on_inconsistent_custom_prepared_tables(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepared_map = _write_inconsistent_custom_prepared_tables(
        tmp_path / "custom_prepared"
    )
    config = _write_config(
        tmp_path,
        runs=[{"label": "Prepared Run", "prepared_table_map": prepared_map}],
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=runtime_workflows.prepared_cache_root(config, create=True),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert [label for label, _ in result.runs] == ["Prepared Run"]
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert 'Prepared relationship validation found 3 failed checks for run "Prepared Run".' in combined_output
    assert "trips rows reference person_id values not present in persons.person_id" in combined_output


def test_run_prepare_workflow_errors_on_inconsistent_custom_prepared_tables_when_configured(
    tmp_path: Path,
) -> None:
    prepared_map = _write_inconsistent_custom_prepared_tables(
        tmp_path / "custom_prepared"
    )
    config = _write_config(
        tmp_path,
        runs=[{"label": "Prepared Run", "prepared_table_map": prepared_map}],
        extra_lines=[
            "prepare:",
            "  validation:",
            "    relationship_checks: error",
        ],
    )

    with pytest.raises(RuntimeError, match='Prepared relationship validation failed for run "Prepared Run"'):
        runtime_workflows.run_prepare_workflow(
            config=config,
            prepared_root=runtime_workflows.prepared_cache_root(config, create=True),
            run_entries=config.runs,
            prefer_cache=True,
            write_cache=True,
        )


def test_run_prepare_workflow_skips_relationship_validation_when_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared_map = _write_inconsistent_custom_prepared_tables(
        tmp_path / "custom_prepared"
    )
    config = _write_config(
        tmp_path,
        runs=[{"label": "Prepared Run", "prepared_table_map": prepared_map}],
        extra_lines=[
            "prepare:",
            "  validation:",
            "    relationship_checks: off",
        ],
    )

    monkeypatch.setattr(
        "runtime.workflows.prepare.validate_prepared_relationships",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("validate_prepared_relationships should not be called when disabled")
        ),
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=runtime_workflows.prepared_cache_root(config, create=True),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert [label for label, _ in result.runs] == ["Prepared Run"]


def test_run_prepare_workflow_skips_run_when_no_raw_tables_are_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: attach_table_availability(
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
            table_states={
                "households": "unavailable",
                "persons": "unavailable",
                "tours": "unavailable",
                "trips": "unavailable",
                "joint_tour_participants": "unavailable",
                "land_use": "unavailable",
            },
            table_reasons={"households": "missing"},
        ),
        prepare_data=lambda rd, config: rd,
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert result.runs == []
    assert result.by_key == {}


def test_run_prepare_workflow_keeps_partial_run_when_some_tables_are_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: attach_table_availability(
            RunData(
                label=label or Path(run_dir).name,
                run_dir=str(run_dir),
                skim_file=None,
                hh=pl.DataFrame({"household_id": [1]}),
                per=pl.DataFrame(),
                tours=pl.DataFrame(),
                trips=pl.DataFrame(),
                joint_participants=pl.DataFrame(),
                land_use=pl.DataFrame(),
                skim_matrix=None,
                skim_zone_map=None,
            ),
            table_states={
                "households": "available",
                "persons": "unavailable",
                "tours": "unavailable",
                "trips": "unavailable",
                "joint_tour_participants": "unavailable",
                "land_use": "unavailable",
            },
            table_reasons={"persons": "missing"},
        ),
        prepare_data=lambda rd, config: rd,
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert [label for label, _ in result.runs] == ["Run A"]
    assert list(result.by_key) == ["run-a"]


def test_run_prepare_workflow_keeps_partial_run_when_some_tables_are_failed(
    tmp_path: Path,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: attach_table_availability(
            RunData(
                label=label or Path(run_dir).name,
                run_dir=str(run_dir),
                skim_file=None,
                hh=pl.DataFrame({"household_id": [1]}),
                per=pl.DataFrame({"person_id": [1]}),
                tours=pl.DataFrame(),
                trips=pl.DataFrame(),
                joint_participants=pl.DataFrame(),
                land_use=pl.DataFrame(),
                skim_matrix=None,
                skim_zone_map=None,
            ),
            table_states={
                "households": "available",
                "persons": "available",
                "tours": "failed",
                "trips": "unavailable",
                "joint_tour_participants": "unavailable",
                "land_use": "unavailable",
            },
            table_reasons={
                "tours": "tour enrichment failed",
                "trips": "missing",
            },
        ),
        prepare_data=lambda rd, config: rd,
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert [label for label, _ in result.runs] == ["Run A"]
    assert list(result.by_key) == ["run-a"]
    captured = capsys.readouterr()
    assert "recorded failed tables" in (caplog.text + captured.err + captured.out)


def test_run_prepare_workflow_validates_prepared_cache_loads(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    prepared_run = RunData(
        label="Run A",
        run_dir=str(run_dir),
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {"person_id": [10], "household_id": [1], "finalweight": [1.0]}
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [100],
                "person_id": [10],
                "household_id": [1],
                "finalweight": [1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [1000, 1001],
                "tour_id": [100, 999],
                "person_id": [10, 999],
                "household_id": [1, 999],
                "finalweight": [1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame({"tour_id": [], "person_id": []}),
        land_use=pl.DataFrame({"zone_id": [1], "TAZ": [1]}),
        skim_matrix=None,
        skim_zone_map=None,
    )
    write_prepared_run_cache(
        prepared_run,
        config,
        run_key="run-a",
        output_root=prepared_root,
        run_fingerprint=build_run_fingerprint(
            label="Run A",
            run_dir=config.runs[0]["dir"],
            skim_file=None,
            hh_weight_col=None,
            person_weight_col=None,
            trip_weight_col=None,
        ),
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert [label for label, _ in result.runs] == ["Run A"]
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert 'Prepared relationship validation found 3 failed checks for run "Run A".' in combined_output


def test_run_summary_workflow_uses_cache_hit_without_raw_read_or_summary_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    summary_run = _simple_summary_run("Run A", "run-a")
    write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=build_run_fingerprint(
            label="Run A",
            run_dir=config.runs[0]["dir"],
            skim_file=None,
            hh_weight_col=None,
            person_weight_col=None,
            trip_weight_col=None,
        ),
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="run-a",
            label="Run A",
            run_dir=config.runs[0]["dir"],
        ),
    )

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called on a cache hit")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called on a cache hit")
        ),
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "build_mode_summaries_with_metadata should not be called on a cache hit"
            )
        ),
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert [summary_run.label for summary_run in result.runs] == ["Run A"]
    assert result.prepared.runs == []
    assert result.prepared.by_key == {}


def test_run_summary_workflow_cache_hit_keeps_existing_prepared_run_by_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    summary_run = _simple_summary_run("Run A", "run-a")
    prepared_run = _fake_run_data("Run A", str(run_dir))
    fingerprint = build_run_fingerprint(
        label="Run A",
        run_dir=config.runs[0]["dir"],
        skim_file=None,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )
    write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="run-a",
            label="Run A",
            run_dir=config.runs[0]["dir"],
        ),
    )

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called on a summary-cache hit")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called on a summary-cache hit")
        ),
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "build_mode_summaries_with_metadata should not be called on a summary-cache hit"
            )
        ),
    )

    existing_result = PreparedRunsArtifact(
        runs=[("Run A", prepared_run)],
        by_key={"run-a": ("Run A", prepared_run)},
        run_keys=["run-a"],
        fingerprints_by_key={"run-a": fingerprint},
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
        prepared=existing_result,
    )

    assert [summary_run.label for summary_run in result.runs] == ["Run A"]
    assert [label for label, _ in result.prepared.runs] == ["Run A"]
    assert result.prepared.by_key["run-a"][1] is prepared_run


def test_run_summary_workflow_rebuilds_and_writes_cache_on_cache_miss(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    read_calls: list[str] = []
    prepare_calls: list[str] = []
    summary_build_calls: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
        prepare_data=lambda rd, config: (
            prepare_calls.append(rd.label),
            rd,
        )[1],
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config: (
            summary_build_calls.append(rd.label),
            _simple_summary_mode_build(rd.label, Path(rd.run_dir).name),
        )[1],
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert read_calls == ["Run A"]
    assert prepare_calls == ["Run A"]
    assert summary_build_calls == ["Run A"]
    assert [summary_run.label for summary_run in result.runs] == ["Run A"]
    assert [label for label, _ in result.prepared.runs] == ["Run A"]
    assert list(result.prepared.by_key) == ["run-a"]
    assert (Path(config.summary_root) / "run-a" / "manifest.json").exists()
    assert (
        Path(config.summary_root) / "run-a" / "prepared_tables" / "manifest.json"
    ).exists()


def test_run_summary_workflow_uses_prepared_cache_before_raw_rebuild(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    prepared_run = _fake_run_data("Run A", str(run_dir))
    read_calls: list[str] = []
    prepare_calls: list[str] = []
    summary_build_calls: list[str] = []

    processor_prepare_fingerprint = build_run_fingerprint(
        label="Run A",
        run_dir=config.runs[0]["dir"],
        skim_file=None,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )
    write_prepared_run_cache(
        prepared_run,
        config,
        run_key="run-a",
        output_root=prepared_root,
        run_fingerprint=processor_prepare_fingerprint,
    )

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
        prepare_data=lambda rd, config: (
            prepare_calls.append(rd.label),
            rd,
        )[1],
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config: (
            summary_build_calls.append(rd.label),
            _simple_summary_mode_build(rd.label, Path(rd.run_dir).name),
        )[1],
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert read_calls == []
    assert prepare_calls == []
    assert summary_build_calls == ["Run A"]
    assert [label for label, _ in result.prepared.runs] == ["Run A"]


def test_run_summary_workflow_reuses_in_memory_prepared_runs_without_reload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_run = _fake_run_data("Run A", str(run_dir))
    summary_build_calls: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when prepared runs already exist in memory")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called when prepared runs already exist in memory")
        ),
    )
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        lambda rd, config: (
            summary_build_calls.append(rd.label),
            _simple_summary_mode_build(rd.label, Path(rd.run_dir).name),
        )[1],
    )

    existing_result = PreparedRunsArtifact(
        runs=[("Run A", prepared_run)],
        by_key={"run-a": ("Run A", prepared_run)},
        run_keys=["run-a"],
        fingerprints_by_key={
            "run-a": build_run_fingerprint(
                label="Run A",
                run_dir=config.runs[0]["dir"],
                skim_file=None,
                hh_weight_col=None,
                person_weight_col=None,
                trip_weight_col=None,
            )
        },
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
        prepared=existing_result,
    )

    assert summary_build_calls == ["Run A"]
    assert result.prepared.by_key["run-a"][1] is prepared_run


def _patch_prepare_pipeline(
    monkeypatch,
    *,
    read_run=None,
    prepare_data=None,
) -> None:
    if read_run is not None:
        monkeypatch.setattr(prepare_workflow, "read_run", read_run)
    if prepare_data is not None:
        monkeypatch.setattr(prepare_workflow, "prepare_data", prepare_data)


def test_run_summary_workflow_backfills_only_missing_summary_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    @summary_contract(schema={"value": pl.Float64})
    def good_summary(rd: RunData, config: Config) -> pl.DataFrame:
        return pl.DataFrame({"value": [1.0]})

    @summary_contract(schema={"value": pl.Float64})
    def new_summary(rd: RunData, config: Config) -> pl.DataFrame:
        return pl.DataFrame({"value": [2.0]})

    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    prepared_run = _fake_run_data("Run A", str(run_dir))
    fingerprint = build_run_fingerprint(
        label="Run A",
        run_dir=config.runs[0]["dir"],
        skim_file=None,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )
    write_prepared_run_cache(
        prepared_run,
        config,
        run_key="run-a",
        output_root=prepared_root,
        run_fingerprint=fingerprint,
    )
    cached_only_good = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={
            "weighted": {"good": pl.DataFrame({"value": [1.0]})},
            "unweighted": {"good": pl.DataFrame({"value": [1.0]})},
        },
        summary_metadata_by_mode={
            "weighted": {"good": {"state": "available"}},
            "unweighted": {"good": {"state": "available"}},
        },
        source_run_dir=str(run_dir),
    )
    monkeypatch.setitem(
        summary_cache.SUMMARY_SPEC_BY_ID,
        "good",
        SummarySpec("good", "good", good_summary),
    )
    monkeypatch.setitem(
        summary_cache.SUMMARY_SPEC_BY_ID,
        "new",
        SummarySpec("new", "new", new_summary),
    )
    monkeypatch.setitem(summary_cache.SUMMARY_FILENAME_BY_ID, "good", "good.csv")
    monkeypatch.setitem(summary_cache.SUMMARY_FILENAME_BY_ID, "new", "new.csv")
    summary_cache.write_summary_run_bundle(
        [cached_only_good],
        config,
        output_root=Path(config.summary_root),
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="run-a",
            label="Run A",
            run_dir=config.runs[0]["dir"],
        ),
    )

    build_calls: list[list[str] | None] = []
    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["good", "new"])

    def fake_build_mode_summaries_with_metadata(rd, config, summary_ids=None):
        build_calls.append(list(summary_ids) if summary_ids is not None else None)
        tables = {}
        metadata = {}
        requested = summary_ids or ["good", "new"]
        for mode in config.weighting_modes:
            mode_tables = {}
            mode_metadata = {}
            for summary_id in requested:
                mode_tables[summary_id] = pl.DataFrame(
                    {"value": [2.0 if summary_id == "new" else 1.0]}
                )
                mode_metadata[summary_id] = {"state": "available"}
            tables[mode] = mode_tables
            metadata[mode] = mode_metadata
        return tables, metadata

    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries_with_metadata",
        fake_build_mode_summaries_with_metadata,
    )
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when prepared cache is valid")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called when prepared cache is valid")
        ),
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert build_calls == [["new"]]
    weighted_tables = result.runs[0].summaries_by_mode["weighted"]
    assert sorted(weighted_tables) == ["good", "new"]


def test_run_cli_resolves_export_html_path_with_cli_config_and_default_precedence(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        export_html_lines=[
            "output_path: configured/dashboard.html",
        ],
    )

    assert (
        cli_run._resolve_export_html_path(None, config, dashboard_mode="live") is None
    )
    assert (
        cli_run._resolve_export_html_path(
            "custom/out.html",
            config,
            dashboard_mode="export",
        )
        == "custom/out.html"
    )
    assert cli_run._resolve_export_html_path(
        cli_run._EXPORT_HTML_USE_CONFIG_SENTINEL,
        config,
        dashboard_mode="export",
    ) == str((tmp_path / "summary_cache" / "configured" / "dashboard.html").resolve())

    config_without_output = _write_config(tmp_path / "fallback", runs=[])
    assert cli_run._resolve_export_html_path(
        cli_run._EXPORT_HTML_USE_CONFIG_SENTINEL,
        config_without_output,
        dashboard_mode="export",
    ) == str(Path(config_without_output.summary_root) / "exported_dashboard.html")


def test_run_cli_uses_configured_terminal_log_level(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        extra_lines=[
            "log_level: error",
        ],
    )

    assert cli_run._resolve_terminal_log_level(config) == 40


def test_resolve_requested_steps_uses_config_pipeline_defaults(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        extra_lines=[
            "pipeline:",
            "  steps:",
            "    - prepare",
            "    - skimjoin",
            "    - dashboard",
        ],
    )

    args = argparse.Namespace(
        prepare=False,
        summarize=False,
        dashboard=False,
        prepare_only=False,
        write_csvs=False,
        no_dashboard=False,
        from_csvs=None,
        skip_summary_cache_write=False,
        refresh_caches=False,
        refresh_prepared_cache=False,
        refresh_summary_cache=False,
        export_html=None,
    )

    assert cli_run.resolve_requested_steps(args, config) == [
        "prepare",
        "skimjoin",
        "dashboard",
    ]


def test_resolve_effective_plan_uses_pipeline_dashboard_mode_and_overwrite(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        extra_lines=[
            "pipeline:",
            "  steps:",
            "    - summarize",
            "    - dashboard",
            "  dashboard_mode: export",
            "  overwrite: true",
        ],
    )

    args = argparse.Namespace(
        prepare=False,
        summarize=False,
        dashboard=False,
        prepare_only=False,
        write_csvs=False,
        no_dashboard=False,
        from_csvs=None,
        skip_summary_cache_write=False,
        refresh_caches=False,
        refresh_prepared_cache=False,
        refresh_summary_cache=False,
        export_html=None,
    )

    plan = cli_run.resolve_effective_plan(args, config)

    assert plan.runtime_steps == ("summarize", "dashboard")
    assert plan.logical_steps == ("summarize", "dashboard")
    assert plan.dashboard_mode == "export"
    assert plan.overwrite is True


def test_resolve_effective_plan_drops_dashboard_when_config_dashboard_mode_is_none(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        extra_lines=[
            "pipeline:",
            "  steps:",
            "    - summarize",
            "    - dashboard",
            "  dashboard_mode: none",
        ],
    )

    args = argparse.Namespace(
        prepare=False,
        summarize=False,
        dashboard=False,
        prepare_only=False,
        write_csvs=False,
        no_dashboard=False,
        from_csvs=None,
        skip_summary_cache_write=False,
        refresh_caches=False,
        refresh_prepared_cache=False,
        refresh_summary_cache=False,
        export_html=None,
    )

    plan = cli_run.resolve_effective_plan(args, config)

    assert plan.logical_steps == ("summarize",)
    assert plan.runtime_steps == ("summarize",)
    assert plan.dashboard_mode == "none"


def test_resolve_dashboard_execution_mode_maps_host_to_live_with_warning(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    execution_mode = cli_run.resolve_dashboard_execution_mode("host")

    assert execution_mode == "live"
    captured = capsys.readouterr()
    combined_output = caplog.text + captured.err + captured.out
    assert (
        "pipeline.dashboard_mode 'host' is not implemented yet; using live mode."
        in combined_output
    )


def test_resolve_effective_plan_preserves_logical_skimjoin_step_for_prepare_only_defaults(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        extra_lines=[
            "pipeline:",
            "  steps:",
            "    - prepare",
            "    - skimjoin",
        ],
    )

    args = argparse.Namespace(
        prepare=False,
        summarize=False,
        dashboard=False,
        prepare_only=False,
        write_csvs=False,
        no_dashboard=False,
        from_csvs=None,
        skip_summary_cache_write=False,
        refresh_caches=False,
        refresh_prepared_cache=False,
        refresh_summary_cache=False,
        export_html=None,
    )

    plan = cli_run.resolve_effective_plan(args, config)

    assert plan.logical_steps == ("prepare", "skimjoin")
    assert plan.runtime_steps == ("prepare",)


def test_run_cli_resolves_export_html_path_from_config_dashboard_mode(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        runs=[],
        export_html_lines=[
            "output_path: configured/dashboard.html",
        ],
    )

    assert cli_run._resolve_export_html_path(
        None,
        config,
        dashboard_mode="export",
    ) == str((tmp_path / "summary_cache" / "configured" / "dashboard.html").resolve())
    assert (
        cli_run._resolve_export_html_path(
            None,
            config,
            dashboard_mode="live",
        )
        is None
    )


def test_parse_args_accepts_export_html_without_path(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["activitysim-viz", "--config", "config.yaml", "--export-html"],
    )

    args = cli_run.parse_args()

    assert args.export_html == cli_run._EXPORT_HTML_USE_CONFIG_SENTINEL


def test_run_summary_workflow_continues_when_one_summary_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )

    @summary_contract(schema={"value": pl.Float64})
    def good_summary(rd: RunData, config: Config) -> pl.DataFrame:
        return pl.DataFrame({"value": [1.0]})

    @summary_contract(schema={"value": pl.Float64})
    def bad_summary(rd: RunData, config: Config) -> pl.DataFrame:
        raise RuntimeError("boom")

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["good", "bad"])
    monkeypatch.setitem(summary_cache.SUMMARY_SPEC_BY_ID, "good", SummarySpec("good", "good", good_summary))
    monkeypatch.setitem(summary_cache.SUMMARY_SPEC_BY_ID, "bad", SummarySpec("bad", "bad", bad_summary))
    monkeypatch.setitem(summary_cache.SUMMARY_FILENAME_BY_ID, "good", "good.csv")
    monkeypatch.setitem(summary_cache.SUMMARY_FILENAME_BY_ID, "bad", "bad.csv")
    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or Path(run_dir).name,
            str(run_dir),
        ),
        prepare_data=lambda rd, config: rd,
    )

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    weighted = result.runs[0].summaries_by_mode["weighted"]
    metadata = result.runs[0].summary_metadata_by_mode["weighted"]
    assert weighted["good"].to_dicts() == [{"value": 1.0}]
    assert weighted["bad"].is_empty()
    assert metadata["good"]["state"] == "available"
    assert metadata["bad"]["state"] == "failed"


def test_load_prepared_runs_for_dashboard_reuses_existing_loaded_runs_by_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    config = _write_config(
        tmp_path,
        runs=[
            {"dir": str(run_a_dir), "label": "Run A"},
            {"dir": str(run_b_dir), "label": "Run B"},
        ],
    )
    existing_run = _fake_run_data("Run A", str(run_a_dir))
    read_calls: list[str] = []
    prepare_calls: list[str] = []

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
        prepare_data=lambda rd, config: (
            prepare_calls.append(rd.label),
            rd,
        )[1],
    )

    ordered_runs = runtime_workflows.load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=["run-a", "run-b"],
        existing_prepared_runs_by_key={"run-a": ("Run A", existing_run)},
    )

    assert [label for label, _ in ordered_runs] == ["Run A", "Run B"]
    assert ordered_runs[0][1] is existing_run
    assert read_calls == ["Run B"]
    assert prepare_calls == ["Run B"]


def test_load_prepared_runs_for_dashboard_returns_empty_when_required_runs_are_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_a_dir), "label": "Run A"}],
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when required runs are unresolved")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called when required runs are unresolved")
        ),
    )

    ordered_runs = runtime_workflows.load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=["run-a", "run-b"],
    )

    assert ordered_runs == []


def test_load_prepared_runs_for_dashboard_supports_custom_prepared_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared_map = _write_custom_prepared_tables(tmp_path / "custom_prepared", file_format="csv")
    config = _write_config(
        tmp_path,
        runs=[{"label": "Prepared Run", "prepared_table_map": prepared_map}],
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called for custom prepared dashboard loads")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called for custom prepared dashboard loads")
        ),
    )

    ordered_runs = runtime_workflows.load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=["prepared-run"],
    )

    assert [label for label, _ in ordered_runs] == ["Prepared Run"]
    assert ordered_runs[0][1].trips["trip_id"].to_list() == [1000]


def test_prune_summary_artifact_keeps_only_required_dashboard_data() -> None:
    prepared_run = RunData(
        label="Run A",
        run_dir="C:/runs/run_a",
        skim_file="C:/runs/run_a/skims.omx",
        hh=pl.DataFrame({"household_id": [1]}),
        per=pl.DataFrame({"person_id": [10]}),
        tours=pl.DataFrame({"tour_id": [20]}),
        trips=pl.DataFrame({"trip_id": [100], "trip_mode": ["WALK"]}),
        joint_participants=pl.DataFrame({"tour_id": [20], "person_id": [10]}),
        land_use=pl.DataFrame({"zone_id": [1]}),
        skim_matrix=None,
        skim_zone_map={1: 0},
    )
    summary_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={
            "weighted": {
                "population_totals": pl.DataFrame({"person_count": [100.0]}),
                "extra_summary": pl.DataFrame({"value": [1]}),
            },
            "unweighted": {
                "population_totals": pl.DataFrame({"person_count": [50.0]}),
                "extra_summary": pl.DataFrame({"value": [2]}),
            },
        },
        source_run_dir="C:/runs/run_a",
    )
    result = SummaryRunsArtifact(
        runs=[summary_run],
        prepared=PreparedRunsArtifact(
            runs=[("Run A", prepared_run)],
            by_key={"run-a": ("Run A", prepared_run)},
            run_keys=["run-a"],
        ),
    )

    pruned = runtime_workflows.prune_summary_artifact(
        result,
        required_summary_ids=("population_totals",),
        required_prepared_tables=("trips",),
    )

    assert pruned is not None
    assert list(pruned.runs[0].summaries_by_mode["weighted"]) == [
        "population_totals"
    ]
    assert pruned.prepared.by_key["run-a"][1].hh.is_empty()
    assert pruned.prepared.by_key["run-a"][1].per.is_empty()
    assert pruned.prepared.by_key["run-a"][1].trips is prepared_run.trips
    assert pruned.prepared.by_key["run-a"][1].trips["trip_id"].to_list() == [100]
    assert pruned.prepared.by_key["run-a"][1].skim_file is None


def test_load_prepared_runs_for_dashboard_prunes_existing_runs_to_required_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_a_dir), "label": "Run A"}],
    )
    existing_run = RunData(
        label="Run A",
        run_dir=str(run_a_dir),
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1]}),
        per=pl.DataFrame({"person_id": [10]}),
        tours=pl.DataFrame({"tour_id": [20]}),
        trips=pl.DataFrame({"trip_id": [100], "trip_mode": ["WALK"]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame({"zone_id": [1]}),
        skim_matrix=None,
        skim_zone_map=None,
    )

    _patch_prepare_pipeline(
        monkeypatch,
        read_run=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when the run is already loaded")
        ),
        prepare_data=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called when the run is already loaded")
        ),
    )

    ordered_runs = runtime_workflows.load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=["run-a"],
        required_prepared_tables=("trips",),
        existing_prepared_runs_by_key={"run-a": ("Run A", existing_run)},
    )

    assert [label for label, _ in ordered_runs] == ["Run A"]
    assert ordered_runs[0][1].hh.is_empty()
    assert ordered_runs[0][1].tours.is_empty()
    assert ordered_runs[0][1].trips["trip_id"].to_list() == [100]


def test_load_prepared_runs_for_dashboard_dedupes_required_run_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_a_dir), "label": "Run A"}],
    )
    captured: dict[str, object] = {}
    prepared_run = RunData(
        label="Run A",
        run_dir=str(run_a_dir),
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1]}),
        per=pl.DataFrame({"person_id": [10]}),
        tours=pl.DataFrame({"tour_id": [20]}),
        trips=pl.DataFrame({"trip_id": [100]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    def fake_run_prepare_workflow(**kwargs):
        captured["run_entries"] = kwargs["run_entries"]
        captured["run_keys"] = [
            run_key
            for _, run_key in runtime_workflows.run_entries_with_keys(
                kwargs["run_entries"]
            )
        ]
        return PreparedRunsArtifact(
            runs=[("Run A", prepared_run)],
            by_key={"run-a": ("Run A", prepared_run)},
            run_keys=["run-a"],
        )

    monkeypatch.setattr(prepare_workflow, "run_prepare_workflow", fake_run_prepare_workflow)

    ordered_runs = runtime_workflows.load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=["run-a", "run-a", "run-a"],
        existing_prepared_runs_by_key={},
    )

    assert [entry["label"] for entry in captured["run_entries"]] == ["Run A"]
    assert captured["run_keys"] == ["run-a"]
    assert [label for label, _ in ordered_runs] == ["Run A"]


def test_run_dashboard_workflow_prunes_inputs_before_live_dashboard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import panel as pn
    from dashboard import app as dashboard_app

    config = _write_config(
        tmp_path,
        runs=[],
        dashboard_pages=["raw_trip_demo"],
    )
    prepared_run = RunData(
        label="Run A",
        run_dir="C:/runs/run_a",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1]}),
        per=pl.DataFrame({"person_id": [10]}),
        tours=pl.DataFrame({"tour_id": [20]}),
        trips=pl.DataFrame({"trip_id": [100], "trip_mode": ["WALK"]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame({"zone_id": [1]}),
        skim_matrix=None,
        skim_zone_map=None,
    )
    summary_run = create_summary_run(
        label="Run A",
        run_key="run-a",
        summaries_by_mode={
            "weighted": {
                "population_totals": pl.DataFrame({"person_count": [100.0]}),
            },
            "unweighted": {
                "population_totals": pl.DataFrame({"person_count": [50.0]}),
            },
        },
        source_run_dir="C:/runs/run_a",
    )
    captured: dict[str, object] = {}

    def fake_build_dashboard(runs, config, summary_runs=None):
        captured["runs"] = runs
        captured["summary_runs"] = summary_runs
        return "dashboard"

    monkeypatch.setattr(dashboard_app, "build_dashboard", fake_build_dashboard)
    monkeypatch.setattr(pn, "serve", lambda *args, **kwargs: None)

    runtime_workflows.run_dashboard_workflow(
        prepared_runs=[("Run A", prepared_run)],
        summary_runs=[summary_run],
        config=config,
        show=False,
    )

    assert captured["runs"][0][1].hh.is_empty()
    assert captured["runs"][0][1].per.is_empty()
    assert captured["runs"][0][1].trips["trip_id"].to_list() == [100]
    assert captured["summary_runs"][0].summaries_by_mode["weighted"] == {}
