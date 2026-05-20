"""Stable public summary cache API re-exporting smaller single-purpose modules."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from processor.cache_identity import build_run_fingerprint, build_run_keys, slugify
from processor.models import RunData
from processor.summarize.cache_execution import (
    build_mode_summaries as _build_mode_summaries,
    build_mode_summaries_with_metadata as _build_mode_summaries_with_metadata,
    build_summaries as _build_summaries,
    build_summaries_with_metadata as _build_summaries_with_metadata,
)
from processor.summarize.cache_storage import (
    SCHEMA_VERSION,
    discover_cache_dirs,
    load_summary_run_bundle as _load_summary_run_bundle,
    load_summary_run_cache as _load_summary_run_cache,
    summary_file_map as _summary_file_map,
    summary_root,
    write_summary_run_bundle as _write_summary_run_bundle,
    write_summary_run_cache as _write_summary_run_cache,
)
from processor.summarize.cache_types import (
    SUPPORTED_WEIGHTING_MODES,
    SummaryCacheError,
    SummaryRun,
    create_summary_run,
    normalize_weighting_modes,
    strip_weights,
)
from processor.summarize.summary_specs import (
    DEFAULT_SUMMARY_IDS,
    SUMMARY_FILENAME_BY_ID,
    SUMMARY_SPEC_BY_ID,
    SummarySpec,
)
from runtime.config import Config


def requested_summary_ids(config: Config) -> list[str]:
    """Return the registered default summary ids."""
    return list(DEFAULT_SUMMARY_IDS)


def build_summaries(
    rd: RunData,
    config: Config,
    summary_ids: list[str] | None = None,
) -> dict[str, pl.DataFrame]:
    """Build the requested summary tables for one prepared run."""
    return _build_summaries(
        rd,
        config,
        summary_ids=summary_ids,
        default_summary_ids=DEFAULT_SUMMARY_IDS,
        summary_spec_by_id=SUMMARY_SPEC_BY_ID,
    )


def build_summaries_with_metadata(
    rd: RunData,
    config: Config,
    summary_ids: list[str] | None = None,
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, object]]]:
    """Build summaries plus per-summary execution metadata."""
    return _build_summaries_with_metadata(
        rd,
        config,
        summary_ids=summary_ids,
        default_summary_ids=DEFAULT_SUMMARY_IDS,
        summary_spec_by_id=SUMMARY_SPEC_BY_ID,
    )


def build_mode_summaries(
    rd: RunData,
    config: Config,
    weighting_modes: list[str] | None = None,
    summary_ids: list[str] | None = None,
) -> dict[str, dict[str, pl.DataFrame]]:
    """Build the requested summaries for every enabled weighting mode."""
    return _build_mode_summaries(
        rd,
        config,
        weighting_modes=weighting_modes,
        summary_ids=summary_ids,
        default_summary_ids=DEFAULT_SUMMARY_IDS,
        summary_spec_by_id=SUMMARY_SPEC_BY_ID,
    )


def build_mode_summaries_with_metadata(
    rd: RunData,
    config: Config,
    weighting_modes: list[str] | None = None,
    summary_ids: list[str] | None = None,
) -> tuple[
    dict[str, dict[str, pl.DataFrame]],
    dict[str, dict[str, dict[str, object]]],
]:
    """Build requested summaries plus per-mode execution metadata."""
    return _build_mode_summaries_with_metadata(
        rd,
        config,
        weighting_modes=weighting_modes,
        summary_ids=summary_ids,
        default_summary_ids=DEFAULT_SUMMARY_IDS,
        summary_spec_by_id=SUMMARY_SPEC_BY_ID,
    )


def summary_file_map(summary_ids: list[str]) -> dict[str, str]:
    """Return persisted filenames for the requested summary ids."""
    return _summary_file_map(
        summary_ids,
        summary_filename_by_id=SUMMARY_FILENAME_BY_ID,
    )


def write_summary_run_cache(
    summary_run: SummaryRun,
    config: Config,
    *,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    prepared_manifest_identity: dict[str, object] | None = None,
) -> Path:
    """Write one run's summary cache directory and manifest."""
    return _write_summary_run_cache(
        summary_run,
        config,
        output_root=output_root,
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_filename_by_id=SUMMARY_FILENAME_BY_ID,
    )


def load_summary_run_cache(
    cache_dir: str | Path,
    config: Config,
    *,
    expected_modes: list[str] | None = None,
    expected_summary_ids: list[str] | None = None,
    expected_summary_config_digest: str | None = None,
    expected_run_fingerprint: dict[str, object] | None = None,
    expected_prepared_manifest_identity: dict[str, object] | None = None,
    expected_label: str | None = None,
    expected_run_key: str | None = None,
) -> SummaryRun:
    """Load and validate one run's summary cache directory."""
    return _load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=expected_modes,
        expected_summary_ids=expected_summary_ids,
        expected_summary_config_digest=expected_summary_config_digest,
        expected_run_fingerprint=expected_run_fingerprint,
        expected_prepared_manifest_identity=expected_prepared_manifest_identity,
        expected_label=expected_label,
        expected_run_key=expected_run_key,
        summary_spec_by_id=SUMMARY_SPEC_BY_ID,
    )


def write_summary_run_bundle(
    summary_runs: list[SummaryRun],
    config: Config,
    *,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    prepared_manifest_identity: dict[str, object] | None = None,
) -> Path:
    """Write one run cache directory containing all segment variants."""
    return _write_summary_run_bundle(
        summary_runs,
        config,
        output_root=output_root,
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_filename_by_id=SUMMARY_FILENAME_BY_ID,
    )


def load_summary_run_bundle(
    cache_dir: str | Path,
    config: Config,
    *,
    expected_modes: list[str] | None = None,
    expected_summary_ids: list[str] | None = None,
    expected_summary_config_digest: str | None = None,
    expected_run_fingerprint: dict[str, object] | None = None,
    expected_prepared_manifest_identity: dict[str, object] | None = None,
    expected_label: str | None = None,
    expected_run_key: str | None = None,
) -> list[SummaryRun]:
    """Load one run cache directory and return all segment variants."""
    return _load_summary_run_bundle(
        cache_dir,
        config,
        expected_modes=expected_modes,
        expected_summary_ids=expected_summary_ids,
        expected_summary_config_digest=expected_summary_config_digest,
        expected_run_fingerprint=expected_run_fingerprint,
        expected_prepared_manifest_identity=expected_prepared_manifest_identity,
        expected_label=expected_label,
        expected_run_key=expected_run_key,
        summary_spec_by_id=SUMMARY_SPEC_BY_ID,
    )


__all__ = [
    "DEFAULT_SUMMARY_IDS",
    "SCHEMA_VERSION",
    "SUMMARY_FILENAME_BY_ID",
    "SUMMARY_SPEC_BY_ID",
    "SUPPORTED_WEIGHTING_MODES",
    "SummaryCacheError",
    "SummaryRun",
    "SummarySpec",
    "build_mode_summaries",
    "build_mode_summaries_with_metadata",
    "build_run_fingerprint",
    "build_run_keys",
    "build_summaries",
    "build_summaries_with_metadata",
    "create_summary_run",
    "discover_cache_dirs",
    "load_summary_run_cache",
    "load_summary_run_bundle",
    "normalize_weighting_modes",
    "requested_summary_ids",
    "slugify",
    "strip_weights",
    "summary_file_map",
    "summary_root",
    "write_summary_run_cache",
    "write_summary_run_bundle",
]
