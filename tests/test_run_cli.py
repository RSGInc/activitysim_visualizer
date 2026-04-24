from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run
import runtime_workflows
from dashboard import app as dashboard_app
from processor.models import RunData
from processor.prepare.cache import build_prepared_manifest_identity
from runtime.config import Config
from processor.summarize import cache as summary_cache
from processor.summarize.cache import (
    build_run_fingerprint,
    create_summary_run,
    write_summary_run_cache,
)

def _write_cli_config(
    tmp_path: Path,
    *,
    runs: list[dict],
    dashboard_pages: list[str] | None = None,
    export_html_lines: list[str] | None = None,
) -> Config:
    lines = [
        'name: "CLI Test Config"',
        "summaries:",
        "  root: summary_cache",
        "  weighting_modes:",
        "    - weighted",
        "    - unweighted",
        "visualizer:",
        '  dashboard_title: "CLI Test Dashboard"',
    ]
    if dashboard_pages is not None:
        lines.append("  dashboard_pages:")
        lines.extend(f"    - {page_id}" for page_id in dashboard_pages)
    if export_html_lines:
        lines.append("  export_html:")
        lines.extend(f"    {line}" for line in export_html_lines)
    lines.extend(
        [
        "runs:",
        ]
    )
    for run_entry in runs:
        run_dir = str(run_entry["dir"]).replace("\\", "/")
        lines.extend(
            [
                f'  - dir: "{run_dir}"',
                f'    label: "{run_entry["label"]}"',
            ]
        )

    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _simple_summary_run(label: str, run_key: str) -> object:
    weighted = {"totals": pl.DataFrame({"population": [100.0]})}
    unweighted = {"totals": pl.DataFrame({"population": [50.0]})}
    return create_summary_run(
        label=label,
        run_key=run_key,
        summaries_by_mode={"weighted": weighted, "unweighted": unweighted},
        source_run_dir=f"C:/runs/{run_key}",
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


def test_main_rejects_no_dashboard_without_write_csvs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--no-dashboard",
        ],
    )

    with pytest.raises(SystemExit, match="1"):
        run.main()

    captured = capsys.readouterr()
    assert captured.err == "Error: --no-dashboard requires --write-csvs.\n"


def test_main_rejects_from_csvs_with_write_csvs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--write-csvs",
            "--from-csvs",
        ],
    )

    with pytest.raises(SystemExit, match="1"):
        run.main()

    captured = capsys.readouterr()
    assert captured.err == "Error: --from-csvs cannot be combined with --write-csvs.\n"


def test_main_rejects_dashboard_step_without_summarize_or_from_csvs(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_cli_config(tmp_path, runs=[])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--dashboard",
        ],
    )

    with pytest.raises(SystemExit, match="1"):
        run.main()

    captured = capsys.readouterr()
    assert (
        captured.err
        == "Error: dashboard step without summarize requires --from-csvs.\n"
    )


def test_main_loads_dashboard_from_explicit_summary_cache_dirs_without_raw_reads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _write_cli_config(tmp_path, runs=[])
    summary_run = _simple_summary_run("Base", "base")
    cache_dir = write_summary_run_cache(summary_run, config)
    dashboard_calls: list[dict[str, object]] = []
    serve_calls: list[object] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read_run should not be called")),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called")
        ),
    )

    def fake_build_dashboard(runs, config, summary_runs=None):
        dashboard_calls.append(
            {
                "runs": list(runs),
                "summary_labels": [summary_run.label for summary_run in summary_runs or []],
            }
        )
        return "dashboard"

    monkeypatch.setattr(dashboard_app, "build_dashboard", fake_build_dashboard)
    monkeypatch.setattr(
        pn,
        "serve",
        lambda dashboard, **kwargs: serve_calls.append(
            {"dashboard": dashboard, "kwargs": kwargs}
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--from-csvs",
            str(cache_dir),
            "--no-show",
        ],
    )

    run.main()

    assert dashboard_calls == [{"runs": [], "summary_labels": ["Base"]}]
    assert serve_calls == [
        {
            "dashboard": "dashboard",
            "kwargs": {
                "port": 5006,
                "show": False,
                "title": config.dashboard_title,
            },
        }
    ]


def test_main_prepare_only_writes_prepared_cache_and_exits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_cli_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    read_calls: list[str] = []
    prepare_calls: list[str] = []

    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("summaries should not be built during prepare-only runs")
        ),
    )
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
        dashboard_app,
        "build_dashboard",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dashboard should not be built")
        ),
    )
    monkeypatch.setattr(
        pn,
        "serve",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("panel serve should not be called")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--prepare-only",
        ],
    )

    run.main()

    prepared_dir = Path(config.summary_root).parent / "prepared_cache" / "run-a"
    assert read_calls == ["Run A"]
    assert prepare_calls == ["Run A"]
    assert (prepared_dir / "manifest.json").exists()
    assert not (Path(config.summary_root) / "run-a" / "manifest.json").exists()


