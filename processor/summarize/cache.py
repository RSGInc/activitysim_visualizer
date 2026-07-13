"""Summary cache serialization and loading."""

from __future__ import annotations

from pathlib import Path

from processor.cache_identity import build_run_fingerprint, build_run_keys, slugify
from processor.summarize import builder as summary_builder
from processor.summarize.cache_storage import (
    SCHEMA_VERSION,
    discover_cache_dirs,
    inspect_summary_run_bundle as _inspect_summary_run_bundle,
    load_summary_run_bundle as _load_summary_run_bundle,
    load_summary_run_cache as _load_summary_run_cache,
    summary_file_map as _summary_file_map,
    summary_root,
    write_summary_run_bundle as _write_summary_run_bundle,
    write_summary_run_cache as _write_summary_run_cache,
)
from processor.summarize.cache_types import (
    SummaryRun,
)
from processor.summarize.summary_specs import (
    SUMMARY_FILENAME_BY_ID,
    SUMMARY_SPEC_BY_ID,
)
from runtime.config import Config


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
        summary_digests=summary_builder.summary_digests(
            config,
            list(summary_run.summaries_by_mode.values())[0].keys(),
        ),
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
    requested_ids = list(next(iter(summary_runs[0].summaries_by_mode.values())).keys())
    return _write_summary_run_bundle(
        summary_runs,
        config,
        output_root=output_root,
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_digests=summary_builder.summary_digests(config, requested_ids),
        summary_filename_by_id=SUMMARY_FILENAME_BY_ID,
    )


def inspect_summary_run_bundle(
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
) -> dict[str, object]:
    return _inspect_summary_run_bundle(
        cache_dir,
        config,
        expected_modes=expected_modes,
        expected_summary_ids=expected_summary_ids,
        expected_summary_config_digest=expected_summary_config_digest,
        expected_run_fingerprint=expected_run_fingerprint,
        expected_prepared_manifest_identity=expected_prepared_manifest_identity,
        expected_label=expected_label,
        expected_run_key=expected_run_key,
        expected_summary_digests=summary_builder.summary_digests(
            config, expected_summary_ids
        ),
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
    "SCHEMA_VERSION",
    "SummaryRun",
    "build_run_fingerprint",
    "build_run_keys",
    "discover_cache_dirs",
    "inspect_summary_run_bundle",
    "load_summary_run_cache",
    "load_summary_run_bundle",
    "slugify",
    "summary_file_map",
    "summary_root",
    "write_summary_run_cache",
    "write_summary_run_bundle",
]
