"""Shared runtime workflows for summarize, dashboard, and export execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from activitysim_viz_logging import get_logger
from runtime import run_data as runtime_run_data
from runtime.config import Config
from runtime.models import RunData
from summarize import cache as summary_cache

LOGGER = get_logger("main")


@dataclass(frozen=True)
class SummaryWorkflowResult:
    """Prepared summary runs plus any raw runs loaded along the way."""

    summary_runs: list[Any]
    raw_runs: list[tuple[str, RunData]]
    raw_runs_by_key: dict[str, tuple[str, RunData]]


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


def load_summary_runs_from_cache(
    *,
    config: Config,
    cache_root: Path,
    explicit_cache_dirs: list[str] | None,
    run_entries: list[dict] | None,
) -> list[Any]:
    """Load precomputed summary runs for dashboard/export-only workflows."""
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
            expected_run_fingerprint = summary_cache.build_run_fingerprint(
                label=expected_label,
                run_dir=run_dir,
                skim_file=runtime_run_data.resolve_skim_path(
                    entry.get("skim_file") or None,
                    config.skim_file,
                    run_dir,
                ),
                hh_weight_col=entry.get("hh_weight_col") or None,
                person_weight_col=entry.get("person_weight_col") or None,
                trip_weight_col=entry.get("trip_weight_col") or None,
            )
        summary_runs.append(
            summary_cache.load_summary_run_cache(
                cache_dir,
                config,
                expected_modes=config.weighting_modes,
                expected_summary_ids=summary_cache.DEFAULT_SUMMARY_IDS,
                expected_summary_config_digest=config.summary_config_digest,
                expected_run_fingerprint=expected_run_fingerprint,
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
    run_keys = summary_cache.build_run_keys(run_labels)
    return list(zip(run_entries, run_keys))


def load_raw_runs_for_dashboard(
    *,
    config: Config,
    run_entries: list[dict],
    required_run_keys: list[str],
    existing_raw_runs_by_key: dict[str, tuple[str, RunData]] | None = None,
) -> list[tuple[str, RunData]]:
    """Load raw runs for dashboard-only pages without rebuilding summaries."""
    existing_raw_runs_by_key = dict(existing_raw_runs_by_key or {})
    if not required_run_keys:
        return []
    if not run_entries:
        LOGGER.warning(
            "Enabled dashboard pages require raw run data, but no raw run inputs are available."
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
            "Enabled dashboard pages require raw run data, but raw inputs could not be resolved "
            "for summary runs: %s",
            ", ".join(repr(run_key) for run_key in missing_run_keys),
        )
        return []

    ordered_raw_runs: list[tuple[str, RunData]] = []
    for run_key in required_run_keys:
        cached_raw_run = existing_raw_runs_by_key.get(run_key)
        if cached_raw_run is not None:
            ordered_raw_runs.append(cached_raw_run)
            continue

        entry = entries_by_key[run_key]
        run_dir = entry.get("dir", "")
        label = entry.get("label", Path(run_dir).name)
        skim = entry.get("skim_file") or None
        LOGGER.info("Reading raw runs for dashboard page needs: %r", label)
        raw_run = runtime_run_data.read_run(
            run_dir,
            config,
            label=label,
            skim_file=skim,
            hh_weight_col=entry.get("hh_weight_col") or None,
            person_weight_col=entry.get("person_weight_col") or None,
            trip_weight_col=entry.get("trip_weight_col") or None,
        )
        raw_run = runtime_run_data.prepare_data(raw_run, config)
        LOGGER.info("Prepared raw runs for dashboard page needs: %r", label)
        loaded = (label, raw_run)
        existing_raw_runs_by_key[run_key] = loaded
        ordered_raw_runs.append(loaded)
    return ordered_raw_runs


def run_summary_workflow(
    *,
    config: Config,
    cache_root: Path,
    run_entries: list[dict],
    prefer_cache: bool,
    write_cache: bool,
) -> SummaryWorkflowResult:
    """Load summaries for the configured runs, using raw runs only in the summary step."""
    summary_runs: list[Any] = []
    raw_runs: list[tuple[str, RunData]] = []
    raw_runs_by_key: dict[str, tuple[str, RunData]] = {}
    runs_with_keys = run_entries_with_keys(run_entries)

    for entry, run_key in runs_with_keys:
        run_dir = entry.get("dir", "")
        label = entry.get("label", Path(run_dir).name)
        skim = entry.get("skim_file") or None
        resolved_skim = runtime_run_data.resolve_skim_path(
            skim, config.skim_file, run_dir
        )
        run_fingerprint = summary_cache.build_run_fingerprint(
            label=label,
            run_dir=run_dir,
            skim_file=resolved_skim,
            hh_weight_col=entry.get("hh_weight_col") or None,
            person_weight_col=entry.get("person_weight_col") or None,
            trip_weight_col=entry.get("trip_weight_col") or None,
        )
        cache_dir = cache_root / run_key

        if prefer_cache:
            try:
                cached_run = summary_cache.load_summary_run_cache(
                    cache_dir,
                    config,
                    expected_modes=config.weighting_modes,
                    expected_summary_ids=summary_cache.DEFAULT_SUMMARY_IDS,
                    expected_summary_config_digest=config.summary_config_digest,
                    expected_run_fingerprint=run_fingerprint,
                    expected_label=label,
                    expected_run_key=run_key,
                )
                LOGGER.info("Loaded summary cache for run: %r", label)
                summary_runs.append(cached_run)
                continue
            except summary_cache.SummaryCacheError as exc:
                LOGGER.info("Cache miss for %r: %s", label, exc)

        LOGGER.info("Reading run %r from %s", label, run_dir)
        raw_run = runtime_run_data.read_run(
            run_dir,
            config,
            label=label,
            skim_file=skim,
            hh_weight_col=entry.get("hh_weight_col") or None,
            person_weight_col=entry.get("person_weight_col") or None,
            trip_weight_col=entry.get("trip_weight_col") or None,
        )
        raw_run = runtime_run_data.prepare_data(raw_run, config)
        LOGGER.info("Prepared run: %r", label)
        raw_loaded = (label, raw_run)
        raw_runs.append(raw_loaded)
        raw_runs_by_key[run_key] = raw_loaded

        summary_run = summary_cache.create_summary_run(
            label=label,
            run_key=run_key,
            summaries_by_mode=summary_cache.build_mode_summaries(raw_run, config),
            source_run_dir=str(raw_run.run_dir),
        )
        summary_runs.append(summary_run)

        if write_cache:
            LOGGER.info("Writing summary cache for run: %r", label)
            cache_path = summary_cache.write_summary_run_cache(
                summary_run,
                config,
                run_fingerprint=run_fingerprint,
            )
            LOGGER.info("Wrote summaries: %s", cache_path)
        else:
            LOGGER.info("Skipped cache write for run: %r", label)

    if not summary_runs:
        raise ValueError("no runs were loaded.")
    return SummaryWorkflowResult(
        summary_runs=summary_runs,
        raw_runs=raw_runs,
        raw_runs_by_key=raw_runs_by_key,
    )


def run_dashboard_workflow(
    *,
    raw_runs: list[tuple[str, RunData]],
    summary_runs: list[Any],
    config: Config,
    export_html_path: str | None = None,
    port: int = 5006,
    show: bool = True,
) -> None:
    """Render the dashboard or export from already-prepared inputs only."""
    if not summary_runs:
        raise ValueError(
            "dashboard workflow requires precomputed summary runs and will not build them."
        )

    if export_html_path:
        from dashboard.export_html import write_export_html_document

        LOGGER.info("Building dashboard")
        LOGGER.info("Exporting dashboard to %s ...", export_html_path)
        write_export_html_document(
            export_html_path,
            raw_runs,
            config,
            summary_runs=summary_runs,
        )
        LOGGER.info("Done.")
        return

    from dashboard.app import build_dashboard
    import panel as pn

    LOGGER.info("Building dashboard")
    dashboard = build_dashboard(
        raw_runs,
        config,
        summary_runs=summary_runs,
    )
    pn.serve(
        dashboard,
        port=port,
        show=show,
        title=config.dashboard_title,
    )
