"""Pure shared helpers for runtime workflow orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from processor.models import PreparedTableName, ProcessorWorkflowResult, RunData


def summary_cache_dirs_for_load(
    *,
    cache_root: Path,
    explicit_cache_dirs: list[str] | None,
    run_entries: list[dict] | None,
    build_run_keys_fn: Callable[[list[str]], list[str]],
    discover_cache_dirs_fn: Callable[[Path], list[Path]],
) -> tuple[list[Path], dict[str, dict]]:
    """Resolve summary cache directories and optional expected run entries."""
    explicit_dirs = [Path(path).resolve() for path in (explicit_cache_dirs or [])]
    if explicit_dirs:
        return explicit_dirs, {}

    if run_entries:
        run_keys = build_run_keys_fn(
            [
                entry.get("label", Path(entry.get("dir", "")).name or "run")
                for entry in run_entries
            ]
        )
        cache_dirs = [cache_root / run_key for run_key in run_keys]
        return cache_dirs, {
            run_key: entry for entry, run_key in zip(run_entries, run_keys)
        }

    return discover_cache_dirs_fn(cache_root), {}


def summary_cache_load_expectations(
    *,
    cache_dir: Path,
    run_entries_by_key: dict[str, dict],
    config: Any,
    build_run_fingerprint_fn: Callable[..., dict[str, object]],
    resolve_skim_path_fn: Callable[[str | None, str | None, str | Path], str | None],
    build_prepared_manifest_identity_fn: Callable[..., dict[str, object]],
) -> dict[str, object] | None:
    """Return cache-load expectations for a cache dir when raw run inputs exist."""
    entry = run_entries_by_key.get(cache_dir.name)
    if entry is None:
        return None

    run_dir = entry.get("dir", "")
    expected_label = entry.get("label", Path(run_dir).name)
    expected_run_key = cache_dir.name
    expected_run_fingerprint = build_run_fingerprint_fn(
        label=expected_label,
        run_dir=run_dir,
        skim_file=resolve_skim_path_fn(
            entry.get("skim_file") or None,
            config.skim_file,
            run_dir,
        ),
        hh_weight_col=entry.get("hh_weight_col") or None,
        person_weight_col=entry.get("person_weight_col") or None,
        trip_weight_col=entry.get("trip_weight_col") or None,
    )
    return {
        "expected_label": expected_label,
        "expected_run_key": expected_run_key,
        "expected_run_fingerprint": expected_run_fingerprint,
        "expected_prepared_manifest_identity": build_prepared_manifest_identity_fn(
            run_key=expected_run_key,
            config=config,
            run_fingerprint=expected_run_fingerprint,
        ),
    }


def run_entries_with_keys(
    run_entries: list[dict],
    *,
    build_run_keys_fn: Callable[[list[str]], list[str]],
) -> list[tuple[dict, str]]:
    """Return each resolved run entry paired with its stable summary cache key."""
    run_labels = [
        entry.get("label", Path(entry.get("dir", "")).name or "run")
        for entry in run_entries
    ]
    run_keys = build_run_keys_fn(run_labels)
    return list(zip(run_entries, run_keys))


def prune_summary_runs(
    summary_runs: list[Any],
    required_summary_ids: list[str] | tuple[str, ...],
    *,
    create_summary_run_fn: Callable[..., Any],
) -> list[Any]:
    """Return summary runs containing only the summary ids needed downstream."""
    if not summary_runs:
        return []

    required_ids = set(required_summary_ids)
    return [
        create_summary_run_fn(
            label=summary_run.label,
            run_key=summary_run.run_key,
            summaries_by_mode={
                mode: {
                    summary_id: table
                    for summary_id, table in mode_tables.items()
                    if summary_id in required_ids
                }
                for mode, mode_tables in summary_run.summaries_by_mode.items()
            },
            summary_metadata_by_mode={
                mode: {
                    summary_id: metadata
                    for summary_id, metadata in summary_run.summary_metadata_by_mode.get(
                        mode, {}
                    ).items()
                    if summary_id in required_ids
                }
                for mode in summary_run.summaries_by_mode
            },
            segment_id=getattr(summary_run, "segment_id", "full"),
            segment_label=getattr(summary_run, "segment_label", "Full"),
            is_full_segment=getattr(summary_run, "is_full_segment", True),
            segment_source_type=getattr(summary_run, "segment_source_type", None),
            segment_column=getattr(summary_run, "segment_column", None),
            segment_values=getattr(summary_run, "segment_values", ()),
            segment_source_table=getattr(summary_run, "segment_source_table", None),
            segment_source_key_column=getattr(
                summary_run, "segment_source_key_column", None
            ),
            segment_csv_file=getattr(summary_run, "segment_csv_file", None),
            segment_csv_key_column=getattr(summary_run, "segment_csv_key_column", None),
            segment_csv_value_column=getattr(
                summary_run, "segment_csv_value_column", None
            ),
            source_run_dir=summary_run.source_run_dir,
            manifest=summary_run.manifest,
        )
        for summary_run in summary_runs
    ]


def prune_processor_result(
    result: ProcessorWorkflowResult | None,
    *,
    required_summary_ids: list[str] | tuple[str, ...],
    required_prepared_tables: list[PreparedTableName] | tuple[PreparedTableName, ...],
    prune_prepared_runs_fn: Callable[[list[tuple[str, RunData]], list[PreparedTableName] | tuple[PreparedTableName, ...]], list[tuple[str, RunData]]],
    prune_summary_runs_fn: Callable[[list[Any], list[str] | tuple[str, ...]], list[Any]],
) -> ProcessorWorkflowResult | None:
    """Return a processor result trimmed to the next dashboard/export step."""
    if result is None:
        return None

    pruned_prepared_runs_by_key = {
        run_key: (
            label,
            prune_prepared_runs_fn([(label, prepared_run)], required_prepared_tables)[0][
                1
            ],
        )
        for run_key, (label, prepared_run) in result.prepared_runs_by_key.items()
    }
    ordered_prepared_runs = ordered_prepared_runs_by_key(
        prepared_runs_by_key=pruned_prepared_runs_by_key,
        run_keys=result.run_keys,
    )
    return ProcessorWorkflowResult(
        summary_runs=prune_summary_runs_fn(result.summary_runs, required_summary_ids),
        prepared_runs=ordered_prepared_runs,
        prepared_runs_by_key=pruned_prepared_runs_by_key,
        run_keys=list(result.run_keys),
        run_fingerprints_by_key=dict(result.run_fingerprints_by_key),
    )


def run_cache_metadata(
    *,
    entry: dict,
    run_key: str,
    config: Any,
    resolve_skim_path_fn: Callable[[str | None, str | None, str | Path], str | None],
    build_run_fingerprint_fn: Callable[..., dict[str, object]],
    build_prepared_manifest_identity_fn: Callable[..., dict[str, object]],
) -> dict[str, object]:
    """Return the stable cache metadata for one resolved run entry."""
    run_dir = entry.get("dir", "")
    label = entry.get("label", Path(run_dir).name)
    skim = entry.get("skim_file") or None
    resolved_skim = resolve_skim_path_fn(skim, config.skim_file, run_dir)
    run_fingerprint = build_run_fingerprint_fn(
        label=label,
        run_dir=run_dir,
        skim_file=resolved_skim,
        hh_weight_col=entry.get("hh_weight_col") or None,
        person_weight_col=entry.get("person_weight_col") or None,
        trip_weight_col=entry.get("trip_weight_col") or None,
    )
    return {
        "label": label,
        "run_dir": run_dir,
        "skim": skim,
        "run_fingerprint": run_fingerprint,
        "prepared_manifest_identity": build_prepared_manifest_identity_fn(
            run_key=run_key,
            config=config,
            run_fingerprint=run_fingerprint,
        ),
    }


def init_processor_result(
    existing_result: ProcessorWorkflowResult | None,
) -> tuple[
    dict[str, tuple[str, RunData]],
    dict[str, tuple[str, RunData]],
    list[str],
    dict[str, dict[str, object]],
]:
    """Initialize shared workflow collections from an existing processor result."""
    existing_prepared_runs_by_key = dict(
        (existing_result.prepared_runs_by_key if existing_result else {}) or {}
    )
    return existing_prepared_runs_by_key, {}, [], {}


def ordered_prepared_runs_by_key(
    *,
    prepared_runs_by_key: dict[str, tuple[str, RunData]],
    run_keys: list[str],
) -> list[tuple[str, RunData]]:
    """Return prepared runs ordered by workflow run key sequence."""
    return [
        prepared_runs_by_key[run_key]
        for run_key in run_keys
        if run_key in prepared_runs_by_key
    ]

