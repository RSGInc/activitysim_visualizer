from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run
from dashboard import app as dashboard_app
from summarize import cache as summary_cache
from summarize import reader as summary_reader
from summarize.cache import build_run_fingerprint, create_summary_run, write_summary_run_cache
from summarize.reader import Config, RunData


def _write_cli_config(
    tmp_path: Path,
    *,
    runs: list[dict],
) -> Config:
    lines = [
        'name: "CLI Test Config"',
        'dashboard_title: "CLI Test Dashboard"',
        "outputs:",
        "  summary_root: summary_cache",
        "  weighting_modes:",
        "    - weighted",
        "    - unweighted",
        "runs:",
    ]
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
        summary_reader,
        "read_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read_run should not be called")),
    )
    monkeypatch.setattr(
        summary_reader,
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
        summary_reader,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(summary_reader, "prepare_data", lambda rd, config: rd)
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
    )
    dashboard_calls: list[dict[str, object]] = []
    read_calls: list[str] = []
    built_summaries: list[str] = []

    monkeypatch.setattr(summary_cache, "DEFAULT_SUMMARY_IDS", ["totals"])
    monkeypatch.setattr(
        summary_reader,
        "read_run",
        lambda run_dir, config, label=None, **kwargs: (
            read_calls.append(label or Path(run_dir).name),
            _fake_run_data(label or Path(run_dir).name, str(run_dir)),
        )[1],
    )
    monkeypatch.setattr(summary_reader, "prepare_data", lambda rd, config: rd)
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
                "raw_run_labels": [label for label, _ in runs],
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
            "raw_run_labels": ["Run B"],
            "summary_run_labels": ["Run A", "Run B"],
        }
    ]
