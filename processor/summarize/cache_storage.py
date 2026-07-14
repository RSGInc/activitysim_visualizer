"""Summary cache persistence and manifest-loading helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from processor.cache_infra import (
    discover_manifest_cache_dirs,
    empty_sentinel_frame,
    is_empty_sentinel_frame,
    read_manifest,
    validate_schema_version,
    write_manifest,
)
from processor.summarize.cache_types import (
    SummaryCacheError,
    SummaryRun,
    normalize_weighting_modes,
)
from processor.summarize.csv_export import write_summary_csvs
from runtime.config import Config

SCHEMA_VERSION = 15


def summary_root(config: Config) -> Path:
    return Path(config.summary_root)


def summary_file_map(
    summary_ids: list[str],
    *,
    summary_filename_by_id: dict[str, str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for summary_id in summary_ids:
        mapping[summary_id] = summary_filename_by_id.get(
            summary_id, f"{summary_id}.csv"
        )
    return mapping


def _summary_state_for_table(table: pl.DataFrame) -> str:
    return "empty" if table.is_empty() else "available"


def _summary_storage_state(
    table: pl.DataFrame,
    metadata: dict[str, object],
) -> tuple[str, str]:
    state = str(metadata.get("state", _summary_state_for_table(table)))
    detail = str(metadata.get("detail", "")).strip()
    return state, detail


def _sentinel_summary_frame() -> pl.DataFrame:
    return empty_sentinel_frame()


def _build_mode_cache_payload(
    *,
    mode_tables: dict[str, pl.DataFrame],
    mode_metadata: dict[str, dict[str, object]],
    summary_filename_by_id: dict[str, str],
) -> dict[str, object]:
    file_tables: dict[str, pl.DataFrame] = {}
    summary_ids = list(mode_tables.keys())
    empty_summaries: list[str] = []
    summary_states: dict[str, str] = {}
    unavailable_summaries: list[str] = []
    failed_summaries: list[str] = []
    summary_diagnostics: dict[str, str] = {}

    for summary_id, table in mode_tables.items():
        filename = Path(
            summary_file_map(
                [summary_id], summary_filename_by_id=summary_filename_by_id
            )[summary_id]
        ).stem
        state, detail = _summary_storage_state(
            table,
            mode_metadata.get(summary_id, {}),
        )
        summary_states[summary_id] = state
        if detail:
            summary_diagnostics[summary_id] = detail
        if state == "unavailable":
            unavailable_summaries.append(summary_id)
        if state == "failed":
            failed_summaries.append(summary_id)
        if state in {"empty", "unavailable", "failed"} or table.width == 0:
            file_tables[filename] = _sentinel_summary_frame()
            empty_summaries.append(summary_id)
        else:
            file_tables[filename] = table

    return {
        "summary_ids": summary_ids,
        "file_tables": file_tables,
        "empty_summaries": empty_summaries,
        "summary_states": summary_states,
        "unavailable_summaries": unavailable_summaries,
        "failed_summaries": failed_summaries,
        "summary_diagnostics": summary_diagnostics,
    }


def _summary_manifest(
    *,
    summary_run: SummaryRun,
    config: Config,
    weighting_modes: list[str],
    summary_ids: list[str],
    empty_summaries: dict[str, list[str]],
    summary_states: dict[str, dict[str, str]],
    unavailable_summaries: dict[str, list[str]],
    failed_summaries: dict[str, list[str]],
    summary_diagnostics: dict[str, dict[str, str]],
    summary_digests: dict[str, dict[str, str]],
    run_fingerprint: dict[str, object] | None,
    prepared_manifest_identity: dict[str, object] | None,
    summary_filename_by_id: dict[str, str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "activitysim-visualizer-summary-cache",
        "label": summary_run.label,
        "run_key": summary_run.run_key,
        "source_run_dir": summary_run.source_run_dir,
        "config_path": config.config_path,
        "summary_config_digest": config.summary_config_digest,
        "weighting_modes": weighting_modes,
        "summary_ids": summary_ids,
        "summary_files": summary_file_map(
            summary_ids,
            summary_filename_by_id=summary_filename_by_id,
        ),
        "empty_summaries": empty_summaries,
        "summary_states": summary_states,
        "unavailable_summaries": unavailable_summaries,
        "failed_summaries": failed_summaries,
        "summary_diagnostics": summary_diagnostics,
        "summary_digests": summary_digests,
        "run_fingerprint": run_fingerprint or {},
        "prepared_manifest_identity": prepared_manifest_identity,
    }


def _segment_manifest_entry(
    *,
    summary_run: SummaryRun,
    weighting_modes: list[str],
    summary_states: dict[str, dict[str, str]],
    summary_diagnostics: dict[str, dict[str, str]],
    summary_digests: dict[str, dict[str, str]],
) -> dict[str, object]:
    summary_roots = {
        mode: f"summary_tables/{mode}/segments/{summary_run.segmentation_type}/{summary_run.segment_id}"
        for mode in weighting_modes
    }
    return {
        "segmentation_type": summary_run.segmentation_type,
        "segment_id": summary_run.segment_id,
        "segment_label": summary_run.segment_label,
        "is_full": summary_run.is_full_segment,
        "source_type": summary_run.segment_source_type,
        "segment_column": summary_run.segment_column,
        "segment_values": list(summary_run.segment_values),
        "source_table": summary_run.segment_source_table,
        "source_key_column": summary_run.segment_source_key_column,
        "csv_file": summary_run.segment_csv_file,
        "csv_key_column": summary_run.segment_csv_key_column,
        "csv_segment_value_column": summary_run.segment_csv_value_column,
        "summary_roots": summary_roots,
        "summary_states": summary_states,
        "summary_diagnostics": summary_diagnostics,
        "summary_digests": summary_digests,
    }


def write_summary_run_cache(
    summary_run: SummaryRun,
    config: Config,
    *,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    prepared_manifest_identity: dict[str, object] | None = None,
    summary_digests: dict[str, str] | None = None,
    summary_filename_by_id: dict[str, str],
) -> Path:
    """Write one run's summary cache directory and manifest."""
    output_root = Path(output_root) if output_root is not None else summary_root(config)
    output_root.mkdir(parents=True, exist_ok=True)

    run_dir = output_root / summary_run.run_key
    run_dir.mkdir(parents=True, exist_ok=True)

    weighting_modes = list(summary_run.summaries_by_mode.keys())
    summary_ids: list[str] = []
    empty_summaries: dict[str, list[str]] = {}
    summary_states: dict[str, dict[str, str]] = {}
    unavailable_summaries: dict[str, list[str]] = {}
    failed_summaries: dict[str, list[str]] = {}
    summary_diagnostics: dict[str, dict[str, str]] = {}
    manifest_summary_digests: dict[str, dict[str, str]] = {}
    for mode in weighting_modes:
        mode_payload = _build_mode_cache_payload(
            mode_tables=summary_run.summaries_by_mode[mode],
            mode_metadata=summary_run.summary_metadata_by_mode.get(mode, {}),
            summary_filename_by_id=summary_filename_by_id,
        )
        summary_ids = list(mode_payload["summary_ids"])
        empty_summaries[mode] = list(mode_payload["empty_summaries"])
        summary_states[mode] = dict(mode_payload["summary_states"])
        unavailable_summaries[mode] = list(mode_payload["unavailable_summaries"])
        failed_summaries[mode] = list(mode_payload["failed_summaries"])
        summary_diagnostics[mode] = dict(mode_payload["summary_diagnostics"])
        manifest_summary_digests[mode] = {
            summary_id: (summary_digests or {}).get(summary_id, "")
            for summary_id in summary_ids
        }
        write_summary_csvs(mode_payload["file_tables"], run_dir / mode)

    manifest = _summary_manifest(
        summary_run=summary_run,
        config=config,
        weighting_modes=weighting_modes,
        summary_ids=summary_ids,
        empty_summaries=empty_summaries,
        summary_states=summary_states,
        unavailable_summaries=unavailable_summaries,
        failed_summaries=failed_summaries,
        summary_diagnostics=summary_diagnostics,
        summary_digests=manifest_summary_digests,
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_filename_by_id=summary_filename_by_id,
    )
    write_manifest(run_dir, manifest)
    summary_run.manifest = manifest
    return run_dir


