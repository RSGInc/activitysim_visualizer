"""Prepared-run workflow orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from runtime.logging import get_logger
from processor.cache_identity import build_run_fingerprint, optional_file_identity
from processor.models import PreparedTableName, RunData, map_run_data_tables
from processor.prepare.availability import (
    failed_tables,
    has_usable_loaded_tables,
    unavailable_tables,
)
from processor.prepare.cache import (
    PreparedCacheError,
    build_prepared_manifest_identity,
    load_custom_prepared_tables,
    load_prepared_run_cache,
    write_prepared_run_cache,
)
from processor.prepare.enrichment.pipeline import prepare_data
from processor.prepare.reader import read_run, resolve_run_file_paths, resolve_skim_path
from processor.prepare.validation import (
    PreparedRelationshipValidationError,
    validate_prepared_relationships,
)
from processor.skimjoin.pipeline import apply_skimjoin
from runtime.config import Config, config_for_run
from runtime.workflows.common import prepared_cache_root, run_entries_with_keys
from runtime.workflows.artifacts import PreparedRunsArtifact, WorkflowPlan
from runtime.workflows import shared

LOGGER = get_logger("main")
VALIDATION_LOGGER = get_logger("processor.prepare.validation")


def prepared_cache_dir(prepared_root: Path, run_key: str) -> Path:
    """Return the prepared-cache directory for one run under the shared root."""
    return prepared_root / run_key / "prepared_tables"


def base_prepared_cache_dir(prepared_root: Path, run_key: str) -> Path:
    """Return the pre-skim preparation cache directory for one run."""
    return prepared_root / run_key / "base_prepared_tables"


def _run_cache_metadata(
    *,
    entry: dict,
    run_key: str,
    config: Config,
) -> dict[str, object]:
    """Return the stable cache metadata for one resolved run entry."""
    metadata = shared.run_cache_metadata(
        entry=entry,
        run_key=run_key,
        config=config,
        resolve_skim_path_fn=resolve_skim_path,
        resolve_run_file_paths_fn=resolve_run_file_paths,
        optional_file_identity_fn=optional_file_identity,
        build_run_fingerprint_fn=build_run_fingerprint,
        build_prepared_manifest_identity_fn=build_prepared_manifest_identity,
    )
    metadata["base_run_fingerprint"] = {
        **dict(metadata["run_fingerprint"]),
        "skimjoin": None,
    }
    return metadata


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


def _validate_prepared_run(
    run_label: str, prepared_run: RunData, config: Config
) -> None:
    """Run configured prepared-table relationship validation for one prepared run."""
    mode = str(config.prepare_relationship_checks).strip().lower()
    if mode == "off":
        return

    validation = validate_prepared_relationships(prepared_run)
    failed_checks = validation.failed_checks
    if not failed_checks:
        return

    VALIDATION_LOGGER.warning(
        'Prepared relationship validation found %d failed checks for run "%s".',
        validation.failed_check_count,
        run_label,
    )
    for check in failed_checks:
        if check.message:
            VALIDATION_LOGGER.warning("%s", check.message)

    if mode == "error":
        raise PreparedRelationshipValidationError(
            f'Prepared relationship validation failed for run "{run_label}" with '
            f"{validation.failed_check_count} failed checks."
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
    prepare_config_digest: str | None = None,
    stage: str = "prepare",
) -> tuple[str, RunData] | None:
    """Load one prepared run from cache when valid and usable."""
    try:
        prepared_run = load_prepared_run_cache(
            prepared_dir,
            config,
            expected_prepare_config_digest=(
                prepare_config_digest or config.prepare_config_digest
            ),
            expected_run_fingerprint=run_fingerprint,
            expected_label=label,
            expected_run_key=run_key,
        )
        LOGGER.info("Pipeline decision for %r / %s: REUSE", label, stage)
    except PreparedCacheError as exc:
        LOGGER.info(
            "Pipeline decision for %r / %s: REBUILD — %s", label, stage, exc
        )
        return None

    if not has_usable_loaded_tables(prepared_run):
        LOGGER.warning(
            "Skipping prepared cache for %r because no raw prepared tables are available.",
            label,
        )
        return None

    loaded = (label, prepared_run)
    _log_prepare_table_diagnostics(label, prepared_run)
    _validate_prepared_run(label, prepared_run, config)
    return loaded


def _build_prepared_run(
    *,
    entry: dict,
    config: Config,
    run_key: str,
    prepared_root: Path,
    metadata: dict[str, object],
    write_cache: bool,
    run_skimjoin: bool,
    cache_name: str = "prepared_tables",
    prepare_config_digest: str | None = None,
    run_fingerprint: dict[str, object] | None = None,
) -> tuple[str, RunData] | None:
    """Read, prepare, skimjoin, and optionally cache one run."""
    label = str(metadata["label"])
    run_dir = str(metadata["run_dir"])
    resolved_run_fingerprint = dict(
        run_fingerprint or metadata["run_fingerprint"]
    )
    prepared_table_map = entry.get("prepared_table_map") or None
    run_config = (
        config if prepared_table_map is not None else config_for_run(config, entry)
    )

    if prepared_table_map is not None:
        LOGGER.info("Loading custom prepared tables for %r", label)
        prepared_run = load_custom_prepared_tables(
            prepared_table_map=prepared_table_map,
            label=label,
            run_dir=run_dir or None,
        )
        if not has_usable_loaded_tables(prepared_run):
            LOGGER.warning(
                "Skipping run %r because no custom prepared tables were available.",
                label,
            )
            return None
        _log_prepare_table_diagnostics(label, prepared_run)
        _validate_prepared_run(label, prepared_run, run_config)
        LOGGER.info("Prepared run: %r", label)
        return (label, prepared_run)

    LOGGER.info(
        "Pipeline decision for %r / %s: REBUILD",
        label,
        "prepare" if not run_skimjoin else "skimjoin",
    )
    LOGGER.info("Reading run %r from %s", label, run_dir)
    prepared_run = read_run(
        run_dir,
        config,
        label=label,
        file_map=entry.get("file_map"),
        skim_file=metadata["skim"],
        hh_weight_col=entry.get("hh_weight_col") or None,
        person_weight_col=entry.get("person_weight_col") or None,
        trip_weight_col=entry.get("trip_weight_col") or None,
    )
    prepared_run = prepare_data(prepared_run, run_config)
    if run_skimjoin:
        prepared_run = apply_skimjoin(prepared_run, run_config)
    if not has_usable_loaded_tables(prepared_run):
        LOGGER.warning(
            "Skipping run %r because no raw prepared tables could be loaded safely.",
            label,
        )
        return None

    _log_prepare_table_diagnostics(label, prepared_run)
    _validate_prepared_run(label, prepared_run, run_config)
    LOGGER.info("Prepared run: %r", label)
    if write_cache:
        write_prepared_run_cache(
            prepared_run,
            run_config,
            run_key=run_key,
            output_root=prepared_root,
            run_fingerprint=resolved_run_fingerprint,
            file_format=config.prepare_output_file_format,
            cache_name=cache_name,
            prepare_config_digest=prepare_config_digest,
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
    prefer_base_cache: bool,
    prefer_skimjoin_cache: bool,
    write_cache: bool,
    run_skimjoin: bool,
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
    if entry.get("prepared_table_map"):
        loaded_custom_prepared_run = _build_prepared_run(
            entry=entry,
            config=config,
            run_key=run_key,
            prepared_root=prepared_root,
            metadata=metadata,
            write_cache=write_cache,
            run_skimjoin=run_skimjoin,
        )
        if loaded_custom_prepared_run is None:
            return None
        existing_prepared_runs_by_key[run_key] = loaded_custom_prepared_run
        return loaded_custom_prepared_run

    if run_skimjoin and prefer_skimjoin_cache:
        cached_prepared_run = _load_prepared_run_from_cache(
            prepared_dir=prepared_dir,
            config=config,
            run_key=run_key,
            label=label,
            run_fingerprint=run_fingerprint,
            stage="skimjoin",
        )
        if cached_prepared_run is not None:
            existing_prepared_runs_by_key[run_key] = cached_prepared_run
            return cached_prepared_run

    if not run_skimjoin and prefer_base_cache:
        cached_prepared_run = _load_prepared_run_from_cache(
            prepared_dir=prepared_dir,
            config=config,
            run_key=run_key,
            label=label,
            run_fingerprint=run_fingerprint,
        )
        if cached_prepared_run is not None:
            existing_prepared_runs_by_key[run_key] = cached_prepared_run
            return cached_prepared_run

    if run_skimjoin:
        base_fingerprint = dict(metadata["base_run_fingerprint"])
        base_dir = base_prepared_cache_dir(prepared_root, run_key)
        base_prepared_run = None
        if prefer_base_cache:
            base_prepared_run = _load_prepared_run_from_cache(
                prepared_dir=base_dir,
                config=config,
                run_key=run_key,
                label=label,
                run_fingerprint=base_fingerprint,
                prepare_config_digest=config.base_prepare_config_digest,
                stage="prepare",
            )
        if base_prepared_run is None:
            base_prepared_run = _build_prepared_run(
                entry=entry,
                config=config,
                run_key=run_key,
                prepared_root=prepared_root,
                metadata=metadata,
                write_cache=write_cache,
                run_skimjoin=False,
                cache_name="base_prepared_tables",
                prepare_config_digest=config.base_prepare_config_digest,
                run_fingerprint=base_fingerprint,
            )
        if base_prepared_run is None:
            return None

        run_config = config_for_run(config, entry)
        skimjoined_run = map_run_data_tables(base_prepared_run[1], lambda _name, frame: frame)
        LOGGER.info("Pipeline decision for %r / skimjoin: REBUILD", label)
        skimjoined_run = apply_skimjoin(skimjoined_run, run_config)
        _log_prepare_table_diagnostics(label, skimjoined_run)
        _validate_prepared_run(label, skimjoined_run, run_config)
        if write_cache:
            write_prepared_run_cache(
                skimjoined_run,
                run_config,
                run_key=run_key,
                output_root=prepared_root,
                run_fingerprint=run_fingerprint,
                file_format=config.prepare_output_file_format,
            )
            LOGGER.info("Wrote skimjoin cache for run: %r", label)
        result = (label, skimjoined_run)
        existing_prepared_runs_by_key[run_key] = result
        return result

    rebuilt_prepared_run = _build_prepared_run(
        entry=entry,
        config=config,
        run_key=run_key,
        prepared_root=prepared_root,
        metadata=metadata,
        write_cache=write_cache,
        run_skimjoin=False,
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
    existing: PreparedRunsArtifact | None = None,
    plan: WorkflowPlan | None = None,
) -> PreparedRunsArtifact:
    """Build or reuse prepared runs for the configured entries."""
    plan = plan or WorkflowPlan.from_config(config)
    config = shared.effective_processor_config(
        config,
        plan=plan,
    )
    prepared_root = prepared_root or prepared_cache_root(config, create=write_cache)
    prefer_base_cache = prefer_cache
    prefer_skimjoin_cache = prefer_cache
    if plan.refreshes("skimjoin") and not plan.refreshes("prepare"):
        prefer_base_cache = True
        prefer_skimjoin_cache = False
    if plan.refreshes("prepare"):
        prefer_base_cache = False
        prefer_skimjoin_cache = False
    (
        existing_prepared_runs_by_key,
        prepared_runs_by_key,
        run_keys,
        run_fingerprints_by_key,
    ) = shared.init_prepared_artifact(existing)
    if existing is not None:
        prepared_runs_by_key.update(existing_prepared_runs_by_key)
        run_keys = list(existing.run_keys)
        run_fingerprints_by_key.update(existing.fingerprints_by_key)

    for entry, run_key in run_entries_with_keys(run_entries):
        if shared.is_summary_table_map_only_run(entry):
            label = str(entry.get("label", run_key))
            LOGGER.info(
                "Skipping prepare for summary-table-map-only run: %r",
                label,
            )
            continue
        metadata = _run_cache_metadata(entry=entry, run_key=run_key, config=config)
        prepared_loaded = _resolve_prepared_run(
            entry=entry,
            run_key=run_key,
            config=config,
            prepared_root=prepared_root,
            existing_prepared_runs_by_key=existing_prepared_runs_by_key,
            prefer_base_cache=prefer_base_cache,
            prefer_skimjoin_cache=prefer_skimjoin_cache,
            write_cache=write_cache,
            run_skimjoin=config.skimjoin_step_enabled(),
        )
        if prepared_loaded is None:
            continue
        prepared_runs_by_key[run_key] = prepared_loaded
        if run_key not in run_keys:
            run_keys.append(run_key)
        run_fingerprints_by_key[run_key] = dict(metadata["run_fingerprint"])

    return PreparedRunsArtifact(
        runs=_ordered_prepared_runs(
            prepared_runs_by_key=prepared_runs_by_key,
            run_keys=run_keys,
        ),
        by_key=prepared_runs_by_key,
        run_keys=run_keys,
        fingerprints_by_key=run_fingerprints_by_key,
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
    prune_prepared_runs_fn: Callable[..., list[tuple[str, RunData]]] | None = None,
    plan: WorkflowPlan | None = None,
) -> list[tuple[str, RunData]]:
    """Load prepared runs only when enabled pages require them."""
    from processor.models import prune_prepared_runs as default_prune_prepared_runs

    if prune_prepared_runs_fn is None:
        prune_prepared_runs_fn = default_prune_prepared_runs

    existing_prepared_runs_by_key = dict(existing_prepared_runs_by_key or {})
    if not required_run_keys:
        return []
    required_run_keys = list(dict.fromkeys(required_run_keys))
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
    prepare_artifact = PreparedRunsArtifact(
        runs=[
            existing_prepared_runs_by_key[run_key]
            for run_key in required_run_keys
            if run_key in existing_prepared_runs_by_key
        ],
        by_key=existing_prepared_runs_by_key,
        run_keys=list(existing_prepared_runs_by_key),
    )
    prepare_artifact = run_prepare_workflow(
        config=config,
        prepared_root=prepared_cache_root(config, create=True),
        run_entries=selected_entries,
        prefer_cache=True,
        write_cache=True,
        existing=prepare_artifact,
        plan=plan,
    )
    ordered_runs = _ordered_prepared_runs(
        prepared_runs_by_key=prepare_artifact.by_key,
        run_keys=required_run_keys,
    )
    if required_prepared_tables:
        return prune_prepared_runs_fn(ordered_runs, required_prepared_tables)
    return ordered_runs
