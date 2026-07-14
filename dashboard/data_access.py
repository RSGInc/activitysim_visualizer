"""Dashboard-owned data access models for summaries and optional prepared runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Literal, TYPE_CHECKING

import polars as pl

from processor.models import RunData
from processor.summarize.cache_types import SummaryRun, strip_weights

if TYPE_CHECKING:
    from dashboard.state import DashboardState

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
RunTableData = Iterable[tuple[str, pl.DataFrame]]


@dataclass(frozen=True)
class RunTables:
    """Canonical multi-run table value used from lookup through rendering.

    Run labels, usable frames, and structured availability issues travel together.
    The object is iterable for domain helpers, while fluent methods preserve the
    metadata needed by the page rendering boundary.
    """

    runs: tuple[tuple[str, pl.DataFrame], ...]
    issues: tuple["VisualizationRunAvailability", ...] = ()
    source_ids: tuple[str, ...] = ()

    @classmethod
    def from_runs(
        cls,
        runs: RunTableData | None,
        *,
        issues: Iterable["VisualizationRunAvailability"] = (),
        source_ids: Iterable[str] = (),
    ) -> "RunTables":
        return cls(
            tuple((label, frame) for label, frame in (runs or []) if not frame.is_empty()),
            tuple(issues),
            tuple(source_ids),
        )

    def __iter__(self) -> Iterator[tuple[str, pl.DataFrame]]:
        return iter(self.runs)

    def __len__(self) -> int:
        return len(self.runs)

    def __bool__(self) -> bool:
        return bool(self.runs)

    def __getitem__(self, index):
        return self.runs[index]

    @property
    def available(self) -> bool:
        return bool(self.runs)

    @property
    def partial(self) -> bool:
        return bool(self.runs) and bool(self.issues)

    def to_list(self) -> list[tuple[str, pl.DataFrame]]:
        """Materialize tuples only for external APIs that cannot accept RunTables."""
        return list(self.runs)

    def _replace(self, runs: Iterable[tuple[str, pl.DataFrame]]) -> "RunTables":
        return RunTables(tuple(runs), self.issues, self.source_ids)

    def requiring(self, *columns: str) -> "RunTables":
        """Keep runs whose table contains every requested column."""
        required = set(columns)
        return self._replace(
                (label, frame)
                for label, frame in self.runs
                if required.issubset(frame.columns)
        )

    def drop_empty(self) -> "RunTables":
        """Remove runs made empty by an earlier query operation."""
        return self._replace(
            (label, frame) for label, frame in self.runs if not frame.is_empty()
        )

    def map(self, transform: Callable[[pl.DataFrame], pl.DataFrame]) -> "RunTables":
        return self._replace(
            (label, transform(frame)) for label, frame in self.runs
        )

    def where(self, **equals: object) -> "RunTables":
        """Filter each run using column equality or membership constraints."""

        def filter_frame(frame: pl.DataFrame) -> pl.DataFrame:
            predicate: pl.Expr | None = None
            for column, value in equals.items():
                values = value if isinstance(value, (list, tuple, set, frozenset)) else None
                condition = (
                    pl.col(column).is_in(list(values))
                    if values is not None
                    else pl.col(column) == value
                )
                predicate = condition if predicate is None else predicate & condition
            return frame if predicate is None else frame.filter(predicate)

        return self.map(filter_frame)

    def with_columns(self, *expressions: pl.Expr) -> "RunTables":
        return self.map(lambda frame: frame.with_columns(*expressions))

    def select(self, *expressions: str | pl.Expr) -> "RunTables":
        return self.map(lambda frame: frame.select(*expressions))

    def sort(self, *by: str | pl.Expr) -> "RunTables":
        return self.map(lambda frame: frame.sort(*by))

    def group(self, by: str | Iterable[str], *aggregations: pl.Expr, **named_aggregations: pl.Expr) -> "RunTables":
        aggregations = (*aggregations, *(expr.alias(name) for name, expr in named_aggregations.items()))
        return self.map(lambda frame: frame.group_by(by).agg(*aggregations))

    def join(
        self,
        other: "RunTables",
        *,
        on: str | list[str],
        how: str = "left",
        coalesce: bool | None = None,
    ) -> "RunTables":
        """Join tables with the corresponding run from another view."""
        other_by_label = dict(other.runs)
        combined_issues = tuple(dict.fromkeys((*self.issues, *other.issues)))
        combined_sources = tuple(dict.fromkeys((*self.source_ids, *other.source_ids)))
        return RunTables(
            tuple(
                (
                    label,
                    frame.join(
                        other_by_label[label],
                        on=on,
                        how=how,
                        coalesce=coalesce,
                    ),
                )
                for label, frame in self.runs
                if label in other_by_label
            ),
            combined_issues,
            combined_sources,
        )

    def values(self, column: str) -> list[object]:
        """Return distinct non-null values in first-seen run order."""
        values: list[object] = []
        for _, frame in self.runs:
            if column not in frame.columns:
                continue
            for value in frame.get_column(column).drop_nulls().unique(maintain_order=True):
                if value not in values:
                    values.append(value)
        return values

    def scalar(self, column: str, *, default: object = None) -> list[tuple[str, object]]:
        """Return the first value of a column for each usable run."""
        return [
            (label, frame[column][0] if column in frame.columns and len(frame) else default)
            for label, frame in self.runs
        ]


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


class PageData:
    """The single dashboard-page gateway for summary and prepared data."""

    def __init__(
        self,
        state: "DashboardState",
        *,
        weighting_key: Callable[[], str],
        required_summary_ids: Callable[[], tuple[str, ...]],
        record_selection: Callable[[str, DashboardDataSelection], None],
        warn_missing: Callable[[str], None],
        warn_missing_prepared: Callable[[], None],
    ) -> None:
        self._state = state
        self._weighting_key = weighting_key
        self._required_summary_ids = required_summary_ids
        self._record_selection = record_selection
        self._warn_missing = warn_missing
        self._warn_missing_prepared = warn_missing_prepared

    def summary(
        self,
        summary_id: str,
        weighting: str | None = None,
        *,
        columns: Iterable[str] = (),
        required: bool | None = None,
    ) -> RunTables:
        """Resolve one summary into a queryable multi-run table value."""
        selection = self._state.inspect_summary_table(
            summary_id,
            weighting_key=weighting or self._weighting_key(),
            required_columns=tuple(columns),
        )
        self._record_selection(summary_id, selection)
        is_required = (
            summary_id in self._required_summary_ids()
            if required is None
            else required
        )
        if is_required and not selection.has_usable_runs:
            self._warn_missing(summary_id)
        return RunTables.from_runs(
            selection.usable_runs,
            issues=selection.excluded_runs,
            source_ids=(summary_id,),
        )

    def summaries(
        self,
        *summary_ids: str,
        columns: dict[str, Iterable[str]] | None = None,
        required: bool | None = None,
    ) -> dict[str, RunTables]:
        """Resolve several summaries through the same availability contract."""
        columns = columns or {}
        return {
            summary_id: self.summary(
                summary_id,
                columns=columns.get(summary_id, ()),
                required=required,
            )
            for summary_id in summary_ids
        }

    def prepared(
        self,
        table_name: str,
        *,
        columns: Iterable[str] = (),
        weighted: bool | None = None,
    ) -> RunTables:
        """Resolve one prepared table without exposing RunData to ordinary pages."""
        selection = self._state.inspect_prepared_table(
            table_name,
            weighted=weighted,
            required_columns=tuple(columns),
        )
        self._record_selection(table_name, selection)
        if not selection.has_usable_runs:
            self._warn_missing_prepared()
        frames = (
            (label, getattr(run, table_name))
            for label, run in selection.usable_runs
        )
        return RunTables.from_runs(
            frames,
            issues=selection.excluded_runs,
            source_ids=(table_name,),
        )

    def prepared_runs(
        self,
        *,
        weighted: bool | None = None,
    ) -> list[tuple[str, RunData]] | None:
        """Escape hatch for skim features that require matrices on RunData."""
        runs = self._state.get_prepared_runs_if_loaded(weighted=weighted)
        if runs is None:
            self._warn_missing_prepared()
        return runs

    def summary_series(
        self,
        summary_id: str,
        *,
        weighting: str | None = None,
    ) -> list[tuple[str, "DashboardSummarySeries", pl.DataFrame]] | None:
        """Specialized skim-page view retaining owning summary-series metadata."""
        return self._state.get_summary_series_set(
            summary_id,
            weighting or self._weighting_key(),
        )


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
    segmentation_type: str = "full"
    segment_id: str = "full"
    segment_label: str = "Full"
    is_full_segment: bool = True
    segment_column: str | None = None
    segment_values: tuple[object, ...] = ()

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
            segmentation_type=summary_run.segmentation_type,
            segment_id=summary_run.segment_id,
            segment_label=summary_run.segment_label,
            is_full_segment=summary_run.is_full_segment,
            segment_column=summary_run.segment_column,
            segment_values=summary_run.segment_values,
        )

    def display_label(self, *, include_segment: bool) -> str:
        if not include_segment:
            return self.label
        return f"{self.label} ({self.segment_label})"

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