def write_summary_run_bundle(
    summary_runs: list[SummaryRun],
    config: Config,
    *,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    prepared_manifest_identity: dict[str, object] | None = None,
    summary_digests: dict[str, str] | None = None,
    summary_filename_by_id: dict[str, str],
) -> Path:
    """Write one run cache directory containing full and segmented summary outputs."""
    if not summary_runs:
        raise ValueError("summary_runs must not be empty.")
    output_root = Path(output_root) if output_root is not None else summary_root(config)
    output_root.mkdir(parents=True, exist_ok=True)

    run_key = summary_runs[0].run_key
    run_dir = output_root / run_key
    run_dir.mkdir(parents=True, exist_ok=True)

    weighting_modes = list(summary_runs[0].summaries_by_mode.keys())
    summary_ids = list(next(iter(summary_runs[0].summaries_by_mode.values())).keys())
    full_run = next((run for run in summary_runs if run.is_full_segment), None)
    if full_run is None:
        raise ValueError("summary_runs must include one global full summary run.")
    empty_summaries: dict[str, list[str]] = {}
    summary_states: dict[str, dict[str, str]] = {}
    unavailable_summaries: dict[str, list[str]] = {}
    failed_summaries: dict[str, list[str]] = {}
    summary_diagnostics: dict[str, dict[str, str]] = {}
    manifest_summary_digests: dict[str, dict[str, str]] = {}
    segmentation_type_entries: dict[str, dict[str, object]] = {}

    for summary_run in summary_runs:
        segment_states: dict[str, dict[str, str]] = {}
        segment_diagnostics: dict[str, dict[str, str]] = {}
        segment_digests: dict[str, dict[str, str]] = {}
        for mode in weighting_modes:
            mode_payload = _build_mode_cache_payload(
                mode_tables=summary_run.summaries_by_mode[mode],
                mode_metadata=summary_run.summary_metadata_by_mode.get(mode, {}),
                summary_filename_by_id=summary_filename_by_id,
            )
            if summary_run.is_full_segment and mode not in empty_summaries:
                empty_summaries[mode] = list(mode_payload["empty_summaries"])
                summary_states[mode] = dict(mode_payload["summary_states"])
                unavailable_summaries[mode] = list(
                    mode_payload["unavailable_summaries"]
                )
                failed_summaries[mode] = list(mode_payload["failed_summaries"])
                summary_diagnostics[mode] = dict(mode_payload["summary_diagnostics"])
                manifest_summary_digests[mode] = {
                    summary_id: (summary_digests or {}).get(summary_id, "")
                    for summary_id in summary_ids
                }
            segment_states[mode] = dict(mode_payload["summary_states"])
            segment_diagnostics[mode] = dict(mode_payload["summary_diagnostics"])
            segment_digests[mode] = {
                summary_id: (summary_digests or {}).get(summary_id, "")
                for summary_id in summary_ids
            }
            mode_dir = (
                run_dir / "summary_tables" / mode
                if summary_run.is_full_segment
                else run_dir
                / "summary_tables"
                / mode
                / "segments"
                / summary_run.segmentation_type
                / summary_run.segment_id
            )
            write_summary_csvs(mode_payload["file_tables"], mode_dir)
        if summary_run.is_full_segment:
            continue
        entry = segmentation_type_entries.setdefault(
            summary_run.segmentation_type,
            {
                "segmentation_type": summary_run.segmentation_type,
                "source_type": summary_run.segment_source_type,
                "segment_column": summary_run.segment_column,
                "source_table": summary_run.segment_source_table,
                "source_key_column": summary_run.segment_source_key_column,
                "csv_file": summary_run.segment_csv_file,
                "csv_key_column": summary_run.segment_csv_key_column,
                "csv_segment_value_column": summary_run.segment_csv_value_column,
                "include_full": False,
                "segments": [],
            },
        )
        entry["segments"].append(
            _segment_manifest_entry(
                summary_run=summary_run,
                weighting_modes=weighting_modes,
                summary_states=segment_states,
                summary_diagnostics=segment_diagnostics,
                summary_digests=segment_digests,
            )
        )

    manifest = _summary_manifest(
        summary_run=full_run,
        config=config,
        weighting_modes=weighting_modes,
        summary_ids=summary_ids,
        empty_summaries=empty_summaries,
        summary_states=summary_states,
        unavailable_summaries=unavailable_summaries,
        failed_summaries=failed_summaries,
        summary_diagnostics=summary_diagnostics,
        summary_digests=manifest_summary_digests,
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_filename_by_id=summary_filename_by_id,
    )
    manifest["segmentation_enabled"] = len(summary_runs) > 1
    manifest["segmentation_types"] = [
        segmentation_type_entries[key] for key in sorted(segmentation_type_entries)
    ]
    write_manifest(run_dir, manifest)
    for summary_run in summary_runs:
        summary_run.manifest = manifest
    return run_dir


