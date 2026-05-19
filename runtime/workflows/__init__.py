"""Runtime workflow package public API."""

from __future__ import annotations

from pathlib import Path

from activitysim_viz_logging import get_logger
from processor.models import PreparedTableName, ProcessorWorkflowResult, RunData
from processor.prepare.cache import load_prepared_run_cache, write_prepared_run_cache
from processor.prepare.enrichment.pipeline import prepare_data
from processor.prepare.reader import read_run
from processor.skimjoin.pipeline import apply_skimjoin
from runtime.config import Config
from runtime.workflows.common import (
    load_runtime_config,
    load_summary_runs_from_cache,
    prepared_cache_root,
    prune_processor_result,
    prune_summary_runs,
    resolve_run_entries as _resolve_run_entries,
    run_entries_with_keys,
    summary_cache_root,
)
from runtime.workflows.dashboard import run_dashboard_workflow
from runtime.workflows.prepare import (
    load_prepared_runs_for_dashboard as _load_prepared_runs_for_dashboard,
    run_prepare_workflow as _run_prepare_workflow,
)
from runtime.workflows.summarize import run_summary_workflow as _run_summary_workflow

LOGGER = get_logger("main")


def resolve_run_entries(
    *,
    cli_runs: list[tuple[str, str]] | None,
    cli_run_skims: list[str] | None,
    config: Config,
    require_runs: bool,
) -> list[dict]:
    """Resolve raw run inputs from CLI overrides or config."""
    return _resolve_run_entries(
        cli_runs=cli_runs,
        cli_run_skims=cli_run_skims,
        config=config,
        require_runs=require_runs,
        logger=LOGGER,
    )


def run_prepare_workflow(
    *,
    config: Config,
    prepared_root: Path | None,
    run_entries: list[dict],
    prefer_cache: bool,
    write_cache: bool,
    existing_result: ProcessorWorkflowResult | None = None,
) -> ProcessorWorkflowResult:
    """Build or reuse prepared runs for the configured entries."""
    return _run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=run_entries,
        prefer_cache=prefer_cache,
        write_cache=write_cache,
        existing_result=existing_result,
        read_run_fn=read_run,
        prepare_data_fn=prepare_data,
        apply_skimjoin_fn=apply_skimjoin,
        load_prepared_run_cache_fn=load_prepared_run_cache,
        write_prepared_run_cache_fn=write_prepared_run_cache,
    )


def load_prepared_runs_for_dashboard(
    *,
    config: Config,
    run_entries: list[dict],
    required_run_keys: list[str],
    required_prepared_tables: (
        list[PreparedTableName] | tuple[PreparedTableName, ...] | None
    ) = None,
    existing_prepared_runs_by_key: dict[str, tuple[str, RunData]] | None = None,
) -> list[tuple[str, RunData]]:
    """Load prepared runs only when enabled pages require them."""
    return _load_prepared_runs_for_dashboard(
        config=config,
        run_entries=run_entries,
        required_run_keys=required_run_keys,
        required_prepared_tables=required_prepared_tables,
        existing_prepared_runs_by_key=existing_prepared_runs_by_key,
        run_prepare_workflow_fn=run_prepare_workflow,
    )


def run_summary_workflow(
    *,
    config: Config,
    cache_root: Path,
    prepared_root: Path | None = None,
    run_entries: list[dict],
    prefer_cache: bool,
    write_cache: bool,
    prepared_prefer_cache: bool = True,
    existing_result: ProcessorWorkflowResult | None = None,
) -> ProcessorWorkflowResult:
    """Build or reuse summaries for the configured runs."""
    return _run_summary_workflow(
        config=config,
        cache_root=cache_root,
        prepared_root=prepared_root,
        run_entries=run_entries,
        prefer_cache=prefer_cache,
        write_cache=write_cache,
        prepared_prefer_cache=prepared_prefer_cache,
        existing_result=existing_result,
        run_prepare_workflow_fn=_run_prepare_workflow,
        read_run_fn=read_run,
        prepare_data_fn=prepare_data,
        apply_skimjoin_fn=apply_skimjoin,
        load_prepared_run_cache_fn=load_prepared_run_cache,
    )


__all__ = [
    "apply_skimjoin",
    "load_prepared_run_cache",
    "load_prepared_runs_for_dashboard",
    "load_runtime_config",
    "load_summary_runs_from_cache",
    "prepare_data",
    "prepared_cache_root",
    "prune_processor_result",
    "prune_summary_runs",
    "read_run",
    "resolve_run_entries",
    "run_dashboard_workflow",
    "run_entries_with_keys",
    "run_prepare_workflow",
    "run_summary_workflow",
    "summary_cache_root",
    "write_prepared_run_cache",
]
