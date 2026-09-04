"""Summary cache serialization and loading."""

from __future__ import annotations

from pathlib import Path

from processor.analysis_units import AnalysisUnit
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
from processor.summarize.catalog import (
    SUMMARY_FILENAME_BY_ID,
    SUMMARY_BY_ID,
)
from runtime.config import Config
from runtime.config.signatures import segmentation_unit_signature_payload


def analysis_unit_key(*, segmentation_type: str, segment_id: str) -> str:
    return f"{segmentation_type}::{segment_id}"


def _analysis_unit_summary_digests(
    config: Config,
    *,
    segmentation_type: str,
    segment_id: str,
    summary_ids: list[str],
) -> dict[str, str]:
    identity = None
    if (segmentation_type, segment_id) != ("full", "full"):
        identity = segmentation_unit_signature_payload(
            config,
            segmentation_type=segmentation_type,
            segment_id=segment_id,
        )
    return summary_builder.summary_digests(
        config,
        summary_ids,
        analysis_unit_identity=identity,
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
        summary_spec_by_id=SUMMARY_BY_ID,
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
    summary_digests_by_unit = {
        analysis_unit_key(
            segmentation_type=summary_run.segmentation_type,
            segment_id=summary_run.segment_id,
        ): _analysis_unit_summary_digests(
            config,
            segmentation_type=summary_run.segmentation_type,
            segment_id=summary_run.segment_id,
            summary_ids=requested_ids,
        )
        for summary_run in summary_runs
    }
    return _write_summary_run_bundle(
        summary_runs,
        config,
        output_root=output_root,
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_digests_by_unit=summary_digests_by_unit,
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
    expected_analysis_units: list[AnalysisUnit] | None = None,
) -> dict[str, object]:
    requested_ids = list(expected_summary_ids or summary_builder.DEFAULT_SUMMARY_IDS)
    if expected_analysis_units is not None:
        unit_keys = [
            (unit.segmentation_type, unit.segment_id)
            for unit in expected_analysis_units
        ]
    elif config.segmentation.enabled:
        unit_keys = [
            ("full", "full"),
            *[
                (definition.name, segment.id)
                for definition in config.segmentation.definitions
                for segment in definition.segments
            ],
        ]
    else:
        unit_keys = [("full", "full")]
    expected_summary_digests_by_unit = {
        analysis_unit_key(
            segmentation_type=segmentation_type,
            segment_id=segment_id,
        ): _analysis_unit_summary_digests(
            config,
            segmentation_type=segmentation_type,
            segment_id=segment_id,
            summary_ids=requested_ids,
        )
        for segmentation_type, segment_id in unit_keys
    }
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
        expected_summary_digests_by_unit=expected_summary_digests_by_unit,
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
    expected_summary_ids_by_unit: dict[str, list[str]] | None = None,
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
        expected_summary_ids_by_unit=expected_summary_ids_by_unit,
        summary_spec_by_id=SUMMARY_BY_ID,
    )


__all__ = [
    "SCHEMA_VERSION",
    "SummaryRun",
    "analysis_unit_key",
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