def _validate_manifest_identity(
    *,
    cache_dir: Path,
    manifest: dict[str, object],
    expected_summary_config_digest: str | None,
    expected_run_fingerprint: dict[str, object] | None,
    expected_prepared_manifest_identity: dict[str, object] | None,
    expected_label: str | None,
    expected_run_key: str | None,
) -> None:
    if expected_label is not None and manifest.get("label") != expected_label:
        raise SummaryCacheError(
            f"Cache label mismatch in {cache_dir}: expected {expected_label!r}, found {manifest.get('label')!r}"
        )
    if expected_run_key is not None and manifest.get("run_key") != expected_run_key:
        raise SummaryCacheError(
            f"Cache run key mismatch in {cache_dir}: expected {expected_run_key!r}, found {manifest.get('run_key')!r}"
        )
    if (
        expected_summary_config_digest is not None
        and manifest.get("summary_config_digest") is not None
        and manifest.get("summary_config_digest") != expected_summary_config_digest
    ):
        raise SummaryCacheError(
            f"Cache summary config digest mismatch in {cache_dir}; summaries were built from a different summary configuration."
        )
    if expected_summary_config_digest is not None and manifest.get(
        "summary_config_digest"
    ) is None:
        raise SummaryCacheError(
            f"Cache {cache_dir} has no summary config digest. Rebuild its summaries."
        )
    if (
        expected_run_fingerprint is not None
        and manifest.get("run_fingerprint") != expected_run_fingerprint
    ):
        raise SummaryCacheError(
            f"Cache run fingerprint mismatch in {cache_dir}; summaries were built from different run inputs."
        )
    if expected_prepared_manifest_identity is not None:
        manifest_prepared_identity = manifest.get("prepared_manifest_identity")
        if manifest_prepared_identity is None:
            raise SummaryCacheError(
                f"Cache {cache_dir} predates prepared-manifest identity tracking. Rebuild summaries once to migrate to prepared-input-aware caches."
            )
        if manifest_prepared_identity != expected_prepared_manifest_identity:
            raise SummaryCacheError(
                f"Cache prepared manifest identity mismatch in {cache_dir}; summaries were built from different prepared inputs."
            )


