"""Runtime-facing compatibility exports for shared processor/runtime contracts.

Configuration parsing still lives in ``runtime.config``, but prepared run-data
models and prepare-step helpers now live under ``processor``. This module keeps
the existing runtime import surface working while that package migration is in
progress.
"""

from runtime.config import (
    Config,
    ExportDashboardSettings,
    ExportHTMLSettings,
    ExportSelectorRequest,
)
from runtime.models import RunData


def compute_weights(*args, **kwargs):
    from processor.prepare import compute_weights as _compute_weights

    return _compute_weights(*args, **kwargs)


def prepare_data(*args, **kwargs):
    from processor.prepare import prepare_data as _prepare_data

    return _prepare_data(*args, **kwargs)


def read_run(*args, **kwargs):
    from processor.prepare import read_run as _read_run

    return _read_run(*args, **kwargs)


def resolve_skim_path(*args, **kwargs):
    from processor.prepare import resolve_skim_path as _resolve_skim_path

    return _resolve_skim_path(*args, **kwargs)

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
