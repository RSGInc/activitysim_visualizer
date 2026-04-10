"""Shared runtime contracts and data-loading helpers.

This package is intentionally separate from both ``summarize`` and ``dashboard``.
It owns the cross-cutting runtime concerns that both subsystems depend on:
configuration parsing, shared data models, and raw ActivitySim run loading and
preparation.
"""

from runtime.config import (
    Config,
    ExportDashboardSettings,
    ExportHTMLSettings,
    ExportSelectorRequest,
)
from runtime.models import RunData
from runtime.run_data import compute_weights, prepare_data, read_run, resolve_skim_path

__all__ = [
    "Config",
    "ExportDashboardSettings",
    "ExportHTMLSettings",
    "ExportSelectorRequest",
    "RunData",
    "compute_weights",
    "prepare_data",
    "read_run",
    "resolve_skim_path",
]
