"""Shared runtime workflows for summarize, dashboard, and export execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from activitysim_viz_logging import get_logger
from dashboard.page_registry import export_data_requirements, live_data_requirements
from processor.models import (
    PreparedTableName,
    ProcessorWorkflowResult,
    RunData,
    prune_prepared_runs,
)
from processor.prepare.availability import (
    failed_tables,
    has_usable_loaded_tables,
    unavailable_tables,
)
from processor.prepare.cache import (
    PreparedCacheError,
    build_prepared_manifest_identity,
    build_run_fingerprint,
    build_run_keys,
    load_prepared_run_cache,
    prepared_root,
    write_prepared_run_cache,
)
from processor.prepare.enrichment.pipeline import prepare_data
from processor.prepare.reader import read_run, resolve_skim_path
from runtime.config import Config
from processor.summarize import cache as summary_cache

LOGGER = get_logger("main")


def load_runtime_config(config_path: str | Path) -> Config:
    """Load config and normalize the shared runtime settings."""
    config = Config.from_yaml(config_path)
    config.weighting_modes = summary_cache.normalize_weighting_modes(
        config.weighting_modes
    )
    return config


def resolve_run_entries(
    *,
    cli_runs: list[tuple[str, str]] | None,
    cli_run_skims: list[str] | None,
    config: Config,
    require_runs: bool,
) -> list[dict]:
    """Resolve raw run inputs from CLI overrides or config."""
    if cli_runs:
        LOGGER.info("Using runs provided on CLI")
        run_entries: list[dict] = []
        resolved_cli_skims = cli_run_skims or []
        for idx, (run_dir, label) in enumerate(cli_runs):
            skim = resolved_cli_skims[idx] if idx < len(resolved_cli_skims) else None
            if skim in ("", "null", "None"):
                skim = None
            run_entries.append({"dir": run_dir, "label": label, "skim_file": skim})
        return run_entries

    if config.runs:
        LOGGER.info("Using runs from config")
        return list(config.runs)

    if require_runs:
        raise ValueError(
            "no runs specified. Add runs to config.yaml or use --run DIR LABEL."
        )
    return []


def summary_cache_root(config: Config, *, create: bool) -> Path:
    """Return the configured summary cache root, creating it when requested."""
    cache_root = summary_cache.summary_root(config)
    if create:
        cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def prepared_cache_root(config: Config, *, create: bool) -> Path:
    """Return the configured prepared cache root, creating it when requested."""
    cache_root = prepared_root(config)
    if create:
        cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def load_summary_runs_from_cache(
    *,
    config: Config,
    cache_root: Path,
    explicit_cache_dirs: list[str] | None,
    run_entries: list[dict] | None,
) -> list[Any]:
    """Load validated summary caches for dashboard or export workflows.

    This path never rebuilds missing summaries. It is the cache-only branch used
    by ``--from-csvs`` and by workflows that should fail fast instead of
    silently regenerating summary content.
    """
    explicit_dirs = [Path(path).resolve() for path in (explicit_cache_dirs or [])]
    if explicit_dirs:
        cache_dirs = explicit_dirs
        run_entries_by_key: dict[str, dict] = {}
    else:
        if run_entries:
            run_labels = [
                entry.get("label", Path(entry.get("dir", "")).name or "run")
                for entry in run_entries
            ]
            run_keys = summary_cache.build_run_keys(run_labels)
            cache_dirs = [cache_root / run_key for run_key in run_keys]
            run_entries_by_key = {
                run_key: entry for entry, run_key in zip(run_entries, run_keys)
            }
        else:
            cache_dirs = summary_cache.discover_cache_dirs(cache_root)
            run_entries_by_key = {}

    if not cache_dirs:
        raise ValueError("no summary cache directories were found to load.")

    summary_runs: list[Any] = []
    LOGGER.info("Loading pre-computed summary caches")
    for cache_dir in cache_dirs:
        expected_label = None
        expected_run_key = None
        expected_run_fingerprint = None
        if cache_dir.name in run_entries_by_key:
            entry = run_entries_by_key[cache_dir.name]
            run_dir = entry.get("dir", "")
            expected_label = entry.get("label", Path(run_dir).name)
            expected_run_key = cache_dir.name
            expected_run_fingerprint = build_run_fingerprint(
                label=expected_label,
                run_dir=run_dir,
                skim_file=resolve_skim_path(
                    entry.get("skim_file") or None,
                    config.skim_file,
                    run_dir,
                ),
                hh_weight_col=entry.get("hh_weight_col") or None,
                person_weight_col=entry.get("person_weight_col") or None,
                trip_weight_col=entry.get("trip_weight_col") or None,
            )
            expected_prepared_manifest_identity = (
                build_prepared_manifest_identity(
                    run_key=expected_run_key,
                    config=config,
                    run_fingerprint=expected_run_fingerprint,
                )
            )
        else:
            expected_prepared_manifest_identity = None
        summary_runs.append(
            summary_cache.load_summary_run_cache(
                cache_dir,
                config,
                expected_modes=config.weighting_modes,
                expected_summary_ids=summary_cache.DEFAULT_SUMMARY_IDS,
                expected_summary_config_digest=config.summary_config_digest,
                expected_run_fingerprint=expected_run_fingerprint,
                expected_prepared_manifest_identity=expected_prepared_manifest_identity,
                expected_label=expected_label,
                expected_run_key=expected_run_key,
            )
        )
    return summary_runs


def run_entries_with_keys(run_entries: list[dict]) -> list[tuple[dict, str]]:
    """Return each resolved run entry paired with its stable summary cache key."""
    run_labels = [
        entry.get("label", Path(entry.get("dir", "")).name or "run")
        for entry in run_entries
    ]
    run_keys = build_run_keys(run_labels)
    return list(zip(run_entries, run_keys))


def prune_summary_runs(
    summary_runs: list[Any],
    required_summary_ids: list[str] | tuple[str, ...],
) -> list[Any]:
    """Return summary runs containing only the summary ids needed downstream."""
    if not summary_runs:
        return []

    required_ids = set(required_summary_ids)
    return [
        summary_cache.create_summary_run(
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
) -> ProcessorWorkflowResult | None:
    """Return a processor result trimmed to the next dashboard/export step."""
    if result is None:
        return None

    pruned_prepared_runs_by_key = {
        run_key: (
            label,
            prune_prepared_runs([(label, prepared_run)], required_prepared_tables)[0][1],
        )
        for run_key, (label, prepared_run) in result.prepared_runs_by_key.items()
    }
    ordered_prepared_runs = [
        pruned_prepared_runs_by_key[run_key]
        for run_key in result.run_keys
        if run_key in pruned_prepared_runs_by_key
    ]
    return ProcessorWorkflowResult(
        summary_runs=prune_summary_runs(result.summary_runs, required_summary_ids),
        prepared_runs=ordered_prepared_runs,
        prepared_runs_by_key=pruned_prepared_runs_by_key,
        run_keys=list(result.run_keys),
        run_fingerprints_by_key=dict(result.run_fingerprints_by_key),
    )


def _run_cache_metadata(
    *,
    entry: dict,
    run_key: str,
    config: Config,
) -> dict[str, object]:
    """Return the stable cache metadata for one resolved run entry."""
    run_dir = entry.get("dir", "")
    label = entry.get("label", Path(run_dir).name)
    skim = entry.get("skim_file") or None
    resolved_skim = resolve_skim_path(skim, config.skim_file, run_dir)
    run_fingerprint = build_run_fingerprint(
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
        "prepared_manifest_identity": build_prepared_manifest_identity(
            run_key=run_key,
            config=config,
            run_fingerprint=run_fingerprint,
        ),
    }


def _resolve_prepared_run(
    *,
    entry: dict,
    run_key: str,
    config: Config,
    prepared_root: Path,
    existing_prepared_runs_by_key: dict[str, tuple[str, RunData]],
    prefer_cache: bool,
    write_cache: bool,
) -> tuple[str, RunData] | None:
    """Reuse in-memory prepared runs, then prepared cache, then raw-run rebuilds."""
    def _log_prepare_table_diagnostics(run_label: str, prepared_run: RunData) -> None:
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

    cached_prepared_run = existing_prepared_runs_by_key.get(run_key)
    if cached_prepared_run is not None:
        if not has_usable_loaded_tables(cached_prepared_run[1]):
            LOGGER.warning(
                "Skipping prepared run %r because no raw prepared tables are available.",
                cached_prepared_run[0],
            )
            return None
        LOGGER.info("Reusing in-memory prepared run for %r", cached_prepared_run[0])
        _log_prepare_table_diagnostics(cached_prepared_run[0], cached_prepared_run[1])
        return cached_prepared_run

    metadata = _run_cache_metadata(entry=entry, run_key=run_key, config=config)
    label = str(metadata["label"])
    run_dir = str(metadata["run_dir"])
    run_fingerprint = dict(metadata["run_fingerprint"])
    prepared_dir = prepared_root / run_key

    if prefer_cache:
        try:
            prepared_run = load_prepared_run_cache(
                prepared_dir,
                config,
                expected_prepare_config_digest=config.prepare_config_digest,
                expected_run_fingerprint=run_fingerprint,
                expected_label=label,
                expected_run_key=run_key,
            )
            LOGGER.info("Loaded prepared cache for run: %r", label)
            loaded = (label, prepared_run)
            if not has_usable_loaded_tables(prepared_run):
                LOGGER.warning(
                    "Skipping prepared cache for %r because no raw prepared tables are available.",
                    label,
                )
                return None
            _log_prepare_table_diagnostics(label, prepared_run)
            existing_prepared_runs_by_key[run_key] = loaded
            return loaded
        except PreparedCacheError as exc:
            LOGGER.info("Prepared cache miss for %r: %s", label, exc)

    LOGGER.info("Reading run %r from %s", label, run_dir)
    prepared_run = read_run(
        run_dir,
        config,
        label=label,
        skim_file=metadata["skim"],
        hh_weight_col=entry.get("hh_weight_col") or None,
        person_weight_col=entry.get("person_weight_col") or None,
        trip_weight_col=entry.get("trip_weight_col") or None,
    )
    prepared_run = prepare_data(prepared_run, config)
    if not has_usable_loaded_tables(prepared_run):
        LOGGER.warning(
            "Skipping run %r because no raw prepared tables could be loaded safely.",
            label,
        )
        return None
    _log_prepare_table_diagnostics(label, prepared_run)
    LOGGER.info("Prepared run: %r", label)
    if write_cache:
        write_prepared_run_cache(
            prepared_run,
            config,
            run_key=run_key,
            output_root=prepared_root,
            run_fingerprint=run_fingerprint,
        )
        LOGGER.info("Wrote prepared cache for run: %r", label)
    else:
        LOGGER.info("Skipped prepared cache write for run: %r", label)
    loaded = (label, prepared_run)
    existing_prepared_runs_by_key[run_key] = loaded
    return loaded


def run_prepare_workflow(
    *,
    config: Config,
    prepared_root: Path | None,
    run_entries: list[dict],
    prefer_cache: bool,
    write_cache: bool,
    existing_result: ProcessorWorkflowResult | None = None,
) -> ProcessorWorkflowResult:
    """Build or reuse prepared runs for the configured entries."""
    prepared_root = prepared_root or prepared_cache_root(config, create=write_cache)
    existing_prepared_runs_by_key = dict(
        (existing_result.prepared_runs_by_key if existing_result else {}) or {}
    )
    prepared_runs_by_key: dict[str, tuple[str, RunData]] = {}
    run_keys: list[str] = []
    run_fingerprints_by_key: dict[str, dict[str, object]] = {}

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
        )
        if prepared_loaded is None:
            continue
        prepared_runs_by_key[run_key] = prepared_loaded
        run_keys.append(run_key)
        run_fingerprints_by_key[run_key] = dict(metadata["run_fingerprint"])

    ordered_prepared_runs = [
        prepared_runs_by_key[run_key]
        for run_key in run_keys
        if run_key in prepared_runs_by_key
    ]
    return ProcessorWorkflowResult(
        summary_runs=list(existing_result.summary_runs) if existing_result else [],
        prepared_runs=ordered_prepared_runs,
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
) -> list[tuple[str, RunData]]:
    """Load prepared runs only when enabled pages require them.

    Most pages should stay summary-backed. This loader exists for the smaller
    set of pages that opt into prepared-run access through page definitions.
    """
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
    prepare_result = run_prepare_workflow(
        config=config,
        prepared_root=prepared_cache_root(config, create=True),
        run_entries=selected_entries,
        prefer_cache=True,
        write_cache=True,
        existing_result=prepare_result,
    )
    ordered_runs = [
        prepare_result.prepared_runs_by_key[run_key]
        for run_key in required_run_keys
        if run_key in prepare_result.prepared_runs_by_key
    ]
    if required_prepared_tables:
        return prune_prepared_runs(ordered_runs, required_prepared_tables)
    return ordered_runs


def run_summary_workflow(
    *,
    config: Config,
    cache_root: Path,
    prepared_root: Path | None = None,
    run_entries: list[dict],
    prefer_cache: bool,
    write_cache: bool,
    existing_result: ProcessorWorkflowResult | None = None,
) -> ProcessorWorkflowResult:
    """Build or reuse summaries for the configured runs.

    The summary workflow is intentionally cache-aware:

    - try to reuse an existing cache when ``prefer_cache`` is true
    - fall back to raw-run loading only when the cache is missing or invalid
    - optionally write back refreshed cache contents for future runs
    """
    summary_runs: list[Any] = []
    prepared_root = prepared_root or prepared_cache_root(config, create=True)
    prepare_result = existing_result
    existing_prepared_runs_by_key = dict(
        (prepare_result.prepared_runs_by_key if prepare_result else {}) or {}
    )
    prepared_runs_by_key: dict[str, tuple[str, RunData]] = {}
    run_keys: list[str] = []
    run_fingerprints_by_key: dict[str, dict[str, object]] = {}
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
            # Cache reuse is intentionally attempted before raw-run loading so
            # presentation-only changes do not force expensive summary rebuilds.
            try:
                cached_run = summary_cache.load_summary_run_cache(
                    cache_dir,
                    config,
                    expected_modes=config.weighting_modes,
                    expected_summary_ids=summary_cache.DEFAULT_SUMMARY_IDS,
                    expected_summary_config_digest=config.summary_config_digest,
                    expected_run_fingerprint=run_fingerprint,
                    expected_prepared_manifest_identity=prepared_manifest_identity,
                    expected_label=label,
                    expected_run_key=run_key,
                )
                LOGGER.info("Loaded summary cache for run: %r", label)
                summary_runs.append(cached_run)
                cached_prepared_run = existing_prepared_runs_by_key.get(run_key)
                if cached_prepared_run is not None:
                    prepared_runs_by_key[run_key] = cached_prepared_run
                continue
            except summary_cache.SummaryCacheError as exc:
                LOGGER.info("Cache miss for %r: %s", label, exc)

        prepare_result = run_prepare_workflow(
            config=config,
            prepared_root=prepared_root,
            run_entries=[entry],
            prefer_cache=True,
            write_cache=True,
            existing_result=prepare_result,
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

        summaries_by_mode, summary_metadata_by_mode = (
            summary_cache.build_mode_summaries_with_metadata(
                prepared_loaded[1], config
            )
        )
        summary_run = summary_cache.create_summary_run(
            label=label,
            run_key=run_key,
            summaries_by_mode=summaries_by_mode,
            summary_metadata_by_mode=summary_metadata_by_mode,
            source_run_dir=str(prepared_loaded[1].run_dir),
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
    ordered_prepared_runs = [
        prepared_runs_by_key[run_key]
        for run_key in run_keys
        if run_key in prepared_runs_by_key
    ]
    return ProcessorWorkflowResult(
        summary_runs=summary_runs,
        prepared_runs=ordered_prepared_runs,
        prepared_runs_by_key=prepared_runs_by_key,
        run_keys=run_keys,
        run_fingerprints_by_key=run_fingerprints_by_key,
    )


def run_dashboard_workflow(
    *,
    summary_runs: list[Any],
    prepared_runs: list[tuple[str, RunData]] | None = None,
    config: Config,
    export_html_path: str | None = None,
    port: int = 5006,
    show: bool = True,
) -> None:
    """Render the live dashboard or a standalone HTML export.

    This workflow assumes summary computation has already happened. It consumes
    ``summary_runs`` as an input contract rather than triggering a rebuild.
    """
    if prepared_runs is None:
        prepared_runs = []
    if not summary_runs:
        raise ValueError(
            "dashboard workflow requires precomputed summary runs and will not build them."
        )
    requirements = (
        export_data_requirements(config)
        if export_html_path
        else live_data_requirements(config)
    )
    summary_runs = prune_summary_runs(
        summary_runs,
        requirements.required_summary_ids,
    )
    prepared_runs = (
        prune_prepared_runs(prepared_runs, requirements.required_prepared_tables)
        if requirements.prepared_data_mode != "none"
        else []
    )

    if export_html_path:
        from dashboard.export.html import write_export_html_document

        LOGGER.info("Building dashboard")
        LOGGER.info("Exporting dashboard to %s ...", export_html_path)
        write_export_html_document(
            export_html_path,
            prepared_runs,
            config,
            summary_runs=summary_runs,
        )
        LOGGER.info("Done.")
        return

    from dashboard.app import build_dashboard
    import panel as pn

    LOGGER.info("Building dashboard")
    dashboard = build_dashboard(
        prepared_runs,
        config,
        summary_runs=summary_runs,
    )
    pn.serve(
        dashboard,
        port=port,
        show=show,
        title=config.dashboard_title,
    )
