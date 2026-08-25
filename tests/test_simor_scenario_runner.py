from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

from scripts import run_simor_scenarios as runner


def _args(tmp_path: Path, *, dry_run: bool = False) -> Namespace:
    return Namespace(
        max_parallel=2,
        log_root=tmp_path / "logs",
        refresh_caches=False,
        dry_run=dry_run,
    )


def _configure_test_scenarios(monkeypatch, tmp_path: Path) -> None:
    configs = []
    for name in ("metro", "lcog", "skats", "comparison"):
        path = tmp_path / f"{name}.yaml"
        path.write_text("name: test\n", encoding="utf-8")
        configs.append((name, path))
    monkeypatch.setattr(runner, "AREA_CONFIGS", tuple(configs[:3]))
    monkeypatch.setattr(runner, "COMPARISON_CONFIG", configs[3])


def test_run_scenarios_waits_for_areas_before_comparison(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_test_scenarios(monkeypatch, tmp_path)
    batches: list[tuple[list[str], int]] = []

    def fake_run_batch(jobs, *, max_parallel, poll_interval=0.25):
        batches.append(([job.name for job in jobs], max_parallel))
        return True

    monkeypatch.setattr(runner, "_run_batch", fake_run_batch)

    assert runner.run_scenarios(_args(tmp_path)) == 0
    assert batches == [
        (["metro", "lcog", "skats"], 2),
        (["comparison"], 1),
    ]


def test_run_scenarios_skips_comparison_after_area_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_test_scenarios(monkeypatch, tmp_path)
    batches: list[list[str]] = []

    def fake_run_batch(jobs, *, max_parallel, poll_interval=0.25):
        batches.append([job.name for job in jobs])
        return False

    monkeypatch.setattr(runner, "_run_batch", fake_run_batch)

    assert runner.run_scenarios(_args(tmp_path)) == 1
    assert batches == [["metro", "lcog", "skats"]]


def test_run_batch_records_console_output(tmp_path: Path) -> None:
    console_log = tmp_path / "probe.console.log"
    job = runner.ScenarioJob(
        name="probe",
        config_path=tmp_path / "probe.yaml",
        runtime_log=tmp_path / "probe.runtime.log",
        console_log=console_log,
        command=(sys.executable, "-c", "print('runner-probe')"),
    )

    assert runner._run_batch([job], max_parallel=1, poll_interval=0.01) is True
    assert console_log.read_text(encoding="utf-8").strip() == "runner-probe"


def test_dry_run_does_not_create_log_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_test_scenarios(monkeypatch, tmp_path)

    assert runner.run_scenarios(_args(tmp_path, dry_run=True)) == 0
    assert not (tmp_path / "logs").exists()
