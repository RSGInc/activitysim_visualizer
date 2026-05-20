"""Prepared-run workflow orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from activitysim_viz_logging import get_logger
from processor.cache_identity import build_run_fingerprint
from processor.models import PreparedTableName, ProcessorWorkflowResult, RunData
from processor.prepare.availability import (
    failed_tables,
    has_usable_loaded_tables,
    unavailable_tables,
)
from processor.prepare.cache import (
    PreparedCacheError,
    build_prepared_manifest_identity,
    load_prepared_run_cache,
    write_prepared_run_cache,
)
from processor.prepare.enrichment.pipeline import prepare_data
from processor.prepare.reader import read_run, resolve_skim_path
from processor.skimjoin.pipeline import apply_skimjoin
from runtime.config import Config
from runtime.workflows.common import prepared_cache_root, run_entries_with_keys
from runtime.workflows import shared

LOGGER = get_logger("main")


def prepared_cache_dir(prepared_root: Path, run_key: str) -> Path:
    """Return the prepared-cache directory for one run under the shared root."""
    return prepared_root / run_key / "prepared_tables"


def _run_cache_metadata(
    *,
    entry: dict,
    run_key: str,
    config: Config,
) -> dict[str, object]:
    """Return the stable cache metadata for one resolved run entry."""
    return shared.run_cache_metadata(
        entry=entry,
        run_key=run_key,
        config=config,
        resolve_skim_path_fn=resolve_skim_path,
        build_run_fingerprint_fn=build_run_fingerprint,
        build_prepared_manifest_identity_fn=build_prepared_manifest_identity,
    )


def _log_prepare_table_diagnostics(run_label: str, prepared_run: RunData) -> None:
    """Log unavailable or failed prepared tables for one run."""
    missing_tables = unavailable_tables(prepared_run)
    failed_prepare_tables = failed_tables(prepared_run)
    if missing_tables:
        LOGGER.warning(
            "Prepared run %r skipped unavailable tables: %s",
            run_label,
            "; ".join(
                f"{table_id} ({reason})"
                for table_id, reason in sorted(missing_tables.items())
            ),
        )
    if failed_prepare_tables:
        LOGGER.warning(
            "Prepared run %r recorded failed tables: %s",
            run_label,
            "; ".join(
                f"{table_id} ({reason})"
                for table_id, reason in sorted(failed_prepare_tables.items())
            ),
        )


def _existing_prepared_run(
    *,
    run_key: str,
    existing_prepared_runs_by_key: dict[str, tuple[str, RunData]],
) -> tuple[str, RunData] | None:
    """Return a reusable in-memory prepared run when available and usable."""
    cached_prepared_run = existing_prepared_runs_by_key.get(run_key)
    if cached_prepared_run is None:
        return None
    if not has_usable_loaded_tables(cached_prepared_run[1]):
        LOGGER.warning(
            "Skipping prepared run %r because no raw prepared tables are available.",
            cached_prepared_run[0],
        )
        return None

    LOGGER.info("Reusing in-memory prepared run for %r", cached_prepared_run[0])
    _log_prepare_table_diagnostics(cached_prepared_run[0], cached_prepared_run[1])
    return cached_prepared_run


def _load_prepared_run_from_cache(
    *,
    prepared_dir: Path,
    config: Config,
    run_key: str,
    label: str,
    run_fingerprint: dict[str, object],
    load_prepared_run_cache_fn: Callable[..., RunData] = load_prepared_run_cache,
) -> tuple[str, RunData] | None:
    """Load one prepared run from cache when valid and usable."""
    try:
        prepared_run = load_prepared_run_cache_fn(
            prepared_dir,
            config,
            expected_prepare_config_digest=config.prepare_config_digest,
            expected_run_fingerprint=run_fingerprint,
            expected_label=label,
            expected_run_key=run_key,
        )
        LOGGER.info("Loaded prepared cache for run: %r", label)
    except PreparedCacheError as exc:
        LOGGER.info("Prepared cache miss for %r: %s", label, exc)
        return None

    if not has_usable_loaded_tables(prepared_run):
        LOGGER.warning(
            "Skipping prepared cache for %r because no raw prepared tables are available.",
            label,
        )
        return None

    loaded = (label, prepared_run)
    _log_prepare_table_diagnostics(label, prepared_run)
    return loaded


def _build_prepared_run(
    *,
    entry: dict,
    config: Config,
    run_key: str,
    prepared_root: Path,
    metadata: dict[str, object],
    write_cache: bool,
    read_run_fn: Callable[..., RunData] = read_run,
    prepare_data_fn: Callable[[RunData, Config], RunData] = prepare_data,
    apply_skimjoin_fn: Callable[[RunData, Config], RunData] = apply_skimjoin,
    write_prepared_run_cache_fn: Callable[..., Path] = write_prepared_run_cache,
) -> tuple[str, RunData] | None:
    """Read, prepare, skimjoin, and optionally cache one run."""
    label = str(metadata["label"])
    run_dir = str(metadata["run_dir"])
    run_fingerprint = dict(metadata["run_fingerprint"])

    LOGGER.info("Reading run %r from %s", label, run_dir)
    prepared_run = read_run_fn(
        run_dir,
        config,
        label=label,
        file_map=entry.get("file_map"),
        skim_file=metadata["skim"],
        hh_weight_col=entry.get("hh_weight_col") or None,
        person_weight_col=entry.get("person_weight_col") or None,
        trip_weight_col=entry.get("trip_weight_col") or None,
    )
    prepared_run = prepare_data_fn(prepared_run, config)
    prepared_run = apply_skimjoin_fn(prepared_run, config)
    if not has_usable_loaded_tables(prepared_run):
        LOGGER.warning(
            "Skipping run %r because no raw prepared tables could be loaded safely.",
            label,
        )
        return None

    _log_prepare_table_diagnostics(label, prepared_run)
    LOGGER.info("Prepared run: %r", label)
    if write_cache:
        write_prepared_run_cache_fn(
            prepared_run,
            config,
            run_key=run_key,
            output_root=prepared_root,
            run_fingerprint=run_fingerprint,
        )
        LOGGER.info("Wrote prepared cache for run: %r", label)
    else:
        LOGGER.info("Skipped prepared cache write for run: %r", label)
    return (label, prepared_run)


def _resolve_prepared_run(
    *,
    entry: dict,
    run_key: str,
    config: Config,
    prepared_root: Path,
    existing_prepared_runs_by_key: dict[str, tuple[str, RunData]],
    prefer_cache: bool,
    write_cache: bool,
    read_run_fn: Callable[..., RunData] = read_run,
    prepare_data_fn: Callable[[RunData, Config], RunData] = prepare_data,
    apply_skimjoin_fn: Callable[[RunData, Config], RunData] = apply_skimjoin,
    load_prepared_run_cache_fn: Callable[..., RunData] = load_prepared_run_cache,
    write_prepared_run_cache_fn: Callable[..., Path] = write_prepared_run_cache,
) -> tuple[str, RunData] | None:
    """Reuse in-memory prepared runs, then prepared cache, then raw-run rebuilds."""
    existing_prepared_run = _existing_prepared_run(
        run_key=run_key,
        existing_prepared_runs_by_key=existing_prepared_runs_by_key,
    )
    if existing_prepared_run is not None:
        return existing_prepared_run

    metadata = _run_cache_metadata(entry=entry, run_key=run_key, config=config)
    label = str(metadata["label"])
    run_fingerprint = dict(metadata["run_fingerprint"])
    prepared_dir = prepared_cache_dir(prepared_root, run_key)

    if prefer_cache:
        cached_prepared_run = _load_prepared_run_from_cache(
            prepared_dir=prepared_dir,
            config=config,
            run_key=run_key,
            label=label,
            run_fingerprint=run_fingerprint,
            load_prepared_run_cache_fn=load_prepared_run_cache_fn,
        )
        if cached_prepared_run is not None:
            existing_prepared_runs_by_key[run_key] = cached_prepared_run
            return cached_prepared_run

    rebuilt_prepared_run = _build_prepared_run(
        entry=entry,
        config=config,
        run_key=run_key,
        prepared_root=prepared_root,
        metadata=metadata,
        write_cache=write_cache,
        read_run_fn=read_run_fn,
        prepare_data_fn=prepare_data_fn,
        apply_skimjoin_fn=apply_skimjoin_fn,
        write_prepared_run_cache_fn=write_prepared_run_cache_fn,
    )
    if rebuilt_prepared_run is None:
        return None
    existing_prepared_runs_by_key[run_key] = rebuilt_prepared_run
    return rebuilt_prepared_run


def _ordered_prepared_runs(
    *,
    prepared_runs_by_key: dict[str, tuple[str, RunData]],
    run_keys: list[str],
) -> list[tuple[str, RunData]]:
    """Return prepared runs ordered by workflow run key sequence."""
    return shared.ordered_prepared_runs_by_key(
        prepared_runs_by_key=prepared_runs_by_key,
        run_keys=run_keys,
    )


def run_prepare_workflow(
    *,
    config: Config,
    prepared_root: Path | None,
    run_entries: list[dict],
    prefer_cache: bool,
    write_cache: bool,
    existing_result: ProcessorWorkflowResult | None = None,
    read_run_fn: Callable[..., RunData] = read_run,
    prepare_data_fn: Callable[[RunData, Config], RunData] = prepare_data,
    apply_skimjoin_fn: Callable[[RunData, Config], RunData] = apply_skimjoin,
    load_prepared_run_cache_fn: Callable[..., RunData] = load_prepared_run_cache,
    write_prepared_run_cache_fn: Callable[..., Path] = write_prepared_run_cache,
) -> ProcessorWorkflowResult:
    """Build or reuse prepared runs for the configured entries."""
    prepared_root = prepared_root or prepared_cache_root(config, create=write_cache)
    (
        existing_prepared_runs_by_key,
        prepared_runs_by_key,
        run_keys,
        run_fingerprints_by_key,
    ) = shared.init_processor_result(existing_result)

    for entry, run_key in run_entries_with_keys(run_entries):
        metadata = _run_cache_metadata(entry=entry, run_key=run_key, config=config)
        prepared_loaded = _resolve_prepared_run(
            entry=entry,
            run_key=run_key,
            config=config,
            prepared_root=prepared_root,
            existing_prepared_runs_by_key=existing_prepared_runs_by_key,
            prefer_cache=prefer_cache,
            write_cache=write_cache,
            read_run_fn=read_run_fn,
            prepare_data_fn=prepare_data_fn,
            apply_skimjoin_fn=apply_skimjoin_fn,
            load_prepared_run_cache_fn=load_prepared_run_cache_fn,
            write_prepared_run_cache_fn=write_prepared_run_cache_fn,
        )
        if prepared_loaded is None:
            continue
        prepared_runs_by_key[run_key] = prepared_loaded
        run_keys.append(run_key)
        run_fingerprints_by_key[run_key] = dict(metadata["run_fingerprint"])

    return ProcessorWorkflowResult(
        summary_runs=list(existing_result.summary_runs) if existing_result else [],
        prepared_runs=_ordered_prepared_runs(
            prepared_runs_by_key=prepared_runs_by_key,
            run_keys=run_keys,
        ),
        prepared_runs_by_key=prepared_runs_by_key,
        run_keys=run_keys,
        run_fingerprints_by_key=run_fingerprints_by_key,
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
    run_prepare_workflow_fn: Callable[..., ProcessorWorkflowResult] = run_prepare_workflow,
    prune_prepared_runs_fn: Callable[..., list[tuple[str, RunData]]] | None = None,
) -> list[tuple[str, RunData]]:
    """Load prepared runs only when enabled pages require them."""
    from processor.models import prune_prepared_runs as default_prune_prepared_runs

    if prune_prepared_runs_fn is None:
        prune_prepared_runs_fn = default_prune_prepared_runs

    existing_prepared_runs_by_key = dict(existing_prepared_runs_by_key or {})
    if not required_run_keys:
        return []
    if not run_entries:
        LOGGER.warning(
            "Enabled dashboard pages require prepared run data, but no raw run inputs are available to build it."
        )
        return []

    entries_by_key = {
        run_key: entry for entry, run_key in run_entries_with_keys(run_entries)
    }
    missing_run_keys = [
        run_key for run_key in required_run_keys if run_key not in entries_by_key
    ]
    if missing_run_keys:
        LOGGER.warning(
            "Enabled dashboard pages require prepared run data, but raw inputs could not be resolved "
            "for summary runs: %s",
            ", ".join(repr(run_key) for run_key in missing_run_keys),
        )
        return []

    selected_entries = [entries_by_key[run_key] for run_key in required_run_keys]
    prepare_result = ProcessorWorkflowResult(
        prepared_runs=[
            existing_prepared_runs_by_key[run_key]
            for run_key in required_run_keys
            if run_key in existing_prepared_runs_by_key
        ],
        prepared_runs_by_key=existing_prepared_runs_by_key,
        run_keys=list(existing_prepared_runs_by_key),
    )
    prepare_result = run_prepare_workflow_fn(
        config=config,
        prepared_root=prepared_cache_root(config, create=True),
        run_entries=selected_entries,
        prefer_cache=True,
        write_cache=True,
        existing_result=prepare_result,
    )
    ordered_runs = _ordered_prepared_runs(
        prepared_runs_by_key=prepare_result.prepared_runs_by_key,
        run_keys=required_run_keys,
    )
    if required_prepared_tables:
        return prune_prepared_runs_fn(ordered_runs, required_prepared_tables)
    return ordered_runs
