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
    resolve_run_entries,
    run_entries_with_keys,
    summary_cache_root,
)
from runtime.workflows.dashboard import run_dashboard_workflow
from runtime.workflows.prepare import (
    load_prepared_runs_for_dashboard,
    run_prepare_workflow,
)
from runtime.workflows.shared import effective_processor_config
from runtime.workflows.summarize import run_summary_workflow


__all__ = [
    "apply_skimjoin",
    "effective_processor_config",
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
