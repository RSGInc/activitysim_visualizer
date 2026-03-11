"""ActivitySim Visualizer Marimo Alt CLI entry point.

Usage examples:
  # Use runs defined in config.yaml
  python run.py --config config.yaml

  # Override/add runs on the command line (repeatable)
  python run.py --run /path/to/run1 "Base" --run /path/to/run2 "Build"

  # Per-run skim override
  python run.py --run /path/to/run1 "Base" --run-skim /path/to/run1/skims.omx

  # Dashboard + write calibration CSVs
  python run.py --write-csvs

  # Write CSVs only (no dashboard)
  python run.py --write-csvs --no-dashboard

  # Export HTML
  python run.py --export-html output.html
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from viz import load_and_prepare_runs, write_prepared_run_summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="activitysim-viz-marimo",
        description="Marimo-based ActivitySim comparison visualizer",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=str(Path(__file__).resolve().parent / "config.yaml"),
        help="Path to config.yaml (default: config.yaml next to run.py)",
    )
    parser.add_argument(
        "--run",
        nargs=2,
        action="append",
        metavar=("DIR", "LABEL"),
        dest="cli_runs",
        help="Add a run: --run /path/to/dir 'My Label' (repeatable; overrides config runs)",
    )
    parser.add_argument(
        "--run-skim",
        nargs="+",
        metavar="SKIM_PATH",
        dest="cli_run_skims",
        help="Skim file for each --run entry (in order); use '' or 'null' for global default",
    )
    parser.add_argument(
        "--write-csvs",
        action="store_true",
        help="Write summary CSVs to each run's output directory",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip the dashboard and only write CSVs; requires --write-csvs",
    )
    parser.add_argument(
        "--from-csvs",
        nargs="*",
        metavar="CSV_DIR",
        help="Reserved for loading pre-computed summary CSVs instead of raw outputs",
    )
    parser.add_argument(
        "--export-html",
        metavar="PATH",
        help="Export the marimo app to HTML and exit",
    )
    parser.add_argument(
        "--include-code",
        action="store_true",
        help="Include notebook code in exported HTML output",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5006,
        help="Port to serve the dashboard on (default: 5006)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the dashboard server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Do not open the dashboard in a browser automatically",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the app file for changes and reload automatically",
    )
    return parser.parse_args()


def _load_raw_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _normalize_cli_skim(value: str | None) -> str | None:
    if value in (None, "", "null", "None"):
        return None
    return value


def _resolve_run_entries(raw_config: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.cli_run_skims and not args.cli_runs:
        raise ValueError("--run-skim requires at least one --run entry.")

    if args.cli_runs:
        cli_skims = args.cli_run_skims or []
        if len(cli_skims) > len(args.cli_runs):
            raise ValueError("More --run-skim entries were provided than --run entries.")
        run_entries: list[dict[str, Any]] = []
        for idx, (run_dir, label) in enumerate(args.cli_runs):
            run_entries.append(
                {
                    "dir": run_dir,
                    "label": label,
                    "skim_file": _normalize_cli_skim(cli_skims[idx] if idx < len(cli_skims) else None),
                }
            )
        return run_entries

    run_entries = raw_config.get("runs", [])
    if not run_entries:
        raise ValueError("No runs specified. Add runs to config.yaml or use --run DIR LABEL.")
    return run_entries


def _write_effective_config(
    base_config_path: Path,
    raw_config: dict[str, Any],
    run_entries: list[dict[str, Any]],
    temp_dir: Path,
) -> Path:
    effective = dict(raw_config)
    effective["runs"] = run_entries
    output_path = temp_dir / "effective_config.yaml"
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(effective, handle, sort_keys=False)
    return output_path


def _marimo_base_command() -> list[str]:
    return [sys.executable, "-m", "marimo"]


def _run_marimo_dashboard(app_path: Path, config_path: Path, args: argparse.Namespace) -> None:
    command = _marimo_base_command() + [
        "run",
        str(app_path),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.headless:
        command.append("--headless")
    if args.watch:
        command.append("--watch")
    command.extend(["--", "--config", str(config_path)])
    subprocess.run(command, check=True)


def _export_marimo_html(app_path: Path, config_path: Path, output_path: Path, include_code: bool) -> None:
    command = _marimo_base_command() + [
        "export",
        "html",
        str(app_path),
        "-o",
        str(output_path),
        "-f",
    ]
    command.append("--include-code" if include_code else "--no-include-code")
    command.extend(["--", "--config", str(config_path)])
    subprocess.run(command, check=True)


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()

    if args.no_dashboard and not args.write_csvs:
        raise SystemExit("Error: --no-dashboard requires --write-csvs.")
    if args.from_csvs:
        raise SystemExit("Error: --from-csvs is not implemented for the marimo alt.")

    root = Path(__file__).resolve().parent
    base_config_path = Path(args.config).expanduser().resolve()
    app_path = root / "app.py"

    raw_config = _load_raw_config(base_config_path)
    run_entries = _resolve_run_entries(raw_config, args)

    print("[main] Starting ActivitySim Visualizer Marimo Alt")
    print(f"[main] Base config: {base_config_path}")

    temp_root = root / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)

    temp_dir = temp_root / f"activitysim_viz_marimo_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        effective_config_path = _write_effective_config(base_config_path, raw_config, run_entries, temp_dir)
        print(f"[main] Effective config: {effective_config_path}")

        if args.write_csvs:
            print("[main] Loading runs for CSV export")
            prepared_runs = load_and_prepare_runs(effective_config_path)
            written_dirs = write_prepared_run_summaries(prepared_runs)
            for out_dir in written_dirs:
                print(f"[main] Wrote summaries: {out_dir}")

        if args.no_dashboard:
            print("Done writing CSVs. Exiting.")
            print(f"[main] Run completed in {(time.perf_counter() - t0) / 60:.2f} minutes.")
            return

        if args.export_html:
            export_path = Path(args.export_html).expanduser().resolve()
            print(f"[main] Exporting dashboard HTML to {export_path}")
            _export_marimo_html(app_path, effective_config_path, export_path, include_code=args.include_code)
            print("Done.")
            print(f"[main] Run completed in {(time.perf_counter() - t0) / 60:.2f} minutes.")
            return

        print("[main] Launching marimo dashboard")
        _run_marimo_dashboard(app_path, effective_config_path, args)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
