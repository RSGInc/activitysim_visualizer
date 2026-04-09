"""Shared live-session state for the Panel dashboard."""

from __future__ import annotations

from typing import Any

import param
import polars as pl

from dashboard.data_access import (
    DashboardRawRunProvider,
    DashboardSummarySeries,
)
from summarize.cache import SummaryRun, normalize_weighting_modes
from summarize.reader import RunData


class DashboardState(param.Parameterized):
    """Single source of truth for live Panel dashboard state."""

    weight_mode = param.ObjectSelector(
        default="Weighted", objects=["Weighted", "Unweighted"]
    )
    value_mode = param.ObjectSelector(default="Percent", objects=["Percent", "Count"])
    active_tab = param.Integer(default=0, bounds=(0, None))

    def __init__(
        self,
        runs: list[tuple[str, RunData]] | None,
        *,
        summary_runs: list[SummaryRun] | None = None,
        weighting_modes: list[str] | None = None,
        raw_run_provider: DashboardRawRunProvider | None = None,
        **params: Any,
    ) -> None:
        super().__init__(**params)
        if raw_run_provider is not None and runs:
            raise ValueError(
                "Pass raw runs either through 'runs' or 'raw_run_provider', not both."
            )
        self._raw_run_provider = (
            raw_run_provider
            if raw_run_provider is not None
            else DashboardRawRunProvider.from_runs(runs)
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
    def weighted_runs(self) -> list[tuple[str, RunData]]:
        """Compatibility wrapper for callers that still expect ambient raw runs."""
        return self.get_raw_runs_if_loaded(weighted=True) or []

    @property
    def unweighted_runs(self) -> list[tuple[str, RunData]]:
        """Compatibility wrapper for callers that still expect ambient raw runs."""
        return self.get_raw_runs_if_loaded(weighted=False) or []

    @property
    def enabled_weighting_modes(self) -> list[str]:
        return list(self._weighting_modes)

    @property
    def raw_run_availability(self) -> str:
        return self._raw_run_provider.availability

    @property
    def run_labels(self) -> list[str]:
        if self._summary_runs:
            return [run.label for run in self._summary_runs]
        return self._raw_run_provider.labels()

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

    def get_raw_runs_if_loaded(
        self,
        weighted: bool | None = None,
    ) -> list[tuple[str, RunData]] | None:
        """Return raw runs only when the dashboard explicitly has them loaded."""
        if weighted is None:
            weighted = self.weight_mode == "Weighted"
        return self._raw_run_provider.get_runs_if_loaded(weighted=weighted)

    def get_runs(self, weighted: bool | None = None) -> list[tuple[str, RunData]]:
        """Compatibility wrapper for callers that still expect ambient raw runs."""
        return self.get_raw_runs_if_loaded(weighted=weighted) or []

    def get_summary_table_set(
        self,
        summary_name: str,
        weighting_key: str | None = None,
    ) -> list[tuple[str, pl.DataFrame]] | None:
        """Return one summary table per run for the requested weighting mode."""
        if not self._summary_runs:
            return None
        mode = weighting_key or self.weighting_key()
        summary_list: list[tuple[str, pl.DataFrame]] = []
        for run in self._summary_runs:
            table = run.get_table(summary_name, mode)
            if table is None:
                return None
            summary_list.append((run.label, table))
        return summary_list

    def has_summary_table_set(
        self,
        summary_name: str,
        weighting_key: str | None = None,
    ) -> bool:
        return self.get_summary_table_set(summary_name, weighting_key) is not None

    def get_precomputed_summary(
        self,
        summary_name: str,
        weighting_key: str | None = None,
    ) -> list[tuple[str, pl.DataFrame]] | None:
        """Compatibility wrapper for the summary-first dashboard data API."""
        return self.get_summary_table_set(summary_name, weighting_key)

    def summary_raw_runs(self) -> list[tuple[str, RunData]]:
        """Compatibility wrapper for older callers expecting summary-linked raw runs."""
        return self.get_raw_runs_if_loaded(weighted=True) or []

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
