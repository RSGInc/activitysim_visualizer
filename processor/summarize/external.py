"""Load user-supplied dashboard-ready summary tables."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from processor.cache_identity import file_identity
from processor.summarize.cache_types import SummaryRun, create_summary_run
from processor.summarize.contracts import get_summary_contract
from processor.summarize.summary_specs import SUMMARY_SPEC_BY_ID
from runtime.config import Config


def summary_table_map_identity(
    summary_table_map: dict[str, str] | None,
) -> dict[str, object] | None:
    """Return stable identity metadata for user-supplied summary files."""
    if not summary_table_map:
        return None
    normalized = dict(sorted(summary_table_map.items()))
    missing_paths = [
        f"{summary_id}: {path}"
        for summary_id, path in normalized.items()
        if not Path(path).exists()
    ]
    if missing_paths:
        raise ValueError(
            "summary_table_map references missing files: "
            + "; ".join(missing_paths)
        )
    return {
        "summary_table_map": normalized,
        "summary_table_fingerprints": {
            summary_id: file_identity(path)
            for summary_id, path in normalized.items()
        },
    }


def validate_summary_table_map_ids(
    summary_table_map: dict[str, str] | None,
    *,
    field_name: str = "summary_table_map",
) -> None:
    """Reject user-supplied mappings for unknown summary ids."""
    unknown_ids = [
        summary_id
        for summary_id in sorted(summary_table_map or {})
        if summary_id not in SUMMARY_SPEC_BY_ID
    ]
    if unknown_ids:
        raise ValueError(
            f"{field_name} contains unsupported summary ids: "
            + ", ".join(repr(summary_id) for summary_id in unknown_ids)
        )


def _read_summary_table(path: str | Path) -> pl.DataFrame:
    resolved = Path(path)
    suffix = resolved.suffix.lower()
    if suffix == ".csv":
        return pl.read_csv(resolved, infer_schema_length=10000)
    if suffix == ".parquet":
        return pl.read_parquet(resolved)
    raise ValueError(f"Summary table path must end with '.csv' or '.parquet': {path}")


def _validate_summary_columns(summary_id: str, table: pl.DataFrame) -> None:
    contract = get_summary_contract(SUMMARY_SPEC_BY_ID[summary_id].builder)
    if contract is None:
        return
    missing_columns = [
        column for column in contract.columns if column not in table.columns
    ]
    if missing_columns:
        raise ValueError(
            f"summary_table_map[{summary_id!r}] is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )


def load_summary_table_map(
    *,
    summary_table_map: dict[str, str],
    label: str,
    run_key: str,
    config: Config,
    source_run_dir: str | None = None,
) -> SummaryRun:
    """Load one run's mapped summary files into a full-segment ``SummaryRun``."""
    validate_summary_table_map_ids(summary_table_map)
    tables: dict[str, pl.DataFrame] = {}
    metadata: dict[str, dict[str, object]] = {}
    for summary_id, path in sorted(summary_table_map.items()):
        table_path = Path(path)
        if not table_path.exists():
            raise ValueError(f"summary_table_map[{summary_id!r}] does not exist: {path}")
        table = _read_summary_table(table_path)
        _validate_summary_columns(summary_id, table)
        tables[summary_id] = table
        metadata[summary_id] = {
            "state": "empty" if table.is_empty() else "available",
            "source": "summary_table_map",
            "source_file": str(table_path.resolve()),
        }

    summaries_by_mode = {mode: dict(tables) for mode in config.weighting_modes}
    metadata_by_mode = {mode: dict(metadata) for mode in config.weighting_modes}
    return create_summary_run(
        label=label,
        run_key=run_key,
        summaries_by_mode=summaries_by_mode,
        summary_metadata_by_mode=metadata_by_mode,
        source_run_dir=source_run_dir,
    )


def merge_summary_table_map_run(
    base_runs: list[SummaryRun],
    external_run: SummaryRun | None,
) -> list[SummaryRun]:
    """Overlay user-supplied run-level summaries onto generated/cache summaries."""
    if external_run is None:
        return base_runs
    if not base_runs:
        return [external_run]

    merged: list[SummaryRun] = []
    overlaid = False
    for base_run in base_runs:
        if base_run.run_key != external_run.run_key:
            merged.append(base_run)
            continue
        summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
        metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
        for mode, base_tables in base_run.summaries_by_mode.items():
            external_tables = external_run.summaries_by_mode.get(mode, {})
            summaries_by_mode[mode] = {**base_tables, **external_tables}
            metadata_by_mode[mode] = {
                **base_run.summary_metadata_by_mode.get(mode, {}),
                **external_run.summary_metadata_by_mode.get(mode, {}),
            }
        merged.append(
            create_summary_run(
                label=base_run.label,
                run_key=base_run.run_key,
                summaries_by_mode=summaries_by_mode,
                summary_metadata_by_mode=metadata_by_mode,
                segmentation_type=base_run.segmentation_type,
                segment_id=base_run.segment_id,
                segment_label=base_run.segment_label,
                is_full_segment=base_run.is_full_segment,
                segment_source_type=base_run.segment_source_type,
                segment_column=base_run.segment_column,
                segment_values=base_run.segment_values,
                segment_source_table=base_run.segment_source_table,
                segment_source_key_column=base_run.segment_source_key_column,
                segment_csv_file=base_run.segment_csv_file,
                segment_csv_key_column=base_run.segment_csv_key_column,
                segment_csv_value_column=base_run.segment_csv_value_column,
                source_run_dir=base_run.source_run_dir,
                manifest=base_run.manifest,
            )
        )
        overlaid = True
    if not overlaid:
        merged.append(external_run)
    return merged


__all__ = [
    "load_summary_table_map",
    "merge_summary_table_map_run",
    "summary_table_map_identity",
    "validate_summary_table_map_ids",
]
