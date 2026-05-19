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
from processor.summarize.contracts import empty_summary_frame
from processor.summarize.writer import write_all
from runtime.config import Config

SCHEMA_VERSION = 11


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
            summary_file_map([summary_id], summary_filename_by_id=summary_filename_by_id)[
                summary_id
            ]
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
        "run_fingerprint": run_fingerprint or {},
        "prepared_manifest_identity": prepared_manifest_identity,
    }


def write_summary_run_cache(
    summary_run: SummaryRun,
    config: Config,
    *,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    prepared_manifest_identity: dict[str, object] | None = None,
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
        write_all(mode_payload["file_tables"], run_dir / mode)

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
        run_fingerprint=run_fingerprint,
        prepared_manifest_identity=prepared_manifest_identity,
        summary_filename_by_id=summary_filename_by_id,
    )
    write_manifest(run_dir, manifest)
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
    if (
        expected_summary_config_digest is not None
        and manifest.get("summary_config_digest") is None
        and manifest.get("config_digest") is not None
    ):
        raise SummaryCacheError(
            f"Cache {cache_dir} uses a legacy full-config digest. Rebuild summaries once to migrate to presentation-safe caches."
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
    missing_modes = [mode for mode in resolved_expected_modes if mode not in manifest_modes]
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
    return (
        summary_files,
        empty_summaries,
        manifest_summary_states,
        manifest_summary_diagnostics,
    )


def _empty_summary_result(
    summary_id: str,
    *,
    summary_spec_by_id: dict[str, object],
) -> pl.DataFrame:
    spec = summary_spec_by_id.get(summary_id)
    if spec is None:
        return pl.DataFrame()
    return empty_summary_frame(spec.builder)


def _loaded_summary_table(
    *,
    path: Path,
    mode: str,
    summary_id: str,
    empty_summaries: dict[str, list[str]],
    manifest_summary_states: dict[str, dict[str, str]],
    summary_spec_by_id: dict[str, object],
) -> tuple[pl.DataFrame, str]:
    table = pl.read_csv(path, infer_schema_length=10000)
    state = manifest_summary_states.get(mode, {}).get(summary_id)
    if state is None:
        state = "empty" if summary_id in empty_summaries.get(mode, []) else "available"
    if summary_id in empty_summaries.get(mode, []) and is_empty_sentinel_frame(table):
        table = _empty_summary_result(
            summary_id,
            summary_spec_by_id=summary_spec_by_id,
        )
    return table, state


def _load_mode_tables(
    *,
    cache_dir: Path,
    mode: str,
    expected_summary_ids: list[str],
    summary_files: dict[str, str],
    empty_summaries: dict[str, list[str]],
    manifest_summary_states: dict[str, dict[str, str]],
    manifest_summary_diagnostics: dict[str, dict[str, str]],
    summary_spec_by_id: dict[str, object],
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, object]]]:
    mode_dir = cache_dir / mode
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
        supported_versions={SCHEMA_VERSION, 6, 5, 2},
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
    ) = _manifest_summary_metadata(manifest)

    summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
    for mode in expected_modes:
        mode_tables, mode_metadata = _load_mode_tables(
            cache_dir=cache_dir,
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


def discover_cache_dirs(root: str | Path) -> list[Path]:
    """Return child cache directories that contain a manifest."""
    return discover_manifest_cache_dirs(root)
