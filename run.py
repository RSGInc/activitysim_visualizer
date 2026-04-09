"""ActivitySim Visualizer CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from activitysim_viz_logging import configure_logging, get_logger, shutdown_logging
from runtime_workflows import (
    load_runtime_config,
    load_summary_runs_from_cache,
    resolve_run_entries,
    run_dashboard_workflow,
    run_summary_workflow,
    summary_cache_root,
)

LOGGER = get_logger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="activitysim-viz",
        description="Panel-based ActivitySim comparison visualizer",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=str(Path(__file__).parent / "config.yaml"),
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
        help="Refresh and write summary CSV caches to the configured summary root",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip the dashboard (only write CSVs; requires --write-csvs)",
    )
    parser.add_argument(
        "--from-csvs",
        nargs="*",
        metavar="CSV_DIR",
        help="Load pre-computed summary CSVs from directories instead of raw run outputs",
    )
    parser.add_argument(
        "--skip-summary-cache-write",
        action="store_true",
        help="Do not write missing or stale summary caches during normal runs",
    )
    parser.add_argument(
        "--export-html",
        metavar="PATH",
        help="Export dashboard to a self-contained HTML file and exit",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5006,
        help="Port to serve the dashboard on (default: 5006)",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open the dashboard in a browser automatically",
    )
    return parser.parse_args()


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()

    if args.no_dashboard and not args.write_csvs:
        print("Error: --no-dashboard requires --write-csvs.", file=sys.stderr)
        sys.exit(1)
    if args.from_csvs is not None and args.write_csvs:
        print(
            "Error: --from-csvs cannot be combined with --write-csvs.", file=sys.stderr
        )
        sys.exit(1)

    config = load_runtime_config(args.config)
    log_path = configure_logging(config, level=logging.INFO)
    LOGGER.info("Starting ActivitySim Visualizer")
    LOGGER.info("Loading config: %s", args.config)
    LOGGER.info("Logging to %s", log_path)
    cache_root = summary_cache_root(config, create=args.from_csvs is None)

    try:
        if args.from_csvs is not None:
            run_entries = resolve_run_entries(
                cli_runs=args.cli_runs,
                cli_run_skims=args.cli_run_skims,
                config=config,
                require_runs=False,
            )
            summary_runs = load_summary_runs_from_cache(
                config=config,
                cache_root=cache_root,
                explicit_cache_dirs=args.from_csvs,
                run_entries=run_entries,
            )
            raw_runs = []
        else:
            run_entries = resolve_run_entries(
                cli_runs=args.cli_runs,
                cli_run_skims=args.cli_run_skims,
                config=config,
                require_runs=True,
            )
            summary_result = run_summary_workflow(
                config=config,
                cache_root=cache_root,
                run_entries=run_entries,
                prefer_cache=not args.write_csvs,
                write_cache=args.write_csvs or not args.skip_summary_cache_write,
            )
            summary_runs = summary_result.summary_runs
            raw_runs = summary_result.raw_runs

        if args.no_dashboard:
            LOGGER.info("Done writing CSVs. Exiting.")
            LOGGER.info(
                "Run completed in %.2f minutes.",
                (time.perf_counter() - t0) / 60,
            )
            shutdown_logging()
            return

        run_dashboard_workflow(
            raw_runs=raw_runs,
            summary_runs=summary_runs,
            config=config,
            export_html_path=args.export_html,
            port=args.port,
            show=not args.no_show,
        )
    except ValueError as exc:
        LOGGER.error("Fatal runtime error: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        shutdown_logging()
        sys.exit(1)

    elapsed = (time.perf_counter() - t0) / 60
    LOGGER.info("Dashboard created in %.2f minutes.", elapsed)
    shutdown_logging()


if __name__ == "__main__":
    main()