def _validated_mode_and_summary_ids(
    *,
    manifest: dict[str, object],
    config: Config,
    cache_dir: Path,
    expected_modes: list[str] | None,
    expected_summary_ids: list[str] | None,
) -> tuple[list[str], list[str]]:
    resolved_expected_modes = normalize_weighting_modes(
        expected_modes or config.weighting_modes
    )
    manifest_modes = normalize_weighting_modes(
        [str(mode) for mode in manifest.get("weighting_modes", [])]
    )
    missing_modes = [
        mode for mode in resolved_expected_modes if mode not in manifest_modes
    ]
    if missing_modes:
        raise SummaryCacheError(
            f"Cache {cache_dir} is missing weighting modes: {missing_modes}"
        )

    manifest_summary_ids = [str(item) for item in manifest.get("summary_ids", [])]
    resolved_summary_ids = expected_summary_ids or manifest_summary_ids
    missing_summary_ids = [
        summary_id
        for summary_id in resolved_summary_ids
        if summary_id not in manifest_summary_ids
    ]
    if missing_summary_ids:
        raise SummaryCacheError(
            f"Cache {cache_dir} is missing summary tables: {missing_summary_ids}"
        )

    return resolved_expected_modes, resolved_summary_ids


def _manifest_summary_metadata(
    manifest: dict[str, object],
) -> tuple[
    dict[str, str],
    dict[str, list[str]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    summary_files = {
        str(summary_id): str(filename)
        for summary_id, filename in dict(manifest.get("summary_files", {})).items()
    }
    empty_summaries = {
        str(mode): [str(summary_id) for summary_id in summary_ids]
        for mode, summary_ids in dict(manifest.get("empty_summaries", {})).items()
    }
    manifest_summary_states = {
        str(mode): {
            str(summary_id): str(state)
            for summary_id, state in dict(mode_states).items()
        }
        for mode, mode_states in dict(manifest.get("summary_states", {})).items()
    }
    manifest_summary_diagnostics = {
        str(mode): {
            str(summary_id): str(detail)
            for summary_id, detail in dict(mode_details).items()
        }
        for mode, mode_details in dict(manifest.get("summary_diagnostics", {})).items()
    }
    manifest_summary_digests = {
        str(mode): {
            str(summary_id): str(digest)
            for summary_id, digest in dict(mode_digests).items()
        }
        for mode, mode_digests in dict(manifest.get("summary_digests", {})).items()
    }
    return (
        summary_files,
        empty_summaries,
        manifest_summary_states,
        manifest_summary_diagnostics,
        manifest_summary_digests,
    )


def _empty_summary_result(
    summary_id: str,
    *,
    summary_spec_by_id: dict[str, object],
) -> pl.DataFrame:
    spec = summary_spec_by_id.get(summary_id)
    if spec is None:
        return pl.DataFrame()
    return spec.empty()


def _loaded_summary_table(
    *,
    path: Path,
    mode: str,
    summary_id: str,
    empty_summaries: dict[str, list[str]],
    manifest_summary_states: dict[str, dict[str, str]],
    summary_spec_by_id: dict[str, object],
) -> tuple[pl.DataFrame, str]:
    is_declared_empty = summary_id in empty_summaries.get(mode, [])
    spec = summary_spec_by_id.get(summary_id)
    if is_declared_empty or spec is None:
        table = pl.read_csv(path, infer_schema_length=10000)
    else:
        table = pl.read_csv(
            path,
            infer_schema_length=10000,
            schema_overrides=dict(spec.contract.schema),
        )
    state = manifest_summary_states.get(mode, {}).get(summary_id)
    if state is None:
        state = "empty" if is_declared_empty else "available"
    if is_declared_empty and is_empty_sentinel_frame(table):
        table = _empty_summary_result(
            summary_id,
            summary_spec_by_id=summary_spec_by_id,
        )
    return table, state


def _load_mode_tables(
    *,
    mode_dir: Path,
    mode: str,
    expected_summary_ids: list[str],
    summary_files: dict[str, str],
    empty_summaries: dict[str, list[str]],
    manifest_summary_states: dict[str, dict[str, str]],
    manifest_summary_diagnostics: dict[str, dict[str, str]],
    summary_spec_by_id: dict[str, object],
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, object]]]:
    if not mode_dir.exists():
        raise SummaryCacheError(f"Missing mode directory: {mode_dir}")

    mode_tables: dict[str, pl.DataFrame] = {}
    mode_metadata: dict[str, dict[str, object]] = {}
    for summary_id in expected_summary_ids:
        filename = summary_files.get(summary_id, f"{summary_id}.csv")
        path = mode_dir / filename
        if not path.exists():
            raise SummaryCacheError(f"Missing summary CSV: {path}")
        table, state = _loaded_summary_table(
            path=path,
            mode=mode,
            summary_id=summary_id,
            empty_summaries=empty_summaries,
            manifest_summary_states=manifest_summary_states,
            summary_spec_by_id=summary_spec_by_id,
        )
        mode_tables[summary_id] = table
        mode_metadata[summary_id] = {"state": state}
        detail = manifest_summary_diagnostics.get(mode, {}).get(summary_id)
        if detail:
            mode_metadata[summary_id]["detail"] = detail
    return mode_tables, mode_metadata