def test_main_write_csvs_no_dashboard_writes_summary_cache_and_exits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_cli_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    read_calls: list[str] = []
    built_summaries: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries",
        lambda rd, config: (
            built_summaries.append(rd.label),
            _simple_summary_run(rd.label, Path(rd.run_dir).name).summaries_by_mode,
        )[1],
    )
    monkeypatch.setattr(
        dashboard_app,
        "build_dashboard",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dashboard should not be built")
        ),
    )
    monkeypatch.setattr(
        pn,
        "serve",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("panel serve should not be called")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--write-csvs",
            "--no-dashboard",
        ],
    )

    run.main()

    cache_dir = Path(config.summary_root) / "run-a"
    assert read_calls == ["Run A"]
    assert built_summaries == ["Run A"]
    assert (cache_dir / "manifest.json").exists()
    assert (cache_dir / "weighted" / "totals.csv").exists()


def test_main_explicit_prepare_and_summarize_runs_processor_without_dashboard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_cli_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
    )
    read_calls: list[str] = []
    prepare_calls: list[str] = []
    built_summaries: list[str] = []

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
        "build_mode_summaries",
        lambda rd, config: (
            built_summaries.append(rd.label),
            _simple_summary_run(rd.label, Path(rd.run_dir).name).summaries_by_mode,
        )[1],
    )
    monkeypatch.setattr(
        dashboard_app,
        "build_dashboard",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dashboard should not be built")
        ),
    )
    monkeypatch.setattr(
        pn,
        "serve",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("panel serve should not be called")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--prepare",
            "--summarize",
            "--write-csvs",
        ],
    )

    run.main()

    assert read_calls == ["Run A"]
    assert prepare_calls == ["Run A"]
    assert built_summaries == ["Run A"]
    assert (Path(config.summary_root).parent / "prepared_cache" / "run-a").exists()
    assert (Path(config.summary_root) / "run-a" / "manifest.json").exists()


def test_main_uses_cache_hit_for_one_run_and_raw_fallback_for_another(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    config = _write_cli_config(
        tmp_path,
        runs=[
            {"dir": str(run_a_dir), "label": "Run A"},
            {"dir": str(run_b_dir), "label": "Run B"},
        ],
    )
    cached_run = _simple_summary_run("Run A", "run-a")
    write_summary_run_cache(
        cached_run,
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
    dashboard_calls: list[dict[str, object]] = []
    read_calls: list[str] = []
    built_summaries: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)
    monkeypatch.setattr(
        summary_cache,
        "build_mode_summaries",
        lambda rd, config: (
            built_summaries.append(rd.label),
            _simple_summary_run(rd.label, Path(rd.run_dir).name).summaries_by_mode,
        )[1],
    )

    def fake_build_dashboard(runs, config, summary_runs=None):
        dashboard_calls.append(
            {
                "prepared_run_labels": [label for label, _ in runs],
                "summary_run_labels": [summary_run.label for summary_run in summary_runs or []],
            }
        )
        return "dashboard"

    monkeypatch.setattr(dashboard_app, "build_dashboard", fake_build_dashboard)
    monkeypatch.setattr(pn, "serve", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--skip-summary-cache-write",
            "--no-show",
        ],
    )

    run.main()

    assert read_calls == ["Run B"]
    assert built_summaries == ["Run B"]
    assert dashboard_calls == [
        {
            "prepared_run_labels": [],
            "summary_run_labels": ["Run A", "Run B"],
        }
    ]


def test_main_loads_prepared_runs_for_enabled_live_prepared_data_page_even_on_cache_hits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    config = _write_cli_config(
        tmp_path,
        runs=[
            {"dir": str(run_a_dir), "label": "Run A"},
            {"dir": str(run_b_dir), "label": "Run B"},
        ],
        dashboard_pages=["raw_trip_demo"],
    )
    cached_run_a = _simple_summary_run("Run A", "run-a")
    cached_run_b = _simple_summary_run("Run B", "run-b")
    write_summary_run_cache(
        cached_run_a,
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
    write_summary_run_cache(
        cached_run_b,
        config,
        run_fingerprint=build_run_fingerprint(
            label="Run B",
            run_dir=config.runs[1]["dir"],
            skim_file=None,
            hh_weight_col=None,
            person_weight_col=None,
            trip_weight_col=None,
        ),
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="run-b",
            label="Run B",
            run_dir=config.runs[1]["dir"],
        ),
    )
    dashboard_calls: list[dict[str, object]] = []
    read_calls: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)

    def fake_build_dashboard(runs, config, summary_runs=None):
        dashboard_calls.append(
            {
                "prepared_run_labels": [label for label, _ in runs],
                "summary_run_labels": [summary_run.label for summary_run in summary_runs or []],
            }
        )
        return "dashboard"

    monkeypatch.setattr(dashboard_app, "build_dashboard", fake_build_dashboard)
    monkeypatch.setattr(pn, "serve", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--skip-summary-cache-write",
            "--no-show",
        ],
    )

    run.main()

    assert read_calls == ["Run A", "Run B"]
    assert dashboard_calls == [
        {
            "prepared_run_labels": ["Run A", "Run B"],
            "summary_run_labels": ["Run A", "Run B"],
        }
    ]


