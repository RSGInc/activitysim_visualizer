"""Pure shared helpers for runtime workflow orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from processor.models import PreparedTableName, RunData
from runtime.config import Config
from runtime.config.signatures import digest_payload
from runtime.workflows.artifacts import (
    PreparedRunsArtifact,
    SummaryRunsArtifact,
    WorkflowPlan,
)


def summary_run_fingerprint(
    run_fingerprint: dict[str, object],
    entry: dict,
) -> dict[str, object]:
    """Return the run fingerprint used specifically by summary caches."""
    from processor.summarize.external import summary_table_map_identity

    fingerprint = dict(run_fingerprint)
    summary_identity = summary_table_map_identity(entry.get("summary_table_map") or None)
    if summary_identity is not None:
        fingerprint["summary_table_map_identity"] = summary_identity
    return fingerprint


def is_summary_table_map_only_run(entry: dict) -> bool:
    """Return whether a run entry only contributes user-supplied summary tables."""
    return bool(entry.get("summary_table_map")) and not (
        entry.get("dir") or entry.get("prepared_table_map")
    )


def effective_processor_config(
    config: Config,
    *,
    plan: WorkflowPlan,
) -> Config:
    """Return a runtime-effective config for processor/cache identity decisions."""
    effective = config
    skimjoin_enabled = effective.skimjoin_step_enabled()
    run_skimjoin = plan.includes("skimjoin")
    if skimjoin_enabled != run_skimjoin:
        if run_skimjoin:
            raise ValueError(
                "Cannot force integrated skimjoin on when the loaded config has it disabled."
            )
        effective = replace(
            effective,
            pipeline=replace(
                effective.pipeline,
                steps=tuple(
                    step for step in effective.pipeline.steps if step != "skimjoin"
                ),
            ),
            skimjoin=replace(
                effective.skimjoin,
                enabled=False,
                config_digest=None,
                normalized_config=None,
                resolved_skim_files=(),
                resolved_network_los_file=None,
            ),
        )
    run_segmentation = plan.includes("segment")
    if bool(effective.segmentation.enabled) != run_segmentation:
        if run_segmentation:
            raise ValueError(
                "Cannot force segmentation on when the loaded config has it disabled."
            )
        effective = replace(
            effective,
            segmentation=replace(
                effective.segmentation,
                enabled=False,
            ),
        )
    if effective is config:
        return config
    effective.prepare_config_digest = digest_payload(effective.prepare_signature_payload())
    effective.summary_config_digest = digest_payload(effective.summary_signature_payload())
    return effective


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
    uses_custom_prepared_tables = bool(entry.get("prepared_table_map"))
    uses_summary_table_map_only = is_summary_table_map_only_run(entry)
    expected_skimjoin = None
    if not (uses_custom_prepared_tables or uses_summary_table_map_only):
        from runtime.config import resolve_run_skimjoin_settings

        resolved_skimjoin = resolve_run_skimjoin_settings(config, entry)
        if resolved_skimjoin.enabled:
            expected_skimjoin = {
                "enabled": True,
                "config_path": resolved_skimjoin.config_path,
                "config_digest": resolved_skimjoin.config_digest,
                "resolved_skim_files": list(resolved_skimjoin.resolved_skim_files),
                "resolved_network_los_file": resolved_skimjoin.resolved_network_los_file,
            }
    base_run_fingerprint = build_run_fingerprint_fn(
        label=expected_label,
        run_dir=(
            None
            if (uses_custom_prepared_tables or uses_summary_table_map_only)
            else run_dir
        ),
        skim_file=(
            None
            if (uses_custom_prepared_tables or uses_summary_table_map_only)
            else resolve_skim_path_fn(
                entry.get("skim_file") or None,
                config.skim_file,
                run_dir,
            )
        ),
        file_map=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("file_map") or None,
        fallback_file_map=(
            None
            if (uses_custom_prepared_tables or uses_summary_table_map_only)
            else config.fallback_files or None
        ),
        skimjoin=expected_skimjoin,
        hh_weight_col=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("hh_weight_col") or None,
        person_weight_col=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("person_weight_col") or None,
        trip_weight_col=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("trip_weight_col") or None,
    )
    expected_run_fingerprint = summary_run_fingerprint(
        base_run_fingerprint,
        entry,
    )
    expected_prepared_manifest_identity = None
    if not uses_summary_table_map_only:
        expected_prepared_manifest_identity = build_prepared_manifest_identity_fn(
            run_key=expected_run_key,
            config=config,
            run_fingerprint=base_run_fingerprint,
            source_type=(
                "custom_prepared_table_map"
                if uses_custom_prepared_tables
                else "prepared_cache"
            ),
            prepared_table_map=entry.get("prepared_table_map") or None,
        )
    return {
        "expected_label": expected_label,
        "expected_run_key": expected_run_key,
        "expected_run_fingerprint": expected_run_fingerprint,
        "expected_prepared_manifest_identity": expected_prepared_manifest_identity,
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
            segmentation_type=getattr(summary_run, "segmentation_type", "full"),
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


def prune_summary_artifact(
    artifact: SummaryRunsArtifact | None,
    *,
    required_summary_ids: list[str] | tuple[str, ...],
    required_prepared_tables: list[PreparedTableName] | tuple[PreparedTableName, ...],
    prune_prepared_runs_fn: Callable[[list[tuple[str, RunData]], list[PreparedTableName] | tuple[PreparedTableName, ...]], list[tuple[str, RunData]]],
    prune_summary_runs_fn: Callable[[list[Any], list[str] | tuple[str, ...]], list[Any]],
) -> SummaryRunsArtifact | None:
    """Return summary/prepared artifacts trimmed for dashboard or export."""
    if artifact is None:
        return None

    pruned_prepared_runs_by_key = {
        run_key: (
            label,
            prune_prepared_runs_fn([(label, prepared_run)], required_prepared_tables)[0][
                1
            ],
        )
        for run_key, (label, prepared_run) in artifact.prepared.by_key.items()
    }
    ordered_prepared_runs = ordered_prepared_runs_by_key(
        prepared_runs_by_key=pruned_prepared_runs_by_key,
        run_keys=artifact.prepared.run_keys,
    )
    return SummaryRunsArtifact(
        runs=prune_summary_runs_fn(artifact.runs, required_summary_ids),
        prepared=PreparedRunsArtifact(
            runs=ordered_prepared_runs,
            by_key=pruned_prepared_runs_by_key,
            run_keys=list(artifact.prepared.run_keys),
            fingerprints_by_key=dict(artifact.prepared.fingerprints_by_key),
        ),
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
    uses_custom_prepared_tables = bool(entry.get("prepared_table_map"))
    uses_summary_table_map_only = is_summary_table_map_only_run(entry)
    resolved_skimjoin_payload = None
    if not (uses_custom_prepared_tables or uses_summary_table_map_only):
        from runtime.config import resolve_run_skimjoin_settings

        resolved_skimjoin = resolve_run_skimjoin_settings(config, entry)
        if resolved_skimjoin.enabled:
            resolved_skimjoin_payload = {
                "enabled": True,
                "config_path": resolved_skimjoin.config_path,
                "config_digest": resolved_skimjoin.config_digest,
                "resolved_skim_files": list(resolved_skimjoin.resolved_skim_files),
                "resolved_network_los_file": resolved_skimjoin.resolved_network_los_file,
            }
    resolved_skim = (
        None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else resolve_skim_path_fn(skim, config.skim_file, run_dir)
    )
    run_fingerprint = build_run_fingerprint_fn(
        label=label,
        run_dir=(
            None
            if (uses_custom_prepared_tables or uses_summary_table_map_only)
            else run_dir
        ),
        skim_file=resolved_skim,
        skimjoin=resolved_skimjoin_payload,
        file_map=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("file_map") or None,
        fallback_file_map=(
            None
            if (uses_custom_prepared_tables or uses_summary_table_map_only)
            else config.fallback_files or None
        ),
        hh_weight_col=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("hh_weight_col") or None,
        person_weight_col=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("person_weight_col") or None,
        trip_weight_col=None
        if (uses_custom_prepared_tables or uses_summary_table_map_only)
        else entry.get("trip_weight_col") or None,
    )
    prepared_manifest_identity = None
    if not uses_summary_table_map_only:
        prepared_manifest_identity = build_prepared_manifest_identity_fn(
            run_key=run_key,
            config=config,
            run_fingerprint=run_fingerprint,
            source_type=(
                "custom_prepared_table_map"
                if uses_custom_prepared_tables
                else "prepared_cache"
            ),
            prepared_table_map=entry.get("prepared_table_map") or None,
        )
    return {
        "label": label,
        "run_dir": run_dir,
        "skim": skim,
        "run_fingerprint": run_fingerprint,
        "prepared_manifest_identity": prepared_manifest_identity,
    }


def init_prepared_artifact(
    existing: PreparedRunsArtifact | None,
) -> tuple[
    dict[str, tuple[str, RunData]],
    dict[str, tuple[str, RunData]],
    list[str],
    dict[str, dict[str, object]],
]:
    """Initialize workflow collections from an existing prepared artifact."""
    existing_prepared_runs_by_key = dict(
        (existing.by_key if existing else {}) or {}
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

