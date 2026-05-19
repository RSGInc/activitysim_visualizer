"""Summary workflow orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from activitysim_viz_logging import get_logger
from processor.models import ProcessorWorkflowResult, RunData
from processor.prepare.cache import load_prepared_run_cache
from processor.prepare.enrichment.pipeline import prepare_data
from processor.prepare.reader import read_run
from processor.skimjoin.pipeline import apply_skimjoin
from processor.summarize import cache as summary_cache
from runtime.config import Config
from runtime.workflows.common import prepared_cache_root, run_entries_with_keys
from runtime.workflows.prepare import run_prepare_workflow
from runtime.workflows import shared

LOGGER = get_logger("main")


def _run_cache_metadata(*, entry: dict, run_key: str, config: Config) -> dict[str, object]:
    """Return the stable cache metadata for one resolved run entry."""
    from runtime.workflows.prepare import _run_cache_metadata as prepare_run_cache_metadata

    return prepare_run_cache_metadata(entry=entry, run_key=run_key, config=config)


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
        cached_run = summary_cache.load_summary_run_cache(
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
        LOGGER.info("Loaded summary cache for run: %r", label)
        return cached_run
    except summary_cache.SummaryCacheError as exc:
        LOGGER.info("Cache miss for %r: %s", label, exc)
        return None


def _build_summary_tables_for_run(
    *,
    prepared_run: RunData,
    config: Config,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, object]]]]:
    """Build summary tables and metadata for one prepared run."""
    if config.skimjoin.enabled:
        return summary_cache.build_mode_summaries_with_metadata(
            prepared_run,
            config,
            summary_ids=summary_cache.requested_summary_ids(config),
        )
    return summary_cache.build_mode_summaries_with_metadata(prepared_run, config)


def _build_summary_run_from_prepared(
    *,
    label: str,
    run_key: str,
    prepared_loaded: tuple[str, RunData],
    config: Config,
) -> Any:
    """Build one summary run wrapper from an already prepared run."""
    summaries_by_mode, summary_metadata_by_mode = _build_summary_tables_for_run(
        prepared_run=prepared_loaded[1],
        config=config,
    )
    return summary_cache.create_summary_run(
        label=label,
        run_key=run_key,
        summaries_by_mode=summaries_by_mode,
        summary_metadata_by_mode=summary_metadata_by_mode,
        source_run_dir=str(prepared_loaded[1].run_dir),
    )


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
    run_prepare_workflow_fn: Callable[..., ProcessorWorkflowResult] = run_prepare_workflow,
    read_run_fn: Callable[..., RunData] = read_run,
    prepare_data_fn: Callable[[RunData, Config], RunData] = prepare_data,
    apply_skimjoin_fn: Callable[[RunData, Config], RunData] = apply_skimjoin,
    load_prepared_run_cache_fn: Callable[..., RunData] = load_prepared_run_cache,
) -> ProcessorWorkflowResult:
    """Build or reuse summaries for the configured runs."""
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
        prepared_manifest_identity = dict(metadata["prepared_manifest_identity"])
        cache_dir = cache_root / run_key
        run_keys.append(run_key)
        run_fingerprints_by_key[run_key] = run_fingerprint

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
                summary_runs.append(cached_run)
                cached_prepared_run = existing_prepared_runs_by_key.get(run_key)
                if cached_prepared_run is not None:
                    prepared_runs_by_key[run_key] = cached_prepared_run
                continue

        prepare_result = run_prepare_workflow_fn(
            config=config,
            prepared_root=prepared_root,
            run_entries=[entry],
            prefer_cache=prepared_prefer_cache,
            write_cache=True,
            existing_result=prepare_result,
            read_run_fn=read_run_fn,
            prepare_data_fn=prepare_data_fn,
            apply_skimjoin_fn=apply_skimjoin_fn,
            load_prepared_run_cache_fn=load_prepared_run_cache_fn,
        )
        if run_key not in prepare_result.prepared_runs_by_key:
            LOGGER.warning(
                "Skipping summary build for %r because no prepared tables were available.",
                label,
            )
            continue
        prepared_loaded = prepare_result.prepared_runs_by_key[run_key]
        existing_prepared_runs_by_key = dict(prepare_result.prepared_runs_by_key)
        prepared_runs_by_key[run_key] = prepared_loaded

        summary_run = _build_summary_run_from_prepared(
            label=label,
            run_key=run_key,
            prepared_loaded=prepared_loaded,
            config=config,
        )
        summary_runs.append(summary_run)

        if write_cache:
            LOGGER.info("Writing summary cache for run: %r", label)
            cache_path = summary_cache.write_summary_run_cache(
                summary_run,
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
