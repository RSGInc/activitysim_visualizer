"""ActivitySim Visualizer CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from activitysim_viz_logging import configure_logging, get_logger, shutdown_logging
from dashboard.page_registry import (
    export_data_requirements,
    live_data_requirements,
)
from runtime_workflows import (
    load_runtime_config,
    load_prepared_runs_for_dashboard,
    load_summary_runs_from_cache,
    prune_processor_result,
    prune_summary_runs,
    prepared_cache_root,
    resolve_run_entries,
    run_dashboard_workflow,
    run_prepare_workflow,
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
        "--prepare",
        action="store_true",
        help="Run the prepare step and materialize prepared-table outputs.",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Run the summarize step and build or reuse summary caches.",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Run the dashboard step explicitly.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Run only the prepare step and exit.",
    )
    parser.add_argument(
        "--write-csvs",
        action="store_true",
        help="Force summary cache writes during the summarize step.",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Legacy shortcut to skip the dashboard step during default runs.",
    )
    parser.add_argument(
        "--from-csvs",
        nargs="*",
        metavar="CSV_DIR",
        help="Load pre-computed summary CSVs for a dashboard-only run.",
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


def resolve_requested_steps(args: argparse.Namespace) -> list[str]:
    """Resolve the ordered workflow steps requested on the CLI."""
    explicit_steps = args.prepare_only or args.prepare or args.summarize or args.dashboard

    if args.from_csvs is not None and args.write_csvs:
        raise ValueError("--from-csvs cannot be combined with --write-csvs.")
    if args.prepare_only and (args.prepare or args.summarize or args.dashboard):
        raise ValueError(
            "--prepare-only cannot be combined with --prepare, --summarize, or --dashboard."
        )
    if args.dashboard and args.no_dashboard:
        raise ValueError("--dashboard cannot be combined with --no-dashboard.")

    if args.prepare_only:
        steps = ["prepare"]
    elif explicit_steps:
        steps = [
            step
            for step, enabled in (
                ("prepare", args.prepare),
                ("summarize", args.summarize),
                ("dashboard", args.dashboard),
            )
            if enabled
        ]
    else:
        if args.no_dashboard and not args.write_csvs:
            raise ValueError("--no-dashboard requires --write-csvs.")
        if args.from_csvs is not None:
            steps = ["dashboard"]
        else:
            steps = ["summarize"]
            if not args.no_dashboard:
                steps.append("dashboard")

    if args.from_csvs is not None and any(
        step in {"prepare", "summarize"} for step in steps
    ):
        raise ValueError("--from-csvs only supports the dashboard step.")
    if "dashboard" in steps and "summarize" not in steps and args.from_csvs is None:
        raise ValueError("dashboard step without summarize requires --from-csvs.")
    if args.write_csvs and "summarize" not in steps:
        raise ValueError("--write-csvs requires the summarize step.")
    if args.skip_summary_cache_write and "summarize" not in steps:
        raise ValueError("--skip-summary-cache-write requires the summarize step.")

    return steps


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()
    resolved_steps: list[str] | None = None

    try:
        resolved_steps = resolve_requested_steps(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    config = load_runtime_config(args.config)
    log_path = configure_logging(config, level=logging.INFO)
    LOGGER.info("Starting ActivitySim Visualizer")
    LOGGER.info("Loading config: %s", args.config)
    LOGGER.info("Logging to %s", log_path)

    try:
        steps = resolved_steps or resolve_requested_steps(args)
        LOGGER.info("Requested workflow steps: %s", ", ".join(steps))
        cache_root = summary_cache_root(config, create="summarize" in steps)
        prepared_root = prepared_cache_root(
            config,
            create="prepare" in steps or "summarize" in steps,
        )

        run_entries = resolve_run_entries(
            cli_runs=args.cli_runs,
            cli_run_skims=args.cli_run_skims,
            config=config,
            require_runs="prepare" in steps or "summarize" in steps,
        )
        processor_result = None
        summary_runs = []
        required_run_keys: list[str] = []

        if "prepare" in steps:
            processor_result = run_prepare_workflow(
                config=config,
                prepared_root=prepared_root,
                run_entries=run_entries,
                prefer_cache=True,
                write_cache=True,
                existing_result=processor_result,
            )

        if "summarize" in steps:
            processor_result = run_summary_workflow(
                config=config,
                cache_root=cache_root,
                prepared_root=prepared_root,
                run_entries=run_entries,
                prefer_cache=not args.write_csvs,
                write_cache=args.write_csvs or not args.skip_summary_cache_write,
                existing_result=processor_result,
            )
            summary_runs = processor_result.summary_runs
            required_run_keys = list(processor_result.run_keys)
        elif args.from_csvs is not None:
            summary_runs = load_summary_runs_from_cache(
                config=config,
                cache_root=cache_root,
                explicit_cache_dirs=args.from_csvs,
                run_entries=run_entries,
            )
            required_run_keys = [summary_run.run_key for summary_run in summary_runs]

        if "dashboard" not in steps:
            LOGGER.info("Completed requested processor steps. Exiting.")
            LOGGER.info(
                "Run completed in %.2f minutes.",
                (time.perf_counter() - t0) / 60,
            )
            shutdown_logging()
            return

        prepared_runs = []
        dashboard_requirements = (
            export_data_requirements(config)
            if args.export_html
            else live_data_requirements(config)
        )
        processor_result = prune_processor_result(
            processor_result,
            required_summary_ids=dashboard_requirements.required_summary_ids,
            required_prepared_tables=dashboard_requirements.required_prepared_tables,
        )
        if processor_result is not None:
            summary_runs = list(processor_result.summary_runs)
        else:
            summary_runs = prune_summary_runs(
                summary_runs,
                dashboard_requirements.required_summary_ids,
            )

        requires_prepared_data = dashboard_requirements.prepared_data_mode != "none"
        if requires_prepared_data:
            existing_prepared_runs_by_key = (
                processor_result.prepared_runs_by_key
                if processor_result is not None
                else None
            )
            prepared_runs = load_prepared_runs_for_dashboard(
                config=config,
                run_entries=run_entries,
                required_run_keys=required_run_keys,
                required_prepared_tables=dashboard_requirements.required_prepared_tables,
                existing_prepared_runs_by_key=existing_prepared_runs_by_key,
            )
        else:
            prepared_runs = []

        run_dashboard_workflow(
            prepared_runs=prepared_runs,
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
