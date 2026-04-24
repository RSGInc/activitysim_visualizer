from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime_workflows
from processor.models import ProcessorWorkflowResult
from processor.models import RunData
from processor.prepare.availability import attach_table_availability
from processor.prepare.cache import (
    build_prepared_manifest_identity,
    write_prepared_run_cache,
)
from runtime.config import Config
from processor.summarize.contracts import summary_contract
from processor.summarize import cache as summary_cache
from processor.summarize.cache import (
    build_run_fingerprint,
    create_summary_run,
    write_summary_run_cache,
)
from processor.summarize.summary_specs import SummarySpec


def _write_config(
    tmp_path: Path,
    *,
    runs: list[dict],
    dashboard_pages: list[str] | None = None,
    export_html_lines: list[str] | None = None,
) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        'name: "Workflow Test Config"',
        "summaries:",
        "  root: summary_cache",
        "  weighting_modes:",
        "    - weighted",
        "    - unweighted",
        "visualizer:",
        '  dashboard_title: "Workflow Test Dashboard"',
    ]
    if dashboard_pages is not None:
        lines.append("  dashboard_pages:")
        lines.extend(f"    - {page_id}" for page_id in dashboard_pages)
    if export_html_lines:
        lines.append("  export_html:")
        lines.extend(f"    {line}" for line in export_html_lines)
    lines.append("runs:")
    for run_entry in runs:
        run_dir = str(run_entry["dir"]).replace("\\", "/")
        lines.extend(
            [
                f'  - dir: "{run_dir}"',
                f'    label: "{run_entry["label"]}"',
            ]
        )
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called on a prepared-cache hit")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called on a prepared-cache hit")
        ),
    )

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert [label for label, _ in result.prepared_runs] == ["Run A"]
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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda rd, config: (
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
    assert [label for label, _ in result.prepared_runs] == ["Run A"]
    assert (prepared_root / "run-a" / "manifest.json").exists()


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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: attach_table_availability(
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
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=True,
    )

    assert result.prepared_runs == []
    assert result.prepared_runs_by_key == {}


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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: attach_table_availability(
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
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert [label for label, _ in result.prepared_runs] == ["Run A"]
    assert list(result.prepared_runs_by_key) == ["run-a"]


def test_run_prepare_workflow_keeps_partial_run_when_some_tables_are_failed(
    tmp_path: Path,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: attach_table_availability(
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
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=True,
        write_cache=False,
    )

    assert [label for label, _ in result.prepared_runs] == ["Run A"]
    assert list(result.prepared_runs_by_key) == ["run-a"]
    assert "recorded failed tables" in caplog.text


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
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called on a cache hit")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
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

    assert [summary_run.label for summary_run in result.summary_runs] == ["Run A"]
    assert result.prepared_runs == []
    assert result.prepared_runs_by_key == {}


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
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda rd, config: (
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
    assert [summary_run.label for summary_run in result.summary_runs] == ["Run A"]
    assert [label for label, _ in result.prepared_runs] == ["Run A"]
    assert list(result.prepared_runs_by_key) == ["run-a"]
    assert (Path(config.summary_root) / "run-a" / "manifest.json").exists()
    assert (
        Path(config.summary_root).parent / "prepared_cache" / "run-a" / "manifest.json"
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
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda rd, config: (
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
    assert [label for label, _ in result.prepared_runs] == ["Run A"]


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
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when prepared runs already exist in memory")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called when prepared runs already exist in memory")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "load_prepared_run_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("load_prepared_run_cache should not be called when prepared runs already exist in memory")
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

    existing_result = ProcessorWorkflowResult(
        prepared_runs=[("Run A", prepared_run)],
        prepared_runs_by_key={"run-a": ("Run A", prepared_run)},
        run_keys=["run-a"],
        run_fingerprints_by_key={
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
        existing_result=existing_result,
    )

    assert summary_build_calls == ["Run A"]
    assert result.prepared_runs_by_key["run-a"][1] is prepared_run


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
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: _fake_run_data(
            label or Path(run_dir).name,
            str(run_dir),
        ),
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)

    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=Path(config.summary_root),
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    weighted = result.summary_runs[0].summaries_by_mode["weighted"]
    metadata = result.summary_runs[0].summary_metadata_by_mode["weighted"]
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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda rd, config: (
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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when required runs are unresolved")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called when required runs are unresolved")
        ),
    )

    ordered_runs = runtime_workflows.load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=["run-a", "run-b"],
    )

    assert ordered_runs == []


def test_prune_processor_result_keeps_only_required_dashboard_data() -> None:
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
    result = ProcessorWorkflowResult(
        summary_runs=[summary_run],
        prepared_runs=[("Run A", prepared_run)],
        prepared_runs_by_key={"run-a": ("Run A", prepared_run)},
        run_keys=["run-a"],
    )

    pruned = runtime_workflows.prune_processor_result(
        result,
        required_summary_ids=("population_totals",),
        required_prepared_tables=("trips",),
    )

    assert pruned is not None
    assert list(pruned.summary_runs[0].summaries_by_mode["weighted"]) == [
        "population_totals"
    ]
    assert pruned.prepared_runs_by_key["run-a"][1].hh.is_empty()
    assert pruned.prepared_runs_by_key["run-a"][1].per.is_empty()
    assert pruned.prepared_runs_by_key["run-a"][1].trips is prepared_run.trips
    assert pruned.prepared_runs_by_key["run-a"][1].trips["trip_id"].to_list() == [100]
    assert pruned.prepared_runs_by_key["run-a"][1].skim_file is None


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

    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called when the run is already loaded")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
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
