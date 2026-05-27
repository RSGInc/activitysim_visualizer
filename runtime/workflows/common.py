"""Shared runtime workflow helpers with no raw-run orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from activitysim_viz_logging import get_logger
from processor.cache_identity import build_run_fingerprint, build_run_keys
from processor.models import (
    PreparedTableName,
    ProcessorWorkflowResult,
    prune_prepared_runs,
)
from processor.prepare.cache import build_prepared_manifest_identity, prepared_root
from processor.prepare.reader import resolve_skim_path
from processor.summarize import cache as summary_cache
from runtime.config import Config
from runtime.workflows import shared

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
    logger = LOGGER
    if cli_runs:
        logger.info("Using runs provided on CLI")
        run_entries: list[dict] = []
        resolved_cli_skims = cli_run_skims or []
        for idx, (run_dir, label) in enumerate(cli_runs):
            skim = resolved_cli_skims[idx] if idx < len(resolved_cli_skims) else None
            if skim in ("", "null", "None"):
                skim = None
            run_entries.append({"dir": run_dir, "label": label, "skim_file": skim})
        return run_entries

    if config.runs:
        logger.info("Using runs from config")
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
    """Load validated summary caches for dashboard or export workflows."""
    cache_dirs, run_entries_by_key = shared.summary_cache_dirs_for_load(
        cache_root=cache_root,
        explicit_cache_dirs=explicit_cache_dirs,
        run_entries=run_entries,
        build_run_keys_fn=build_run_keys,
        discover_cache_dirs_fn=summary_cache.discover_cache_dirs,
    )

    if not cache_dirs:
        raise ValueError("no summary cache directories were found to load.")

    summary_runs: list[Any] = []
    for cache_dir in cache_dirs:
        expectations = (
            shared.summary_cache_load_expectations(
                cache_dir=cache_dir,
                run_entries_by_key=run_entries_by_key,
                config=config,
                build_run_fingerprint_fn=build_run_fingerprint,
                resolve_skim_path_fn=resolve_skim_path,
                build_prepared_manifest_identity_fn=build_prepared_manifest_identity,
            )
            or {}
        )
        summary_runs.extend(
            summary_cache.load_summary_run_bundle(
                cache_dir,
                config,
                expected_modes=config.weighting_modes,
                expected_summary_ids=summary_cache.requested_summary_ids(config),
                expected_summary_config_digest=config.summary_config_digest,
                expected_run_fingerprint=expectations.get("expected_run_fingerprint"),
                expected_prepared_manifest_identity=expectations.get(
                    "expected_prepared_manifest_identity"
                ),
                expected_label=expectations.get("expected_label"),
                expected_run_key=expectations.get("expected_run_key"),
            )
        )
    return summary_runs


def run_entries_with_keys(run_entries: list[dict]) -> list[tuple[dict, str]]:
    """Return each resolved run entry paired with its stable summary cache key."""
    return shared.run_entries_with_keys(
        run_entries,
        build_run_keys_fn=build_run_keys,
    )


def prune_summary_runs(
    summary_runs: list[Any],
    required_summary_ids: list[str] | tuple[str, ...],
) -> list[Any]:
    """Return summary runs containing only the summary ids needed downstream."""
    return shared.prune_summary_runs(
        summary_runs,
        required_summary_ids,
        create_summary_run_fn=summary_cache.create_summary_run,
    )


def prune_processor_result(
    result: ProcessorWorkflowResult | None,
    *,
    required_summary_ids: list[str] | tuple[str, ...],
    required_prepared_tables: list[PreparedTableName] | tuple[PreparedTableName, ...],
) -> ProcessorWorkflowResult | None:
    """Return a processor result trimmed to the next dashboard/export step."""
    return shared.prune_processor_result(
        result,
        required_summary_ids=required_summary_ids,
        required_prepared_tables=required_prepared_tables,
        prune_prepared_runs_fn=prune_prepared_runs,
        prune_summary_runs_fn=prune_summary_runs,
    )
