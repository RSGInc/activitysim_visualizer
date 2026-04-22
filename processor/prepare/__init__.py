"""Public prepare-step API for reading and enriching ActivitySim runs."""

from processor.models import RunData
from processor.prepare.cache import (
    PreparedCacheError,
    PreparedRunCacheEntry,
    build_prepared_manifest_identity,
    build_run_fingerprint,
    build_run_keys,
    discover_cache_dirs,
    load_prepared_run_cache,
    prepared_root,
    write_prepared_run_cache,
)
from processor.prepare.enrichment import (
    compute_weights,
    prepare_data,
    resolve_source_column,
)
from processor.prepare.reader import read_run, resolve_skim_path

__all__ = [
    "RunData",
    "PreparedCacheError",
    "PreparedRunCacheEntry",
    "build_prepared_manifest_identity",
    "build_run_fingerprint",
    "build_run_keys",
    "compute_weights",
    "discover_cache_dirs",
    "load_prepared_run_cache",
    "prepare_data",
    "prepared_root",
    "read_run",
    "resolve_skim_path",
    "resolve_source_column",
    "write_prepared_run_cache",
]
