"""ActivitySim Visualizer CLI entry point."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

from runtime.logging import configure_logging, get_logger, shutdown_logging
from dashboard.page_registry import (
    export_data_requirements,
    live_data_requirements,
)
import runtime.workflows as runtime_workflows
from runtime.workflows import WorkflowPlan

LOGGER = get_logger("main")
_EXPORT_HTML_USE_CONFIG_SENTINEL = "__USE_CONFIG_OR_DEFAULT_EXPORT_HTML__"


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
    parser.add_argument(
        "--explain-cache",
        action="store_true",
        help="Print cache decisions for the configured pipeline and exit without running it.",
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
    if args.dashboard:
        return "live"
    return str(config.pipeline.dashboard_mode).lower()


def resolve_effective_plan(args: argparse.Namespace, config) -> WorkflowPlan:
    """Resolve logical steps, runtime steps, dashboard mode, and refresh policy."""
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
    refresh_steps = set(config.pipeline.refresh)
    if args.refresh_caches:
        refresh_steps.update(
            step
            for step in logical_steps
            if step in {"prepare", "skimjoin", "summarize"}
        )
    if args.refresh_prepared_cache:
        refresh_steps.add("prepare")
    if args.refresh_summary_cache:
        refresh_steps.add("summarize")

    runtime_steps = tuple(collapse_runtime_steps(logical_steps))
    return WorkflowPlan(
        logical_steps=tuple(logical_steps),
        runtime_steps=runtime_steps,
        dashboard_mode=dashboard_mode,
        refresh_steps=tuple(
            step
            for step in ("prepare", "skimjoin", "summarize")
            if step in refresh_steps
        ),
    )


def _remove_run_cache_dirs(
    *,
    root: Path,
    run_keys: list[str],
    cache_label: str,
    preserve_names: set[str] | None = None,
) -> None:
    """Remove per-run cache directories before a forced rebuild."""
    for run_key in run_keys:
        cache_dir = root / run_key
        if cache_dir.exists():
            LOGGER.info("Refreshing %s cache for run key %r", cache_label, run_key)
            if not preserve_names:
                shutil.rmtree(cache_dir)
                continue
            for child in cache_dir.iterdir():
                if child.name in preserve_names:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()


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
            preserve_names={"prepared_tables", "base_prepared_tables"},
        )
    return refresh_prepared, refresh_summary


def resolve_cache_preferences(
    *,
    plan: WorkflowPlan,
    refreshed_prepared: bool,
    refreshed_summary: bool,
) -> tuple[bool, bool]:
    """Resolve cache reuse preferences after config defaults and CLI refresh overrides."""
    prefer_prepared_cache = not any(
        plan.refreshes(step) for step in ("prepare", "skimjoin")
    )
    prefer_summary_cache = not any(
        plan.refreshes(step) for step in ("prepare", "skimjoin", "summarize")
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


def explain_cache_plan(
    *,
    config,
    plan: WorkflowPlan,
    prepared_root: Path,
    cache_root: Path,
    run_entries: list[dict],
) -> None:
    """Print cache decisions without loading tables or writing artifacts."""
    from processor.prepare.cache import PreparedCacheError, inspect_prepared_run_cache
    from processor.summarize import builder as summary_builder
    from processor.summarize import cache as summary_cache
    from processor.summarize.cache_types import SummaryCacheError
    from runtime.workflows import prepare as prepare_workflow
    from runtime.workflows import summarize as summarize_workflow

    effective = runtime_workflows.effective_processor_config(config, plan=plan)

    def decision(action: str, reason: str | None = None) -> str:
        return action if not reason else f"{action} — {reason}"

    for entry, run_key in runtime_workflows.run_entries_with_keys(run_entries):
        prepare_metadata = prepare_workflow._run_cache_metadata(
            entry=entry,
            run_key=run_key,
            config=effective,
        )
        label = str(prepare_metadata["label"])
        print(f"Pipeline plan — {label}")

        prepare_action = "DISABLED"
        prepare_reason = None
        if "prepare" in plan.runtime_steps or "summarize" in plan.runtime_steps:
            if plan.refreshes("prepare"):
                prepare_action = "REBUILD"
                prepare_reason = "explicitly refreshed"
            else:
                base_cache = (
                    prepare_workflow.base_prepared_cache_dir(prepared_root, run_key)
                    if plan.includes("skimjoin")
                    else prepare_workflow.prepared_cache_dir(prepared_root, run_key)
                )
                base_digest = (
                    effective.base_prepare_config_digest
                    if plan.includes("skimjoin")
                    else effective.prepare_config_digest
                )
                base_fingerprint = dict(
                    prepare_metadata[
                        "base_run_fingerprint"
                        if plan.includes("skimjoin")
                        else "run_fingerprint"
                    ]
                )
                try:
                    inspect_prepared_run_cache(
                        base_cache,
                        expected_prepare_config_digest=base_digest,
                        expected_run_fingerprint=base_fingerprint,
                        expected_label=label,
                        expected_run_key=run_key,
                    )
                    prepare_action = "REUSE"
                except PreparedCacheError as exc:
                    prepare_action = "REBUILD"
                    prepare_reason = str(exc)
        print(f"  prepare    {decision(prepare_action, prepare_reason)}")

        if plan.includes("skimjoin"):
            if plan.refreshes("skimjoin"):
                skimjoin_action = decision("REBUILD", "explicitly refreshed")
            elif prepare_action == "REBUILD":
                skimjoin_action = decision("REBUILD", "upstream prepare will change")
            else:
                try:
                    inspect_prepared_run_cache(
                        prepare_workflow.prepared_cache_dir(prepared_root, run_key),
                        expected_prepare_config_digest=effective.prepare_config_digest,
                        expected_run_fingerprint=dict(prepare_metadata["run_fingerprint"]),
                        expected_label=label,
                        expected_run_key=run_key,
                    )
                    skimjoin_action = "REUSE"
                except PreparedCacheError as exc:
                    skimjoin_action = decision("REBUILD", str(exc))
            print(f"  skimjoin   {skimjoin_action}")
        else:
            print("  skimjoin   DISABLED")

        if "summarize" in plan.runtime_steps:
            if any(plan.refreshes(step) for step in ("prepare", "skimjoin", "summarize")):
                summary_action = decision("REBUILD", "explicit or upstream refresh")
            elif prepare_action == "REBUILD":
                summary_action = decision("REBUILD", "upstream prepare will change")
            else:
                summary_metadata = summarize_workflow._run_cache_metadata(
                    entry=entry,
                    run_key=run_key,
                    config=effective,
                )
                try:
                    inspection = summary_cache.inspect_summary_run_bundle(
                        cache_root / run_key,
                        effective,
                        expected_modes=effective.weighting_modes,
                        expected_summary_ids=list(summary_builder.DEFAULT_SUMMARY_IDS),
                        expected_run_fingerprint=dict(summary_metadata["run_fingerprint"]),
                        expected_prepared_manifest_identity=summary_metadata[
                            "prepared_manifest_identity"
                        ],
                        expected_label=label,
                        expected_run_key=run_key,
                    )
                    stale_count = sum(
                        len(summary_ids)
                        for summary_ids in dict(
                            inspection["stale_summary_ids_by_unit"]
                        ).values()
                    )
                    obsolete_count = len(inspection["obsolete_unit_keys"])
                    summary_action = (
                        decision(
                            "REBUILD",
                            (
                                f"{stale_count} analysis-unit summary tables are stale; "
                                f"{obsolete_count} analysis units are obsolete"
                            ),
                        )
                        if stale_count or obsolete_count
                        else "REUSE"
                    )
                except SummaryCacheError as exc:
                    summary_action = decision("REBUILD", str(exc))
            print(f"  summarize  {summary_action}")
        else:
            print("  summarize  DISABLED")

        print(
            "  dashboard  "
            + ("RUN" if "dashboard" in plan.runtime_steps else "DISABLED")
        )


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()

    try:
        _validate_cli_step_flags(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    config = runtime_workflows.load_runtime_config(args.config)
    if not args.explain_cache:
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
            config, create="summarize" in steps and not args.explain_cache
        )
        prepared_root = runtime_workflows.prepared_cache_root(
            config,
            create=("prepare" in steps or "summarize" in steps)
            and not args.explain_cache,
        )

        run_entries = runtime_workflows.resolve_run_entries(
            cli_runs=args.cli_runs,
            cli_run_skims=args.cli_run_skims,
            config=config,
            require_runs="prepare" in steps or "summarize" in steps,
        )
        if args.explain_cache:
            explain_cache_plan(
                config=config,
                plan=plan,
                prepared_root=prepared_root,
                cache_root=cache_root,
                run_entries=run_entries,
            )
            return
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
            plan=plan,
        )
        dashboard_execution_mode = (
            resolve_dashboard_execution_mode(plan.dashboard_mode)
            if "dashboard" in steps
            else "none"
        )
        export_html_path = _resolve_export_html_path(
            args.export_html,
            config,
            dashboard_mode=dashboard_execution_mode,
        )
        dashboard_requirements = (
            (
                export_data_requirements(config)
                if export_html_path is not None
                else live_data_requirements(config)
            )
            if "dashboard" in steps
            else None
        )
        prepared_artifact = None
        summary_artifact = None
        summary_runs = []
        required_run_keys: list[str] = []

        if "prepare" in steps:
            prepared_artifact = runtime_workflows.run_prepare_workflow(
                config=config,
                prepared_root=prepared_root,
                run_entries=run_entries,
                prefer_cache=prefer_prepared_cache,
                write_cache=True,
                existing=prepared_artifact,
                plan=plan,
            )

        if "summarize" in steps:
            summary_artifact = runtime_workflows.run_summary_workflow(
                config=config,
                cache_root=cache_root,
                prepared_root=prepared_root,
                run_entries=run_entries,
                prefer_cache=prefer_summary_cache and not args.write_csvs,
                prepared_prefer_cache=prefer_prepared_cache,
                write_cache=args.write_csvs or not args.skip_summary_cache_write,
                prepared=prepared_artifact,
                plan=plan,
            )
            summary_runs = summary_artifact.runs
            required_run_keys = list(summary_artifact.prepared.run_keys)
        elif "dashboard" in steps:
            assert dashboard_requirements is not None
            summary_runs = runtime_workflows.load_summary_runs_from_cache(
                config=effective_processor_config,
                cache_root=cache_root,
                explicit_cache_dirs=args.from_csvs,
                run_entries=run_entries,
                required_summary_ids=dashboard_requirements.required_summary_ids,
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

        assert dashboard_requirements is not None
        prepared_runs = []
        summary_artifact = runtime_workflows.prune_summary_artifact(
            summary_artifact,
            required_summary_ids=dashboard_requirements.summary_ids_for_pruning,
            required_prepared_tables=dashboard_requirements.required_prepared_tables,
        )
        if summary_artifact is not None:
            summary_runs = list(summary_artifact.runs)
        else:
            summary_runs = runtime_workflows.prune_summary_runs(
                summary_runs,
                dashboard_requirements.summary_ids_for_pruning,
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
                summary_artifact.prepared.by_key
                if summary_artifact is not None
                else None
            )
            prepared_runs = runtime_workflows.load_prepared_runs_for_dashboard(
                config=effective_processor_config,
                run_entries=run_entries,
                required_run_keys=required_run_keys,
                required_prepared_tables=dashboard_requirements.required_prepared_tables,
                existing_prepared_runs_by_key=existing_prepared_runs_by_key,
                plan=plan,
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