def test_main_from_csvs_loads_prepared_runs_for_enabled_live_prepared_data_page_when_inputs_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_cli_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
        dashboard_pages=["raw_trip_demo"],
    )
    summary_run = _simple_summary_run("Run A", "run-a")
    cache_dir = write_summary_run_cache(
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
    dashboard_calls: list[dict[str, object]] = []
    read_calls: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(runtime_workflows, "prepare_data", lambda rd, config: rd)

    def fake_build_dashboard(runs, config, summary_runs=None):
        dashboard_calls.append(
            {
                "prepared_run_labels": [label for label, _ in runs],
                "summary_run_labels": [summary_run.label for summary_run in summary_runs or []],
            }
        )
        return "dashboard"

    monkeypatch.setattr(dashboard_app, "build_dashboard", fake_build_dashboard)
    monkeypatch.setattr(pn, "serve", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--from-csvs",
            str(cache_dir),
            "--no-show",
        ],
    )

    run.main()

    assert read_calls == ["Run A"]
    assert dashboard_calls == [
        {
            "prepared_run_labels": ["Run A"],
            "summary_run_labels": ["Run A"],
        }
    ]


def test_main_from_csvs_keeps_prepared_data_page_unavailable_when_no_inputs_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _write_cli_config(tmp_path, runs=[], dashboard_pages=["raw_trip_demo"])
    summary_run = _simple_summary_run("Base", "base")
    cache_dir = write_summary_run_cache(summary_run, config)
    dashboard_calls: list[dict[str, object]] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called")
        ),
    )

    def fake_build_dashboard(runs, config, summary_runs=None):
        dashboard_calls.append(
            {
                "prepared_run_labels": [label for label, _ in runs],
                "summary_run_labels": [summary_run.label for summary_run in summary_runs or []],
            }
        )
        return "dashboard"

    monkeypatch.setattr(dashboard_app, "build_dashboard", fake_build_dashboard)
    monkeypatch.setattr(pn, "serve", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--from-csvs",
            str(cache_dir),
            "--no-show",
        ],
    )

    run.main()

    assert dashboard_calls == [
        {
            "prepared_run_labels": [],
            "summary_run_labels": ["Base"],
        }
    ]


def test_main_export_does_not_load_prepared_runs_for_live_only_prepared_data_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run_a"
    config = _write_cli_config(
        tmp_path,
        runs=[{"dir": str(run_dir), "label": "Run A"}],
        dashboard_pages=["raw_trip_demo"],
    )
    summary_run = _simple_summary_run("Run A", "run-a")
    cache_dir = write_summary_run_cache(
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
    export_calls: list[dict[str, object]] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        runtime_workflows,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read_run should not be called")
        ),
    )
    monkeypatch.setattr(
        runtime_workflows,
        "prepare_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prepare_data should not be called")
        ),
    )

    def fake_write_export(output_path, runs, config, summary_runs=None):
        export_calls.append(
            {
                "output_path": output_path,
                "prepared_run_labels": [label for label, _ in runs],
                "summary_run_labels": [summary_run.label for summary_run in summary_runs or []],
            }
        )

    monkeypatch.setattr(
        "dashboard.export.html.write_export_html_document",  # type: ignore[arg-type]
        fake_write_export,
        raising=False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "activitysim-viz",
            "--config",
            str(tmp_path / "config.yaml"),
            "--from-csvs",
            str(cache_dir),
            "--export-html",
            str(tmp_path / "dashboard.html"),
        ],
    )

    run.main()

    assert export_calls == [
        {
            "output_path": str(tmp_path / "dashboard.html"),
            "prepared_run_labels": [],
            "summary_run_labels": ["Run A"],
        }
    ]


def test_dashboard_workflow_rejects_missing_summary_runs(tmp_path: Path) -> None:
    config = _write_cli_config(tmp_path, runs=[])

    with pytest.raises(
        ValueError,
        match="dashboard workflow requires precomputed summary runs",
    ):
        runtime_workflows.run_dashboard_workflow(
            prepared_runs=[],
            summary_runs=[],
            config=config,
        )
