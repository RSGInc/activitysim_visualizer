"""Analysis-unit metadata used by segmentation-aware summary workflows."""

from __future__ import annotations

from dataclasses import dataclass

from processor.models import RunData


@dataclass(frozen=True)
class SegmentMetadata:
    """Resolved segment metadata carried with one sliced analysis unit."""

    segment_id: str
    segment_label: str
    is_full: bool
    source_type: str | None = None
    column: str | None = None
    values: tuple[object, ...] = ()
    source_table: str | None = None
    source_key_column: str | None = None
    csv_file: str | None = None
    csv_key_column: str | None = None
    csv_segment_value_column: str | None = None


@dataclass(frozen=True)
class AnalysisUnit:
    """One prepared run slice to be summarized independently."""

    run_id: str
    run_name: str
    run_key: str
    segment_id: str
    segment_label: str
    is_full: bool
    segment_metadata: SegmentMetadata
    prepared_run: RunData


def full_segment_metadata() -> SegmentMetadata:
    """Return the canonical metadata for the full, unsegmented analysis unit."""
    return SegmentMetadata(
        segment_id="full",
        segment_label="Full",
        is_full=True,
    )


def full_analysis_unit(
    *,
    run_key: str,
    run_name: str,
    prepared_run: RunData,
) -> AnalysisUnit:
    """Wrap one prepared run as the full analysis unit."""
    metadata = full_segment_metadata()
    return AnalysisUnit(
        run_id=run_key,
        run_name=run_name,
        run_key=run_key,
        segment_id=metadata.segment_id,
        segment_label=metadata.segment_label,
        is_full=True,
        segment_metadata=metadata,
        prepared_run=prepared_run,
    )
