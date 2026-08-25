"""Build the SIMOR area dashboards in parallel, then build their comparison."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = PROJECT_ROOT / "run.py"
AREA_CONFIGS = (
    ("metro", PROJECT_ROOT / "simor_configs/metro_configs/metro_config.yaml"),
    ("lcog", PROJECT_ROOT / "simor_configs/lcog_configs/lcog_config.yaml"),
    ("skats", PROJECT_ROOT / "simor_configs/skats_configs/skats_config.yaml"),
)
COMPARISON_CONFIG = (
    "comparison",
    PROJECT_ROOT
    / "simor_configs/comparison_configs/estimation_mode_outputs_comparison.yaml",
)
DEFAULT_LOG_ROOT = PROJECT_ROOT / "simor_project_outputs/logs/scenario_runner"


@dataclass(frozen=True)
class ScenarioJob:
    name: str
    config_path: Path
    runtime_log: Path
    console_log: Path
    command: tuple[str, ...]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Metro, LCOG, and SKATS dashboard exports concurrently, then "
            "run the comparison dashboard after all three succeed."
        )
    )
    parser.add_argument(
        "--max-parallel",
        type=_positive_int,
        default=2,
        help="Maximum concurrent area dashboards (default: 2).",
    )
    parser.add_argument(
        "--log-root",
        type=Path,
        default=DEFAULT_LOG_ROOT,
        help="Parent directory for timestamped per-scenario logs.",
    )
    parser.add_argument(
        "--refresh-caches",
        action="store_true",
        help="Pass --refresh-caches to every dashboard build.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the staged commands without running them.",
    )
    return parser.parse_args()


def _build_job(
    *,
    name: str,
    config_path: Path,
    run_log_dir: Path,
    refresh_caches: bool,
) -> ScenarioJob:
    runtime_log = run_log_dir / f"{name}.runtime.log"
    console_log = run_log_dir / f"{name}.console.log"
    command = [
        sys.executable,
        str(RUN_SCRIPT),
        "--config",
        str(config_path),
        "--log-path",
        str(runtime_log),
    ]
    if refresh_caches:
        command.append("--refresh-caches")
    return ScenarioJob(
        name=name,
        config_path=config_path,
        runtime_log=runtime_log,
        console_log=console_log,
        command=tuple(command),
    )


def _tail(path: Path, line_count: int = 20) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        return "".join(deque(stream, maxlen=line_count)).rstrip()


def _stop_active(active: dict[subprocess.Popen, tuple[ScenarioJob, object, float]]) -> None:
    for process in active:
        if process.poll() is None:
            process.terminate()
    for process, (_, console_stream, _) in active.items():
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        console_stream.close()


def _run_batch(
    jobs: list[ScenarioJob],
    *,
    max_parallel: int,
    poll_interval: float = 0.25,
) -> bool:
    pending = deque(jobs)
    active: dict[subprocess.Popen, tuple[ScenarioJob, object, float]] = {}

    try:
        while pending or active:
            while pending and len(active) < max_parallel:
                job = pending.popleft()
                job.console_log.parent.mkdir(parents=True, exist_ok=True)
                console_stream = job.console_log.open(
                    "w",
                    encoding="utf-8",
                    newline="",
                )
                try:
                    process = subprocess.Popen(
                        job.command,
                        cwd=PROJECT_ROOT,
                        stdout=console_stream,
                        stderr=subprocess.STDOUT,
                    )
                except Exception:
                    console_stream.close()
                    raise
                active[process] = (job, console_stream, time.perf_counter())
                print(
                    f"[runner] START {job.name} (pid={process.pid})",
                    flush=True,
                )

            completed = [
                process for process in active if process.poll() is not None
            ]
            if not completed:
                time.sleep(poll_interval)
                continue

            for process in completed:
                job, console_stream, started = active.pop(process)
                console_stream.close()
                elapsed = time.perf_counter() - started
                if process.returncode == 0:
                    print(
                        f"[runner] PASS  {job.name} ({elapsed / 60:.2f} min)",
                        flush=True,
                    )
                    continue

                print(
                    f"[runner] FAIL  {job.name} (exit={process.returncode}, "
                    f"{elapsed / 60:.2f} min)",
                    file=sys.stderr,
                    flush=True,
                )
                detail = _tail(job.console_log)
                if detail:
                    print(detail, file=sys.stderr, flush=True)
                _stop_active(active)
                return False
    except KeyboardInterrupt:
        print("\n[runner] Interrupted; stopping active dashboards.", file=sys.stderr)
        _stop_active(active)
        raise

    return True


def run_scenarios(args: argparse.Namespace) -> int:
    configured = (*AREA_CONFIGS, COMPARISON_CONFIG)
    missing_configs = [path for _, path in configured if not path.is_file()]
    if missing_configs:
        for path in missing_configs:
            print(f"[runner] Missing config: {path}", file=sys.stderr)
        return 2

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    run_log_dir = args.log_root.resolve() / timestamp
    area_jobs = [
        _build_job(
            name=name,
            config_path=config_path,
            run_log_dir=run_log_dir,
            refresh_caches=args.refresh_caches,
        )
        for name, config_path in AREA_CONFIGS
    ]
    comparison_job = _build_job(
        name=COMPARISON_CONFIG[0],
        config_path=COMPARISON_CONFIG[1],
        run_log_dir=run_log_dir,
        refresh_caches=args.refresh_caches,
    )

    print(
        f"[runner] Area concurrency: {min(args.max_parallel, len(area_jobs))}",
        flush=True,
    )
    print(f"[runner] Logs: {run_log_dir}", flush=True)

    if args.dry_run:
        for job in (*area_jobs, comparison_job):
            print(
                f"[runner] {job.name}: {subprocess.list2cmdline(job.command)}",
                flush=True,
            )
        return 0

    run_log_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    if not _run_batch(area_jobs, max_parallel=args.max_parallel):
        print(
            "[runner] Comparison skipped because an area dashboard failed.",
            file=sys.stderr,
        )
        return 1

    if not _run_batch([comparison_job], max_parallel=1):
        return 1

    print(
        f"[runner] All dashboards completed in "
        f"{(time.perf_counter() - started) / 60:.2f} minutes.",
        flush=True,
    )
    return 0


def main() -> None:
    raise SystemExit(run_scenarios(parse_args()))


if __name__ == "__main__":
    main()