def _segment_mode_dirs(
    cache_dir: Path,
    manifest: dict[str, object],
    expected_modes: list[str],
) -> list[tuple[str, dict[str, Path]]]:
    segment_dirs: list[tuple[str, dict[str, Path]]] = []
    segment_dirs.append(
        (
            "full",
            {
                mode: (
                    cache_dir / "summary_tables" / mode
                    if (cache_dir / "summary_tables" / mode).exists()
                    else cache_dir / mode
                )
                for mode in expected_modes
            },
        )
    )
    for group in list(manifest.get("segmentation_types", [])):
        group_dict = dict(group)
        for raw_segment in list(group_dict.get("segments", [])):
            segment = dict(raw_segment)
            segment_key = f"{group_dict.get('segmentation_type', 'full')}::{segment.get('segment_id', 'full')}"
            summary_roots = {
                str(mode): str(path)
                for mode, path in dict(segment.get("summary_roots", {})).items()
            }
            segment_dirs.append(
                (
                    segment_key,
                    {
                        mode: cache_dir
                        / Path(summary_roots.get(mode, f"summary_tables/{mode}"))
                        for mode in expected_modes
                    },
                )
            )
    return segment_dirs


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
    expected_summary_digests: dict[str, str] | None = None,
) -> dict[str, object]:
    cache_dir = Path(cache_dir)
    manifest = read_manifest(cache_dir, error_cls=SummaryCacheError)
    validate_schema_version(
        cache_dir=cache_dir,
        manifest=manifest,
        supported_versions={SCHEMA_VERSION, 14, 13, 12},
        error_factory=SummaryCacheError,
    )
    _validate_manifest_identity(
        cache_dir=cache_dir,
        manifest=manifest,
        expected_summary_config_digest=None,
        expected_run_fingerprint=expected_run_fingerprint,
        expected_prepared_manifest_identity=expected_prepared_manifest_identity,
        expected_label=expected_label,
        expected_run_key=expected_run_key,
    )
    expected_modes, manifest_summary_ids = _validated_mode_and_summary_ids(
        manifest=manifest,
        config=config,
        cache_dir=cache_dir,
        expected_modes=expected_modes,
        expected_summary_ids=None,
    )
    resolved_summary_ids = list(expected_summary_ids or manifest_summary_ids)
    (
        summary_files,
        _empty_summaries,
        _manifest_summary_states,
        _manifest_summary_diagnostics,
        manifest_summary_digests,
    ) = _manifest_summary_metadata(manifest)
    expected_summary_digests = dict(expected_summary_digests or {})
    stale_summary_ids: list[str] = []
    reusable_summary_ids: list[str] = []
    segment_dirs = _segment_mode_dirs(cache_dir, manifest, expected_modes)
    for summary_id in resolved_summary_ids:
        expected_digest = expected_summary_digests.get(summary_id)
        if expected_digest:
            manifest_digest = manifest_summary_digests.get(expected_modes[0], {}).get(
                summary_id
            )
            if manifest_digest != expected_digest:
                stale_summary_ids.append(summary_id)
                continue
        filename = summary_files.get(summary_id, f"{summary_id}.csv")
        is_reusable = True
        for _, mode_dirs in segment_dirs:
            for mode in expected_modes:
                if not (mode_dirs[mode] / filename).exists():
                    is_reusable = False
                    break
            if not is_reusable:
                break
        if is_reusable:
            reusable_summary_ids.append(summary_id)
        else:
            stale_summary_ids.append(summary_id)
    return {
        "manifest": manifest,
        "reusable_summary_ids": reusable_summary_ids,
        "stale_summary_ids": stale_summary_ids,
    }


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
    summary_spec_by_id: dict[str, object],
) -> SummaryRun:
    """Load and validate one run's summary cache directory."""
    cache_dir = Path(cache_dir)
    manifest = read_manifest(cache_dir, error_cls=SummaryCacheError)
    validate_schema_version(
        cache_dir=cache_dir,
        manifest=manifest,
        supported_versions={SCHEMA_VERSION, 14, 13, 12, 11, 6, 5, 2},
        error_factory=SummaryCacheError,
    )

    _validate_manifest_identity(
        cache_dir=cache_dir,
        manifest=manifest,
        expected_summary_config_digest=expected_summary_config_digest,
        expected_run_fingerprint=expected_run_fingerprint,
        expected_prepared_manifest_identity=expected_prepared_manifest_identity,
        expected_label=expected_label,
        expected_run_key=expected_run_key,
    )
    expected_modes, expected_summary_ids = _validated_mode_and_summary_ids(
        manifest=manifest,
        config=config,
        cache_dir=cache_dir,
        expected_modes=expected_modes,
        expected_summary_ids=expected_summary_ids,
    )
    (
        summary_files,
        empty_summaries,
        manifest_summary_states,
        manifest_summary_diagnostics,
        _,
    ) = _manifest_summary_metadata(manifest)

    summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
    for mode in expected_modes:
        mode_tables, mode_metadata = _load_mode_tables(
            mode_dir=cache_dir / mode,
            mode=mode,
            expected_summary_ids=expected_summary_ids,
            summary_files=summary_files,
            empty_summaries=empty_summaries,
            manifest_summary_states=manifest_summary_states,
            manifest_summary_diagnostics=manifest_summary_diagnostics,
            summary_spec_by_id=summary_spec_by_id,
        )
        summaries_by_mode[mode] = mode_tables
        summary_metadata_by_mode[mode] = mode_metadata

    return SummaryRun(
        label=str(manifest.get("label", cache_dir.name)),
        run_key=str(manifest.get("run_key", cache_dir.name)),
        summaries_by_mode=summaries_by_mode,
        summary_metadata_by_mode=summary_metadata_by_mode,
        source_run_dir=manifest.get("source_run_dir"),
        manifest=manifest,
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
    summary_spec_by_id: dict[str, object],
) -> list[SummaryRun]:
    """Load one run cache directory and return all persisted segment variants."""
    cache_dir = Path(cache_dir)
    manifest = read_manifest(cache_dir, error_cls=SummaryCacheError)
    if "segmentation_types" not in manifest and "segments" not in manifest:
        return [
            load_summary_run_cache(
                cache_dir,
                config,
                expected_modes=expected_modes,
                expected_summary_ids=expected_summary_ids,
                expected_summary_config_digest=expected_summary_config_digest,
                expected_run_fingerprint=expected_run_fingerprint,
                expected_prepared_manifest_identity=expected_prepared_manifest_identity,
                expected_label=expected_label,
                expected_run_key=expected_run_key,
                summary_spec_by_id=summary_spec_by_id,
            )
        ]

    validate_schema_version(
        cache_dir=cache_dir,
        manifest=manifest,
        supported_versions={SCHEMA_VERSION, 14, 13, 12},
        error_factory=SummaryCacheError,
    )
    _validate_manifest_identity(
        cache_dir=cache_dir,
        manifest=manifest,
        expected_summary_config_digest=expected_summary_config_digest,
        expected_run_fingerprint=expected_run_fingerprint,
        expected_prepared_manifest_identity=expected_prepared_manifest_identity,
        expected_label=expected_label,
        expected_run_key=expected_run_key,
    )
    expected_modes, expected_summary_ids = _validated_mode_and_summary_ids(
        manifest=manifest,
        config=config,
        cache_dir=cache_dir,
        expected_modes=expected_modes,
        expected_summary_ids=expected_summary_ids,
    )
    (
        summary_files,
        empty_summaries,
        manifest_summary_states,
        manifest_summary_diagnostics,
        _,
    ) = _manifest_summary_metadata(manifest)

    loaded_runs: list[SummaryRun] = []
    full_summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    full_summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
    for mode in expected_modes:
        full_mode_dir = cache_dir / "summary_tables" / mode
        if not full_mode_dir.exists():
            full_mode_dir = cache_dir / mode
        mode_tables, mode_metadata = _load_mode_tables(
            mode_dir=full_mode_dir,
            mode=mode,
            expected_summary_ids=expected_summary_ids,
            summary_files=summary_files,
            empty_summaries=empty_summaries,
            manifest_summary_states=manifest_summary_states,
            manifest_summary_diagnostics=manifest_summary_diagnostics,
            summary_spec_by_id=summary_spec_by_id,
        )
        full_summaries_by_mode[mode] = mode_tables
        full_summary_metadata_by_mode[mode] = mode_metadata
    loaded_runs.append(
        SummaryRun(
            label=str(manifest.get("label", cache_dir.name)),
            run_key=str(manifest.get("run_key", cache_dir.name)),
            summaries_by_mode=full_summaries_by_mode,
            summary_metadata_by_mode=full_summary_metadata_by_mode,
            segmentation_type="full",
            segment_id="full",
            segment_label="Full",
            is_full_segment=True,
            source_run_dir=manifest.get("source_run_dir"),
            manifest=manifest,
        )
    )
    if "segmentation_types" in manifest:
        segment_groups = []
        for raw_group in list(manifest.get("segmentation_types", [])):
            group = dict(raw_group)
            segmentation_type = str(group.get("segmentation_type", "full"))
            for raw_segment in list(group.get("segments", [])):
                segment_groups.append((segmentation_type, dict(raw_segment)))
    else:
        segment_groups = [
            (str(dict(raw_segment).get("segmentation_type", "full")), dict(raw_segment))
            for raw_segment in list(manifest.get("segments", []))
        ]
    for segmentation_type, segment in segment_groups:
        summary_roots = {
            str(mode): str(path)
            for mode, path in dict(segment.get("summary_roots", {})).items()
        }
        manifest_summary_states = {
            str(mode): {
                str(summary_id): str(state)
                for summary_id, state in dict(mode_states).items()
            }
            for mode, mode_states in dict(segment.get("summary_states", {})).items()
        }
        manifest_summary_diagnostics = {
            str(mode): {
                str(summary_id): str(detail)
                for summary_id, detail in dict(mode_details).items()
            }
            for mode, mode_details in dict(
                segment.get("summary_diagnostics", {})
            ).items()
        }
        empty_summaries = {
            mode: [
                summary_id
                for summary_id, state in manifest_summary_states.get(mode, {}).items()
                if state in {"empty", "unavailable", "failed"}
            ]
            for mode in expected_modes
        }
        summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
        summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
        for mode in expected_modes:
            mode_root = summary_roots.get(mode, f"summary_tables/{mode}")
            mode_tables, mode_metadata = _load_mode_tables(
                mode_dir=cache_dir / mode_root,
                mode=mode,
                expected_summary_ids=expected_summary_ids,
                summary_files=summary_files,
                empty_summaries=empty_summaries,
                manifest_summary_states=manifest_summary_states,
                manifest_summary_diagnostics=manifest_summary_diagnostics,
                summary_spec_by_id=summary_spec_by_id,
            )
            summaries_by_mode[mode] = mode_tables
            summary_metadata_by_mode[mode] = mode_metadata
        loaded_runs.append(
            SummaryRun(
                label=str(manifest.get("label", cache_dir.name)),
                run_key=str(manifest.get("run_key", cache_dir.name)),
                summaries_by_mode=summaries_by_mode,
                summary_metadata_by_mode=summary_metadata_by_mode,
                segmentation_type=segmentation_type,
                segment_id=str(segment.get("segment_id", "full")),
                segment_label=str(segment.get("segment_label", "Full")),
                is_full_segment=bool(segment.get("is_full", False)),
                segment_source_type=segment.get("source_type"),
                segment_column=segment.get("segment_column"),
                segment_values=tuple(segment.get("segment_values", [])),
                segment_source_table=segment.get("source_table"),
                segment_source_key_column=segment.get("source_key_column"),
                segment_csv_file=segment.get("csv_file"),
                segment_csv_key_column=segment.get("csv_key_column"),
                segment_csv_value_column=segment.get("csv_segment_value_column"),
                source_run_dir=manifest.get("source_run_dir"),
                manifest=manifest,
            )
        )
    return loaded_runs


def discover_cache_dirs(root: str | Path) -> list[Path]:
    """Return child cache directories that contain a manifest."""
    return discover_manifest_cache_dirs(root)
