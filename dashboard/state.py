"""Shared live-session state for the Panel dashboard."""

from __future__ import annotations

from typing import Any

import param
import polars as pl

from dashboard.data_access import (
    DashboardDataSelection,
    DashboardPreparedRunProvider,
    DashboardSummarySeries,
    VisualizationRunAvailability,
)
from processor.models import RunData
from processor.prepare.availability import table_availability, table_diagnostics
from processor.summarize.cache import SummaryRun, normalize_weighting_modes


class DashboardState(param.Parameterized):
    """Single source of truth for live Panel dashboard state."""

    weight_mode = param.ObjectSelector(
        default="Weighted", objects=["Weighted", "Unweighted"]
    )
    value_mode = param.ObjectSelector(default="Percent", objects=["Percent", "Count"])
    active_tab = param.Integer(default=0, bounds=(0, None))

    def __init__(
        self,
        summary_runs: list[SummaryRun] | None = None,
        weighting_modes: list[str] | None = None,
        prepared_run_provider: DashboardPreparedRunProvider | None = None,
        **params: Any,
    ) -> None:
        super().__init__(**params)
        self._prepared_run_provider = (
            prepared_run_provider
            if prepared_run_provider is not None
            else DashboardPreparedRunProvider.not_requested()
        )
        self._weighting_modes = normalize_weighting_modes(weighting_modes)
        weight_options = [mode.title() for mode in self._weighting_modes]
        self.param.weight_mode.objects = weight_options
        self.weight_mode = weight_options[0]
        self._page_state: dict[str, dict[str, Any]] = {}
        self._caches: dict[str, dict[tuple[Any, ...], Any]] = {}
        self._cache_stats: dict[str, dict[str, int]] = {}
        self._summary_runs: list[DashboardSummarySeries] = self._build_summary_series(
            summary_runs
        )

    def _build_summary_series(
        self,
        summary_runs: list[SummaryRun] | None,
    ) -> list[DashboardSummarySeries]:
        if not summary_runs:
            return []
        return [
            DashboardSummarySeries.from_summary_run(summary_run)
            for summary_run in summary_runs
        ]

    @property
    def enabled_weighting_modes(self) -> list[str]:
        return list(self._weighting_modes)

    @property
    def prepared_run_availability(self) -> str:
        return self._prepared_run_provider.availability

    @property
    def run_labels(self) -> list[str]:
        if self._summary_runs:
            return [run.label for run in self._summary_runs]
        return self._prepared_run_provider.labels()

    @property
    def page_state(self) -> dict[str, dict[str, Any]]:
        """Return all page-local state keyed by page name."""
        return self._page_state

    @property
    def caches(self) -> dict[str, dict[tuple[Any, ...], Any]]:
        """Return all shared caches keyed by cache bucket."""
        return self._caches

    @property
    def cache_stats(self) -> dict[str, dict[str, int]]:
        """Return cache hit/miss stats keyed by cache bucket."""
        return self._cache_stats

    def weighting_key(self) -> str:
        return str(self.weight_mode).strip().lower()

    def value_key(self) -> str:
        return "percent" if self.value_mode == "Percent" else "count"

    def global_state_key(self) -> tuple[str, str]:
        """Return a stable key for the current global display state."""
        return (self.weighting_key(), self.value_key())

    def get_prepared_runs_if_loaded(
        self,
        weighted: bool | None = None,
    ) -> list[tuple[str, RunData]] | None:
        """Return prepared runs only when the dashboard explicitly has them loaded."""
        if weighted is None:
            weighted = self.weight_mode == "Weighted"
        return self._prepared_run_provider.get_runs_if_loaded(weighted=weighted)

    def get_summary_table_set(
        self,
        summary_name: str,
        weighting_key: str | None = None,
    ) -> list[tuple[str, pl.DataFrame]] | None:
        """Return usable summary tables for the requested weighting mode."""
        if not self._summary_runs:
            return None
        mode = weighting_key or self.weighting_key()
        return self.get_or_create_cached(
            "summary_table_set",
            summary_name,
            mode,
            factory=lambda: self._build_summary_table_set(summary_name, mode),
        )

    def has_summary_table_set(
        self,
        summary_name: str,
        weighting_key: str | None = None,
    ) -> bool:
        return self.get_summary_table_set(summary_name, weighting_key) is not None

    def get_summary_column_values(
        self,
        summary_name: str,
        column: str,
        weighting_key: str | None = None,
    ) -> list[str]:
        """Return the union of one string-like summary column across usable runs."""
        mode = weighting_key or self.weighting_key()
        return self.get_or_create_cached(
            "summary_column_values",
            summary_name,
            column,
            mode,
            factory=lambda: self._build_summary_column_values(
                summary_name,
                column,
                mode,
            ),
        )

    def _build_summary_column_values(
        self,
        summary_name: str,
        column: str,
        weighting_key: str,
    ) -> list[str]:
        data_list = self.get_summary_table_set(summary_name, weighting_key)
        if data_list is None:
            return []
        values: list[str] = []
        for _, table in data_list:
            if column not in table.columns:
                continue
            for value in (
                table.select(column)
                .drop_nulls()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            ):
                if value not in values:
                    values.append(value)
        return values

    def inspect_summary_table(
        self,
        summary_name: str,
        *,
        weighting_key: str | None = None,
        required_columns: tuple[str, ...] = (),
    ) -> DashboardDataSelection:
        """Return usable and excluded runs for one summary table."""
        mode = weighting_key or self.weighting_key()
        normalized_columns = tuple(required_columns)
        return self.get_or_create_cached(
            "summary_selection",
            summary_name,
            mode,
            normalized_columns,
            factory=lambda: self._inspect_summary_table_uncached(
                summary_name,
                weighting_key=mode,
                required_columns=normalized_columns,
            ),
        )

    def _build_summary_table_set(
        self,
        summary_name: str,
        weighting_key: str,
    ) -> list[tuple[str, pl.DataFrame]] | None:
        selection = self.inspect_summary_table(
            summary_name,
            weighting_key=weighting_key,
        )
        if not selection.has_usable_runs:
            return None
        return [(label, table) for label, table in selection.usable_runs]

    def _inspect_summary_table_uncached(
        self,
        summary_name: str,
        *,
        weighting_key: str,
        required_columns: tuple[str, ...] = (),
    ) -> DashboardDataSelection:
        """Return usable and excluded runs for one summary table."""
        mode = weighting_key or self.weighting_key()
        usable_runs: list[tuple[str, pl.DataFrame]] = []
        excluded_runs: list[VisualizationRunAvailability] = []
        for run in self._summary_runs:
            table = run.get_table(summary_name, mode)
            metadata = run.get_summary_metadata(summary_name, mode) or {}
            state = str(metadata.get("state", "")).strip().lower()
            if table is None:
                detail = (
                    str(metadata.get("detail", "")).strip()
                    or "summary table is missing"
                )
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=run.label,
                        run_key=run.run_key,
                        source_run_dir=run.source_run_dir,
                        status="missing",
                        detail=detail,
                        source_kind="summary",
                        source_id=summary_name,
                    )
                )
                continue
            if state == "unavailable":
                detail = (
                    str(metadata.get("detail", "")).strip()
                    or "required inputs for this summary are unavailable"
                )
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=run.label,
                        run_key=run.run_key,
                        source_run_dir=run.source_run_dir,
                        status="unavailable",
                        detail=detail,
                        source_kind="summary",
                        source_id=summary_name,
                    )
                )
                continue
            if state == "failed":
                detail = (
                    str(metadata.get("detail", "")).strip()
                    or "summary generation failed"
                )
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=run.label,
                        run_key=run.run_key,
                        source_run_dir=run.source_run_dir,
                        status="failed",
                        detail=detail,
                        source_kind="summary",
                        source_id=summary_name,
                    )
                )
                continue
            if table.is_empty():
                detail = (
                    str(metadata.get("detail", "")).strip() or "summary table is empty"
                )
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=run.label,
                        run_key=run.run_key,
                        source_run_dir=run.source_run_dir,
                        status="empty",
                        detail=detail,
                        source_kind="summary",
                        source_id=summary_name,
                    )
                )
                continue
            missing_columns = tuple(
                column for column in required_columns if column not in table.columns
            )
            if missing_columns:
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=run.label,
                        run_key=run.run_key,
                        source_run_dir=run.source_run_dir,
                        status="schema_mismatch",
                        detail=(
                            "missing required columns: "
                            + ", ".join(sorted(missing_columns))
                        ),
                        source_kind="summary",
                        source_id=summary_name,
                        missing_columns=missing_columns,
                    )
                )
                continue
            usable_runs.append((run.label, table))

        return DashboardDataSelection(
            source_kind="summary",
            source_id=summary_name,
            usable_runs=usable_runs,
            excluded_runs=excluded_runs,
        )

    def inspect_prepared_table(
        self,
        table_name: str,
        *,
        weighted: bool | None = None,
        required_columns: tuple[str, ...] = (),
    ) -> DashboardDataSelection:
        """Return usable and excluded runs for one prepared table."""
        effective_weighted = self.weight_mode == "Weighted" if weighted is None else weighted
        normalized_columns = tuple(required_columns)
        return self.get_or_create_cached(
            "prepared_selection",
            table_name,
            effective_weighted,
            normalized_columns,
            factory=lambda: self._inspect_prepared_table_uncached(
                table_name,
                weighted=effective_weighted,
                required_columns=normalized_columns,
            ),
        )

    def _inspect_prepared_table_uncached(
        self,
        table_name: str,
        *,
        weighted: bool,
        required_columns: tuple[str, ...] = (),
    ) -> DashboardDataSelection:
        """Return usable and excluded runs for one prepared table."""
        usable_runs: list[tuple[str, RunData]] = []
        excluded_runs: list[VisualizationRunAvailability] = []
        prepared_runs = self.get_prepared_runs_if_loaded(weighted=weighted)
        if prepared_runs is None:
            detail = (
                "prepared run data was not requested for this dashboard session"
                if self.prepared_run_availability == "not_requested"
                else "prepared run data is unavailable"
            )
            return DashboardDataSelection(
                source_kind="prepared",
                source_id=table_name,
                usable_runs=[],
                excluded_runs=[
                    VisualizationRunAvailability(
                        label=label,
                        status="missing",
                        detail=detail,
                        source_kind="prepared",
                        source_id=table_name,
                    )
                    for label in self.run_labels
                ],
            )

        for label, run in prepared_runs:
            states = table_availability(run)
            diagnostics = table_diagnostics(run)
            table = getattr(run, table_name, None)
            state = states.get(table_name)
            if table is None or state == "unavailable":
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=label,
                        status="unavailable",
                        detail=diagnostics.get(
                            table_name, "prepared table is unavailable"
                        ),
                        source_kind="prepared",
                        source_id=table_name,
                    )
                )
                continue
            if state == "failed":
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=label,
                        status="failed",
                        detail=diagnostics.get(table_name, "prepared table failed"),
                        source_kind="prepared",
                        source_id=table_name,
                    )
                )
                continue
            if isinstance(table, pl.DataFrame) and table.is_empty():
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=label,
                        status="empty",
                        detail=diagnostics.get(table_name, "prepared table is empty"),
                        source_kind="prepared",
                        source_id=table_name,
                    )
                )
                continue
            missing_columns = tuple(
                column for column in required_columns if column not in table.columns
            )
            if missing_columns:
                excluded_runs.append(
                    VisualizationRunAvailability(
                        label=label,
                        status="schema_mismatch",
                        detail=(
                            "missing required columns: "
                            + ", ".join(sorted(missing_columns))
                        ),
                        source_kind="prepared",
                        source_id=table_name,
                        missing_columns=missing_columns,
                    )
                )
                continue
            usable_runs.append((label, run))

        return DashboardDataSelection(
            source_kind="prepared",
            source_id=table_name,
            usable_runs=usable_runs,
            excluded_runs=excluded_runs,
        )

    def get_page_state(self, page_name: str) -> dict[str, Any]:
        """Return mutable page-local state for a page, creating it if needed."""
        return self._page_state.setdefault(page_name, {})

    def update_page_state(self, page_name: str, **updates: Any) -> dict[str, Any]:
        """Update and return page-local state for a page."""
        state = self.get_page_state(page_name)
        state.update(updates)
        return state

    def get_cache(self, bucket: str) -> dict[tuple[Any, ...], Any]:
        """Return a named shared cache bucket."""
        return self._caches.setdefault(bucket, {})

    def _stats_for(self, bucket: str) -> dict[str, int]:
        return self._cache_stats.setdefault(bucket, {"hits": 0, "misses": 0})

    def get_cached(self, bucket: str, *key: Any, default: Any = None) -> Any:
        """Read a cached value from a named bucket."""
        return self.get_cache(bucket).get(tuple(key), default)

    def set_cached(self, bucket: str, *key: Any, value: Any) -> Any:
        """Store a cached value in a named bucket and return it."""
        self.get_cache(bucket)[tuple(key)] = value
        return value

    def get_or_create_cached(self, bucket: str, *key: Any, factory) -> Any:
        """Return a cached value or create it, recording cache hit/miss stats."""
        cache = self.get_cache(bucket)
        stats = self._stats_for(bucket)
        cache_key = tuple(key)
        if cache_key in cache:
            stats["hits"] += 1
            return cache[cache_key]
        stats["misses"] += 1
        value = factory()
        cache[cache_key] = value
        return value
