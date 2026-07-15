"""Shared summary cache types and weighting-mode helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from processor.models import RunData
from runtime.weighting import WEIGHTING_MODES, normalize_weighting_modes


class SummaryCacheError(RuntimeError):
    """Raised when a summary cache directory is invalid or incomplete."""


@dataclass
class SummaryRun:
    """One run's summary tables grouped by weighting mode."""

    label: str
    run_key: str
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]]
    summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] = field(
        default_factory=dict
    )
    segmentation_type: str = "full"
    segment_id: str = "full"
    segment_label: str = "Full"
    is_full_segment: bool = True
    segment_source_type: str | None = None
    segment_column: str | None = None
    segment_values: tuple[object, ...] = ()
    segment_source_table: str | None = None
    segment_source_key_column: str | None = None
    segment_csv_file: str | None = None
    segment_csv_key_column: str | None = None
    segment_csv_value_column: str | None = None
    source_run_dir: str | None = None
    manifest: dict[str, object] | None = None


def strip_weights(rd: RunData) -> RunData:
    """Return a copy of ``RunData`` with all ``finalweight`` values reset to 1.0."""
    return WEIGHTING_MODES.get("unweighted").apply(rd, None)


def create_summary_run(
    *,
    label: str,
    run_key: str,
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]],
    summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] | None = None,
    segmentation_type: str = "full",
    segment_id: str = "full",
    segment_label: str = "Full",
    is_full_segment: bool = True,
    segment_source_type: str | None = None,
    segment_column: str | None = None,
    segment_values: tuple[object, ...] = (),
    segment_source_table: str | None = None,
    segment_source_key_column: str | None = None,
    segment_csv_file: str | None = None,
    segment_csv_key_column: str | None = None,
    segment_csv_value_column: str | None = None,
    source_run_dir: str | None = None,
    manifest: dict[str, object] | None = None,
) -> SummaryRun:
    """Package a run's summary tables into the shared ``SummaryRun`` wrapper."""
    return SummaryRun(
        label=label,
        run_key=run_key,
        summaries_by_mode=summaries_by_mode,
        summary_metadata_by_mode=dict(summary_metadata_by_mode or {}),
        segmentation_type=segmentation_type,
        segment_id=segment_id,
        segment_label=segment_label,
        is_full_segment=is_full_segment,
        segment_source_type=segment_source_type,
        segment_column=segment_column,
        segment_values=tuple(segment_values),
        segment_source_table=segment_source_table,
        segment_source_key_column=segment_source_key_column,
        segment_csv_file=segment_csv_file,
        segment_csv_key_column=segment_csv_key_column,
        segment_csv_value_column=segment_csv_value_column,
        source_run_dir=source_run_dir,
        manifest=manifest,
    )


__all__ = [
    "SummaryCacheError",
    "SummaryRun",
    "create_summary_run",
    "normalize_weighting_modes",
    "strip_weights",
]
