"""Shared summary cache types and weighting-mode helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from processor.models import RunData, SkimjoinArtifacts, TableAvailabilityMetadata

SUPPORTED_WEIGHTING_MODES = ("weighted", "unweighted")


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


def normalize_weighting_modes(modes: list[str] | None) -> list[str]:
    """Validate, normalize, and deduplicate weighting mode names."""
    if not modes:
        modes = list(SUPPORTED_WEIGHTING_MODES)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_mode in modes:
        mode = str(raw_mode).strip().lower()
        if mode not in SUPPORTED_WEIGHTING_MODES:
            raise ValueError(
                f"Unsupported weighting mode {raw_mode!r}. Supported modes: {SUPPORTED_WEIGHTING_MODES}"
            )
        if mode not in seen:
            normalized.append(mode)
            seen.add(mode)
    return normalized


def strip_weights(rd: RunData) -> RunData:
    """Return a copy of ``RunData`` with all ``finalweight`` values reset to 1.0."""

    def _reset(df: pl.DataFrame) -> pl.DataFrame:
        if "finalweight" in df.columns:
            return df.with_columns(pl.lit(1.0).alias("finalweight"))
        return df

    return RunData(
        label=rd.label,
        run_dir=rd.run_dir,
        skim_file=rd.skim_file,
        hh=_reset(rd.hh),
        per=_reset(rd.per),
        day=_reset(rd.day),
        tours=_reset(rd.tours),
        trips=_reset(rd.trips),
        vehicles=_reset(rd.vehicles),
        trip_hypothetical_skims=_reset(rd.trip_hypothetical_skims),
        tour_hypothetical_skims=_reset(rd.tour_hypothetical_skims),
        joint_participants=rd.joint_participants,
        land_use=rd.land_use,
        skim_matrix=rd.skim_matrix,
        skim_zone_map=rd.skim_zone_map,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
        table_availability_metadata=TableAvailabilityMetadata(
            states=dict(rd.table_availability_metadata.states),
            diagnostics=dict(rd.table_availability_metadata.diagnostics),
        ),
        skimjoin_artifacts=SkimjoinArtifacts(
            manifest=dict(rd.skimjoin_artifacts.manifest),
            reports=dict(rd.skimjoin_artifacts.reports),
        ),
        skimjoin_manifest=dict(rd.skimjoin_manifest),
        skimjoin_reports=dict(rd.skimjoin_reports),
    )


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
    "SUPPORTED_WEIGHTING_MODES",
    "SummaryCacheError",
    "SummaryRun",
    "create_summary_run",
    "normalize_weighting_modes",
    "strip_weights",
]
