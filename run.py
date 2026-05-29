"""ActivitySim Visualizer CLI entry point."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import shutil
import sys
import time
from pathlib import Path

from activitysim_viz_logging import configure_logging, get_logger, shutdown_logging
from dashboard.page_registry import (
    export_data_requirements,
    live_data_requirements,
)
import runtime.workflows as runtime_workflows

LOGGER = get_logger("main")
_EXPORT_HTML_USE_CONFIG_SENTINEL = "__USE_CONFIG_OR_DEFAULT_EXPORT_HTML__"


@dataclass(frozen=True)
class EffectiveWorkflowPlan:
    """Resolved runtime workflow intent after merging CLI and config defaults."""

    logical_steps: tuple[str, ...]
    runtime_steps: tuple[str, ...]
    dashboard_mode: str
    overwrite: bool


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
        "--refresh-caches",
        action="store_true",
        help="Refresh both prepared and summary caches for the selected runs before rebuilding.",
    )
    parser.add_argument(
        "--refresh-prepared-cache",
        action="store_true",
        help="Refresh prepared caches for the selected runs before rebuilding.",
    )
    parser.add_argument(
        "--refresh-summary-cache",
        action="store_true",
        help="Refresh summary caches for the selected runs before rebuilding.",
    )
    parser.add_argument(
        "--export-html",
        nargs="?",
        const=_EXPORT_HTML_USE_CONFIG_SENTINEL,
        metavar="PATH",
        help=(
            "Export dashboard to a self-contained HTML file and exit. "
            "If PATH is omitted, use the config output_path or the default root-based export path."
        ),
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


def _validate_cli_step_flags(args: argparse.Namespace) -> None:
    """Validate CLI flag combinations before merging with config defaults."""
    if args.from_csvs is not None and args.write_csvs:
        raise ValueError("--from-csvs cannot be combined with --write-csvs.")
    if args.prepare_only and (args.prepare or args.summarize or args.dashboard):
        raise ValueError(
            "--prepare-only cannot be combined with --prepare, --summarize, or --dashboard."
        )
    if args.dashboard and args.no_dashboard:
        raise ValueError("--dashboard cannot be combined with --no-dashboard.")


def _config_default_logical_steps(config) -> list[str]:
    """Return logical config pipeline steps in user-configured order."""
    return list(config.pipeline.steps)

def collapse_runtime_steps(logical_steps: list[str] | tuple[str, ...]) -> list[str]:
    """Collapse logical pipeline steps into current runtime workflow boundaries."""
    runtime_steps: list[str] = []
    if any(step in logical_steps for step in ("prepare", "skimjoin")):
        runtime_steps.append("prepare")
    if any(step in logical_steps for step in ("summarize", "segment")):
        runtime_steps.append("summarize")
    if "dashboard" in logical_steps:
        runtime_steps.append("dashboard")
    return runtime_steps


def resolve_requested_steps(args: argparse.Namespace, config) -> list[str]:
    """Resolve the ordered logical workflow steps requested by CLI or config defaults."""
    _validate_cli_step_flags(args)
    explicit_steps = (
        args.prepare_only or args.prepare or args.summarize or args.dashboard
    )

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
        if args.from_csvs is not None:
            steps = ["dashboard"]
        else:
            steps = _config_default_logical_steps(config)
            if args.no_dashboard:
                steps = [step for step in steps if step != "dashboard"]

    if args.from_csvs is not None and any(
        step in {"prepare", "summarize"} for step in steps
    ):
        raise ValueError("--from-csvs only supports the dashboard step.")
    if args.write_csvs and "summarize" not in steps:
        raise ValueError("--write-csvs requires the summarize step.")
    if args.skip_summary_cache_write and "summarize" not in steps:
        raise ValueError("--skip-summary-cache-write requires the summarize step.")
    if (
        args.refresh_summary_cache or args.refresh_caches
    ) and "summarize" not in steps:
        raise ValueError(
            "--refresh-summary-cache and --refresh-caches require the summarize step."
        )
    if (
        args.refresh_prepared_cache or args.refresh_caches
    ) and not any(step in {"prepare", "summarize"} for step in steps):
        raise ValueError(
            "--refresh-prepared-cache and --refresh-caches require the prepare or summarize step."
        )
    if not steps:
        raise ValueError("no workflow steps were selected after applying CLI/config settings.")

    return steps


def resolve_effective_dashboard_mode(
    args: argparse.Namespace,
    config,
    *,
    steps: list[str] | tuple[str, ...],
) -> str:
    """Resolve the dashboard execution mode after applying CLI precedence."""
    if "dashboard" not in steps:
        return "none"
    if args.export_html is not None:
        return "export"
    if args.no_dashboard:
        return "none"
    if args.dashboard:
        return "live"
    return str(config.pipeline.dashboard_mode).lower()


def resolve_effective_plan(args: argparse.Namespace, config) -> EffectiveWorkflowPlan:
    """Resolve logical steps, runtime steps, dashboard mode, and overwrite policy."""
    logical_steps = resolve_requested_steps(args, config)
    dashboard_mode = resolve_effective_dashboard_mode(
        args,
        config,
        steps=logical_steps,
    )
    if dashboard_mode == "none":
        logical_steps = [
            step for step in logical_steps if step != "dashboard"
        ]
    overwrite = bool(config.pipeline.overwrite)
    if args.refresh_caches or args.refresh_prepared_cache or args.refresh_summary_cache:
        overwrite = True

    runtime_steps = tuple(collapse_runtime_steps(logical_steps))
    return EffectiveWorkflowPlan(
        logical_steps=tuple(logical_steps),
        runtime_steps=runtime_steps,
        dashboard_mode=dashboard_mode,
        overwrite=overwrite,
    )


def _remove_run_cache_dirs(
    *,
    root: Path,
    run_keys: list[str],
    cache_label: str,
) -> None:
    """Remove per-run cache directories before a forced rebuild."""
    for run_key in run_keys:
        cache_dir = root / run_key
        if cache_dir.exists():
            LOGGER.info("Refreshing %s cache for run key %r", cache_label, run_key)
            shutil.rmtree(cache_dir)


def _refresh_requested_caches(
    *,
    args: argparse.Namespace,
    prepared_root: Path,
    cache_root: Path,
    run_entries: list[dict],
) -> tuple[bool, bool]:
    """Delete targeted cache directories and return cache reuse preferences."""
    refresh_prepared = bool(args.refresh_caches or args.refresh_prepared_cache)
    refresh_summary = bool(args.refresh_caches or args.refresh_summary_cache)
    if not refresh_prepared and not refresh_summary:
        return False, False

    run_keys = [
        run_key for _, run_key in runtime_workflows.run_entries_with_keys(run_entries)
    ]
    if refresh_prepared:
        _remove_run_cache_dirs(
            root=prepared_root,
            run_keys=run_keys,
            cache_label="prepared",
        )
    if refresh_summary:
        _remove_run_cache_dirs(
            root=cache_root,
            run_keys=run_keys,
            cache_label="summary",
        )
    return refresh_prepared, refresh_summary


def resolve_cache_preferences(
    *,
    plan: EffectiveWorkflowPlan,
    refreshed_prepared: bool,
    refreshed_summary: bool,
) -> tuple[bool, bool]:
    """Resolve cache reuse preferences after config defaults and CLI refresh overrides."""
    prefer_prepared_cache = not (
        "prepare" in plan.runtime_steps and plan.overwrite
    )
    prefer_summary_cache = not (
        "summarize" in plan.runtime_steps and plan.overwrite
    )
    if refreshed_prepared:
        prefer_prepared_cache = False
    if refreshed_summary:
        prefer_summary_cache = False
    return prefer_prepared_cache, prefer_summary_cache


def _resolve_terminal_log_level(config) -> int:
    return getattr(logging, str(config.log_level).upper(), logging.INFO)


def _resolve_export_html_path(
    export_html_arg: str | None,
    config,
    *,
    dashboard_mode: str,
) -> str | None:
    if dashboard_mode != "export":
        return None
    if export_html_arg != _EXPORT_HTML_USE_CONFIG_SENTINEL:
        if export_html_arg is not None:
            return export_html_arg
    if config.export_html.output_path:
        return config.export_html.output_path
    return str(Path(config.summary_root) / "exported_dashboard.html")


def resolve_dashboard_execution_mode(dashboard_mode: str) -> str:
    """Map validated dashboard modes to an executable runtime behavior."""
    normalized_mode = str(dashboard_mode).lower()
    if normalized_mode == "host":
        LOGGER.warning(
            "pipeline.dashboard_mode 'host' is not implemented yet; using live mode."
        )
        return "live"
    return normalized_mode


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()

    try:
        _validate_cli_step_flags(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    config = runtime_workflows.load_runtime_config(args.config)
    log_path = configure_logging(config, level=_resolve_terminal_log_level(config))
    LOGGER.info("Starting ActivitySim Visualizer")
    LOGGER.info("Loading config: %s", args.config)
    LOGGER.info("Logging to %s", log_path)

    try:
        plan = resolve_effective_plan(args, config)
        steps = list(plan.runtime_steps)
        LOGGER.info("Requested workflow steps: %s", ", ".join(steps) if steps else "(none)")
        LOGGER.info("Effective dashboard mode: %s", plan.dashboard_mode)
        cache_root = runtime_workflows.summary_cache_root(
            config, create="summarize" in steps
        )
        prepared_root = runtime_workflows.prepared_cache_root(
            config,
            create="prepare" in steps or "summarize" in steps,
        )

        run_entries = runtime_workflows.resolve_run_entries(
            cli_runs=args.cli_runs,
            cli_run_skims=args.cli_run_skims,
            config=config,
            require_runs="prepare" in steps or "summarize" in steps,
        )
        refreshed_prepared, refreshed_summary = _refresh_requested_caches(
            args=args,
            prepared_root=prepared_root,
            cache_root=cache_root,
            run_entries=run_entries,
        )
        prefer_prepared_cache, prefer_summary_cache = resolve_cache_preferences(
            plan=plan,
            refreshed_prepared=refreshed_prepared,
            refreshed_summary=refreshed_summary,
        )
        effective_processor_config = runtime_workflows.effective_processor_config(
            config,
            apply_skimjoin="skimjoin" in plan.logical_steps,
            apply_segmentation="segment" in plan.logical_steps,
        )
        processor_result = None
        summary_runs = []
        required_run_keys: list[str] = []

        if "prepare" in steps:
            processor_result = runtime_workflows.run_prepare_workflow(
                config=config,
                prepared_root=prepared_root,
                run_entries=run_entries,
                prefer_cache=prefer_prepared_cache,
                write_cache=True,
                existing_result=processor_result,
                apply_skimjoin="skimjoin" in plan.logical_steps,
            )

        if "summarize" in steps:
            processor_result = runtime_workflows.run_summary_workflow(
                config=config,
                cache_root=cache_root,
                prepared_root=prepared_root,
                run_entries=run_entries,
                prefer_cache=prefer_summary_cache and not args.write_csvs,
                prepared_prefer_cache=prefer_prepared_cache,
                write_cache=args.write_csvs or not args.skip_summary_cache_write,
                existing_result=processor_result,
                apply_skimjoin="skimjoin" in plan.logical_steps,
                apply_segmentation="segment" in plan.logical_steps,
            )
            summary_runs = processor_result.summary_runs
            required_run_keys = list(processor_result.run_keys)
        elif "dashboard" in steps:
            summary_runs = runtime_workflows.load_summary_runs_from_cache(
                config=effective_processor_config,
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

        dashboard_execution_mode = resolve_dashboard_execution_mode(
            plan.dashboard_mode
        )
        export_html_path = _resolve_export_html_path(
            args.export_html,
            config,
            dashboard_mode=dashboard_execution_mode,
        )
        prepared_runs = []
        dashboard_requirements = (
            export_data_requirements(config)
            if export_html_path is not None
            else live_data_requirements(config)
        )
        processor_result = runtime_workflows.prune_processor_result(
            processor_result,
            required_summary_ids=dashboard_requirements.required_summary_ids,
            required_prepared_tables=dashboard_requirements.required_prepared_tables,
        )
        if processor_result is not None:
            summary_runs = list(processor_result.summary_runs)
        else:
            summary_runs = runtime_workflows.prune_summary_runs(
                summary_runs,
                dashboard_requirements.required_summary_ids,
            )

        requires_prepared_data = dashboard_requirements.prepared_data_mode != "none"
        if (
            requires_prepared_data
            and args.from_csvs is not None
            and export_html_path is not None
        ):
            prepared_runs = []
        elif requires_prepared_data:
            existing_prepared_runs_by_key = (
                processor_result.prepared_runs_by_key
                if processor_result is not None
                else None
            )
            prepared_runs = runtime_workflows.load_prepared_runs_for_dashboard(
                config=effective_processor_config,
                run_entries=run_entries,
                required_run_keys=required_run_keys,
                required_prepared_tables=dashboard_requirements.required_prepared_tables,
                existing_prepared_runs_by_key=existing_prepared_runs_by_key,
                apply_skimjoin="skimjoin" in plan.logical_steps,
            )
        else:
            prepared_runs = []

        runtime_workflows.run_dashboard_workflow(
            prepared_runs=prepared_runs,
            summary_runs=summary_runs,
            config=config,
            export_html_path=export_html_path,
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
