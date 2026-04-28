"""Dashboard-owned data access models for summaries and optional prepared runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import polars as pl

from processor.models import RunData
from processor.summarize.cache import SummaryRun, strip_weights

PreparedRunAvailability = Literal["loaded", "unavailable", "not_requested"]
VisualizationAvailability = Literal[
    "available",
    "empty",
    "missing",
    "schema_mismatch",
    "unavailable",
    "failed",
]
VisualizationRenderState = Literal["rendered", "partial", "skipped"]


@dataclass(frozen=True)
class VisualizationRunAvailability:
    """One run's availability state for one dashboard visualization input."""

    label: str
    status: VisualizationAvailability
    detail: str
    source_kind: Literal["summary", "prepared"]
    source_id: str
    missing_columns: tuple[str, ...] = ()
    run_key: str | None = None
    source_run_dir: str | None = None


@dataclass(frozen=True)
class DashboardDataSelection:
    """Resolved usable/excluded dashboard inputs for one source table."""

    source_kind: Literal["summary", "prepared"]
    source_id: str
    usable_runs: list[tuple[str, Any]]
    excluded_runs: list[VisualizationRunAvailability]

    @property
    def has_usable_runs(self) -> bool:
        return bool(self.usable_runs)


@dataclass(frozen=True)
class VisualizationInputResult:
    """Combined run selection for one visualization across one or more inputs."""

    visualization_id: str
    input_kind: Literal["summary", "prepared", "mixed"]
    usable_by_input: dict[str, list[tuple[str, Any]]]
    excluded_runs: list[VisualizationRunAvailability]
    input_ids: tuple[str, ...]

    @property
    def has_usable_runs(self) -> bool:
        return bool(self.usable_by_input) and all(self.usable_by_input.values())


@dataclass(frozen=True)
class VisualizationDiagnostic:
    """Serialized-ready diagnostic record for one visualization render."""

    visualization_id: str
    render_state: VisualizationRenderState
    input_kind: Literal["summary", "prepared", "mixed"]
    input_ids: tuple[str, ...]
    usable_run_labels: tuple[str, ...]
    excluded_runs: tuple[VisualizationRunAvailability, ...]


@dataclass(frozen=True)
class DashboardSummarySeries:
    """Summary tables available for one run in dashboard-friendly form."""

    label: str
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]]
    summary_metadata_by_mode: dict[str, dict[str, dict[str, object]]] = field(
        default_factory=dict
    )
    run_key: str | None = None
    source_run_dir: str | None = None

    @classmethod
    def from_summary_run(
        cls,
        summary_run: SummaryRun,
    ) -> "DashboardSummarySeries":
        return cls(
            label=summary_run.label,
            summaries_by_mode=summary_run.summaries_by_mode,
            summary_metadata_by_mode=summary_run.summary_metadata_by_mode,
            run_key=summary_run.run_key,
            source_run_dir=summary_run.source_run_dir,
        )

    def has_table(self, summary_name: str, weighting_key: str) -> bool:
        mode_tables = self.summaries_by_mode.get(weighting_key)
        return mode_tables is not None and summary_name in mode_tables

    def get_table(
        self,
        summary_name: str,
        weighting_key: str,
    ) -> pl.DataFrame | None:
        mode_tables = self.summaries_by_mode.get(weighting_key)
        if mode_tables is None:
            return None
        return mode_tables.get(summary_name)

    def get_summary_metadata(
        self,
        summary_name: str,
        weighting_key: str,
    ) -> dict[str, object] | None:
        mode_metadata = self.summary_metadata_by_mode.get(weighting_key)
        if mode_metadata is None:
            return None
        metadata = mode_metadata.get(summary_name)
        return dict(metadata) if metadata is not None else None


@dataclass
class DashboardPreparedRunProvider:
    """Prepared-run access for dashboard pages that need disaggregate data."""

    availability: PreparedRunAvailability
    weighted_runs: list[tuple[str, RunData]] = field(default_factory=list)
    _unweighted_runs: list[tuple[str, RunData]] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @classmethod
    def loaded(
        cls,
        runs: list[tuple[str, RunData]] | None,
    ) -> "DashboardPreparedRunProvider":
        return cls("loaded", weighted_runs=list(runs or []))

    @classmethod
    def unavailable(cls) -> "DashboardPreparedRunProvider":
        return cls("unavailable")

    @classmethod
    def not_requested(cls) -> "DashboardPreparedRunProvider":
        return cls("not_requested")

    @property
    def is_loaded(self) -> bool:
        return self.availability == "loaded"

    def labels(self) -> list[str]:
        if not self.is_loaded:
            return []
        return [label for label, _ in self.weighted_runs]

    def get_runs_if_loaded(
        self,
        *,
        weighted: bool = True,
    ) -> list[tuple[str, RunData]] | None:
        if not self.is_loaded:
            return None
        if weighted:
            return list(self.weighted_runs)
        if self._unweighted_runs is None:
            self._unweighted_runs = [
                (label, strip_weights(rd)) for label, rd in self.weighted_runs
            ]
        return list(self._unweighted_runs)
