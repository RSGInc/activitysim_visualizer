"""Summary workflow orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from runtime.logging import get_logger
from processor.analysis_units import AnalysisUnit
from processor.models import ProcessorWorkflowResult, RunData


from processor.segmentation import build_analysis_units_for_run

from processor.summarize import cache as summary_cache
from processor.summarize.external import (
    load_summary_table_map,
    merge_summary_table_map_run,
)
from runtime.config import Config
from runtime.workflows.common import prepared_cache_root, run_entries_with_keys
from runtime.workflows.prepare import run_prepare_workflow
from runtime.workflows import shared

LOGGER = get_logger("main")


def _run_cache_metadata(
    *, entry: dict, run_key: str, config: Config
) -> dict[str, object]:
    """Return the stable cache metadata for one resolved run entry."""
    from runtime.workflows.prepare import (
        _run_cache_metadata as prepare_run_cache_metadata,
    )

    metadata = dict(
        prepare_run_cache_metadata(entry=entry, run_key=run_key, config=config)
    )
    metadata["run_fingerprint"] = shared.summary_run_fingerprint(
        dict(metadata["run_fingerprint"]),
        entry,
    )
    return metadata


def _load_summary_run_from_cache(
    *,
    cache_dir: Path,
    config: Config,
    label: str,
    run_key: str,
    run_fingerprint: dict[str, object],
    prepared_manifest_identity: dict[str, object],
) -> Any | None:
    """Load one summary run from cache when valid."""
    try:
        inspection = summary_cache.inspect_summary_run_bundle(
            cache_dir,
            config,
            expected_modes=config.weighting_modes,
            expected_summary_ids=summary_cache.requested_summary_ids(config),
            expected_summary_config_digest=config.summary_config_digest,
            expected_run_fingerprint=run_fingerprint,
            expected_prepared_manifest_identity=prepared_manifest_identity,
            expected_label=label,
            expected_run_key=run_key,
        )
        reusable_summary_ids = list(inspection["reusable_summary_ids"])
        stale_summary_ids = list(inspection["stale_summary_ids"])
        cached_runs = (
            summary_cache.load_summary_run_bundle(
                cache_dir,
                config,
                expected_modes=config.weighting_modes,
                expected_summary_ids=reusable_summary_ids,
                expected_summary_config_digest=config.summary_config_digest,
                expected_run_fingerprint=run_fingerprint,
                expected_prepared_manifest_identity=prepared_manifest_identity,
                expected_label=label,
                expected_run_key=run_key,
            )
            if reusable_summary_ids
            else []
        )
        LOGGER.info(
            "Loaded reusable summary cache tables for run %r: %s",
            label,
            ", ".join(reusable_summary_ids) if reusable_summary_ids else "(none)",
        )
        return {
            "summary_runs": cached_runs,
            "reusable_summary_ids": reusable_summary_ids,
            "stale_summary_ids": stale_summary_ids,
        }
    except summary_cache.SummaryCacheError as exc:
        LOGGER.info("Cache miss for %r: %s", label, exc)
        return None


def _build_summary_tables_for_run(
    *,
    prepared_run: RunData,
    config: Config,
    summary_ids: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, object]]]]:
    """Build summary tables and metadata for one prepared run."""
    requested_summary_ids = summary_cache.requested_summary_ids(config)
    if summary_ids is None or list(summary_ids) == requested_summary_ids:
        return summary_cache.build_mode_summaries_with_metadata(prepared_run, config)
    return summary_cache.build_mode_summaries_with_metadata(
        prepared_run,
        config,
        summary_ids=summary_ids,
    )


def _build_summary_run_from_analysis_unit(
    *,
    unit: AnalysisUnit,
    config: Config,
) -> Any:
    """Build one summary run wrapper from an already prepared analysis unit."""
    summaries_by_mode, summary_metadata_by_mode = _build_summary_tables_for_run(
        prepared_run=unit.prepared_run,
        config=config,
    )
    return summary_cache.create_summary_run(
        label=unit.run_name,
        run_key=unit.run_key,
        summaries_by_mode=summaries_by_mode,
        summary_metadata_by_mode=summary_metadata_by_mode,
        segmentation_type=unit.segmentation_type,
        segment_id=unit.segment_id,
        segment_label=unit.segment_label,
        is_full_segment=unit.is_full,
        segment_source_type=unit.segment_metadata.source_type,
        segment_column=unit.segment_metadata.column,
        segment_values=unit.segment_metadata.values,
        segment_source_table=unit.segment_metadata.source_table,
        segment_source_key_column=unit.segment_metadata.source_key_column,
        segment_csv_file=unit.segment_metadata.csv_file,
        segment_csv_key_column=unit.segment_metadata.csv_key_column,
        segment_csv_value_column=unit.segment_metadata.csv_segment_value_column,
        source_run_dir=str(unit.prepared_run.run_dir),
    )


def _merge_summary_runs(
    *,
    cached_runs: list[Any],
    rebuilt_runs: list[Any],
) -> list[Any]:
    if not cached_runs:
        return rebuilt_runs
    cached_by_segment = {
        (run.segmentation_type, run.segment_id): run for run in cached_runs
    }
    rebuilt_by_segment = {
        (run.segmentation_type, run.segment_id): run for run in rebuilt_runs
    }
    merged: list[Any] = []
    for segment_key in rebuilt_by_segment:
        rebuilt = rebuilt_by_segment[segment_key]
        cached = cached_by_segment.get(segment_key)
        if cached is None:
            merged.append(rebuilt)
            continue
        summaries_by_mode: dict[str, dict[str, Any]] = {}
        metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
        for mode, rebuilt_tables in rebuilt.summaries_by_mode.items():
            cached_tables = cached.summaries_by_mode.get(mode, {})
            cached_metadata = cached.summary_metadata_by_mode.get(mode, {})
            summaries_by_mode[mode] = {**cached_tables, **rebuilt_tables}
            metadata_by_mode[mode] = {
                **cached_metadata,
                **rebuilt.summary_metadata_by_mode.get(mode, {}),
            }
        merged.append(
            summary_cache.create_summary_run(
                label=rebuilt.label,
                run_key=rebuilt.run_key,
                summaries_by_mode=summaries_by_mode,
                summary_metadata_by_mode=metadata_by_mode,
                segmentation_type=rebuilt.segmentation_type,
                segment_id=rebuilt.segment_id,
                segment_label=rebuilt.segment_label,
                is_full_segment=rebuilt.is_full_segment,
                segment_source_type=rebuilt.segment_source_type,
                segment_column=rebuilt.segment_column,
                segment_values=rebuilt.segment_values,
                segment_source_table=rebuilt.segment_source_table,
                segment_source_key_column=rebuilt.segment_source_key_column,
                segment_csv_file=rebuilt.segment_csv_file,
                segment_csv_key_column=rebuilt.segment_csv_key_column,
                segment_csv_value_column=rebuilt.segment_csv_value_column,
                source_run_dir=rebuilt.source_run_dir,
                manifest=rebuilt.manifest,
            )
        )
    return merged


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
    apply_skimjoin: bool | None = None,
    apply_segmentation: bool | None = None,
) -> ProcessorWorkflowResult:
    """Build or reuse summaries for the configured runs."""
    config = shared.effective_processor_config(
        config,
        apply_skimjoin=apply_skimjoin,
        apply_segmentation=apply_segmentation,
    )
    summary_runs: list[Any] = []
    prepared_root = prepared_root or prepared_cache_root(config, create=True)
    prepare_result = existing_result
    (
        existing_prepared_runs_by_key,
        prepared_runs_by_key,
        run_keys,
        run_fingerprints_by_key,
    ) = shared.init_processor_result(prepare_result)
    runs_with_keys = run_entries_with_keys(run_entries)

    for entry, run_key in runs_with_keys:
        metadata = _run_cache_metadata(entry=entry, run_key=run_key, config=config)
        label = str(metadata["label"])
        run_fingerprint = dict(metadata["run_fingerprint"])
        raw_prepared_manifest_identity = metadata["prepared_manifest_identity"]
        prepared_manifest_identity = (
            dict(raw_prepared_manifest_identity)
            if raw_prepared_manifest_identity is not None
            else None
        )
        summary_table_map = entry.get("summary_table_map") or None
        external_summary_run = None
        external_summary_ids: set[str] = set()
        if summary_table_map:
            LOGGER.info("Loading custom summary tables for %r", label)
            external_summary_run = load_summary_table_map(
                summary_table_map=summary_table_map,
                label=label,
                run_key=run_key,
                config=config,
                source_run_dir=entry.get("dir") or None,
            )
            external_summary_ids = set(summary_table_map)
        cache_dir = cache_root / run_key
        run_keys.append(run_key)
        run_fingerprints_by_key[run_key] = run_fingerprint
        cached_run = None

        if prefer_cache:
            cached_run = _load_summary_run_from_cache(
                cache_dir=cache_dir,
                config=config,
                label=label,
                run_key=run_key,
                run_fingerprint=run_fingerprint,
                prepared_manifest_identity=prepared_manifest_identity,
            )
            if cached_run is not None:
                stale_summary_ids = list(cached_run["stale_summary_ids"])
                if not stale_summary_ids:
                    summary_runs.extend(
                        merge_summary_table_map_run(
                            cached_run["summary_runs"],
                            external_summary_run,
                        )
                    )
                    cached_prepared_run = existing_prepared_runs_by_key.get(run_key)
                    if cached_prepared_run is not None:
                        prepared_runs_by_key[run_key] = cached_prepared_run
                    continue

        cached_summary_runs = list(cached_run["summary_runs"]) if cached_run else []
        summary_ids_to_build = summary_cache.requested_summary_ids(config)
        if cached_run is not None:
            summary_ids_to_build = list(cached_run["stale_summary_ids"])
        summary_ids_to_build = [
            summary_id
            for summary_id in summary_ids_to_build
            if summary_id not in external_summary_ids
        ]

        has_buildable_inputs = bool(entry.get("dir") or entry.get("prepared_table_map"))
        if not has_buildable_inputs:
            run_summary_runs = merge_summary_table_map_run(
                cached_summary_runs,
                external_summary_run,
            )
            if run_summary_runs:
                summary_runs.extend(run_summary_runs)
                if write_cache:
                    LOGGER.info("Writing summary cache for run: %r", label)
                    cache_path = summary_cache.write_summary_run_bundle(
                        run_summary_runs,
                        config,
                        run_fingerprint=run_fingerprint,
                        prepared_manifest_identity=prepared_manifest_identity,
                    )
                    LOGGER.info("Wrote summaries: %s", cache_path)
                else:
                    LOGGER.info("Skipped cache write for run: %r", label)
                continue
            LOGGER.warning(
                "Skipping summary build for %r because no raw, prepared, or summary table inputs were available.",
                label,
            )
            continue

        prepare_result = run_prepare_workflow(
            config=config,
            prepared_root=prepared_root,
            run_entries=[entry],
            prefer_cache=prepared_prefer_cache,
            write_cache=True,
            existing_result=prepare_result,
            apply_skimjoin=apply_skimjoin,
        )
        if run_key not in prepare_result.prepared_runs_by_key:
            run_summary_runs = merge_summary_table_map_run(
                cached_summary_runs,
                external_summary_run,
            )
            if run_summary_runs:
                summary_runs.extend(run_summary_runs)
                if write_cache:
                    LOGGER.info("Writing summary cache for run: %r", label)
                    cache_path = summary_cache.write_summary_run_bundle(
                        run_summary_runs,
                        config,
                        run_fingerprint=run_fingerprint,
                        prepared_manifest_identity=prepared_manifest_identity,
                    )
                    LOGGER.info("Wrote summaries: %s", cache_path)
                else:
                    LOGGER.info("Skipped cache write for run: %r", label)
                continue
            LOGGER.warning(
                "Skipping summary build for %r because no prepared tables were available.",
                label,
            )
            continue
        prepared_loaded = prepare_result.prepared_runs_by_key[run_key]
        existing_prepared_runs_by_key = dict(prepare_result.prepared_runs_by_key)
        prepared_runs_by_key[run_key] = prepared_loaded

        analysis_units = build_analysis_units_for_run(
            run_key=run_key,
            run_name=label,
            prepared_run=prepared_loaded[1],
            config=config,
        )
        run_summary_runs = []
        if summary_ids_to_build:
            for unit in analysis_units:
                summaries_by_mode, summary_metadata_by_mode = _build_summary_tables_for_run(
                    prepared_run=unit.prepared_run,
                    config=config,
                    summary_ids=summary_ids_to_build,
                )
                run_summary_runs.append(
                    summary_cache.create_summary_run(
                        label=unit.run_name,
                        run_key=unit.run_key,
                        summaries_by_mode=summaries_by_mode,
                        summary_metadata_by_mode=summary_metadata_by_mode,
                        segmentation_type=unit.segmentation_type,
                        segment_id=unit.segment_id,
                        segment_label=unit.segment_label,
                        is_full_segment=unit.is_full,
                        segment_source_type=unit.segment_metadata.source_type,
                        segment_column=unit.segment_metadata.column,
                        segment_values=unit.segment_metadata.values,
                        segment_source_table=unit.segment_metadata.source_table,
                        segment_source_key_column=unit.segment_metadata.source_key_column,
                        segment_csv_file=unit.segment_metadata.csv_file,
                        segment_csv_key_column=unit.segment_metadata.csv_key_column,
                        segment_csv_value_column=unit.segment_metadata.csv_segment_value_column,
                        source_run_dir=str(unit.prepared_run.run_dir),
                    )
                )
        if cached_summary_runs and run_summary_runs:
            run_summary_runs = _merge_summary_runs(
                cached_runs=cached_summary_runs,
                rebuilt_runs=run_summary_runs,
            )
        elif cached_summary_runs:
            run_summary_runs = cached_summary_runs
        run_summary_runs = merge_summary_table_map_run(
            run_summary_runs,
            external_summary_run,
        )
        summary_runs.extend(run_summary_runs)

        if write_cache:
            LOGGER.info("Writing summary cache for run: %r", label)
            cache_path = summary_cache.write_summary_run_bundle(
                run_summary_runs,
                config,
                run_fingerprint=run_fingerprint,
                prepared_manifest_identity=prepared_manifest_identity,
            )
            LOGGER.info("Wrote summaries: %s", cache_path)
        else:
            LOGGER.info("Skipped cache write for run: %r", label)

    if not summary_runs:
        raise ValueError("no runs were loaded.")
    return ProcessorWorkflowResult(
        summary_runs=summary_runs,
        prepared_runs=_ordered_prepared_runs(
            prepared_runs_by_key=prepared_runs_by_key,
            run_keys=run_keys,
        ),
        prepared_runs_by_key=prepared_runs_by_key,
        run_keys=run_keys,
        run_fingerprints_by_key=run_fingerprints_by_key,
    )
