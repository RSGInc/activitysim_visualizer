"""Shared live-session state for the Panel dashboard."""
from __future__ import annotations

from typing import Any

import param
import polars as pl

from summarize.reader import RunData


def _strip_weights(rd: RunData) -> RunData:
    """Return a copy of RunData with finalweight=1.0 on weighted tables."""

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
        tours=_reset(rd.tours),
        trips=_reset(rd.trips),
        joint_participants=rd.joint_participants,
        land_use=rd.land_use,
        skim_matrix=rd.skim_matrix,
        skim_zone_map=rd.skim_zone_map,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )


class DashboardState(param.Parameterized):
    """Single source of truth for live Panel dashboard state."""

    weight_mode = param.ObjectSelector(default="Weighted", objects=["Weighted", "Unweighted"])
    value_mode = param.ObjectSelector(default="Percent", objects=["Percent", "Count"])
    active_tab = param.Integer(default=0, bounds=(0, None))

    def __init__(self, runs: list[tuple[str, RunData]], **params: Any) -> None:
        super().__init__(**params)
        self._weighted_runs = list(runs)
        self._unweighted_runs: list[tuple[str, RunData]] | None = None
        self._page_state: dict[str, dict[str, Any]] = {}
        self._caches: dict[str, dict[tuple[Any, ...], Any]] = {}
        self._cache_stats: dict[str, dict[str, int]] = {}

    @property
    def weighted_runs(self) -> list[tuple[str, RunData]]:
        """Return the original weighted run list."""
        return self._weighted_runs

    @property
    def unweighted_runs(self) -> list[tuple[str, RunData]]:
        """Return cached unweighted runs, creating them on first access."""
        if self._unweighted_runs is None:
            self._unweighted_runs = [
                (label, _strip_weights(rd)) for label, rd in self._weighted_runs
            ]
        return self._unweighted_runs

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
        return "weighted" if self.weight_mode == "Weighted" else "unweighted"

    def value_key(self) -> str:
        return "percent" if self.value_mode == "Percent" else "count"

    def global_state_key(self) -> tuple[str, str]:
        """Return a stable key for the current global display state."""
        return (self.weighting_key(), self.value_key())

    def get_runs(self, weighted: bool | None = None) -> list[tuple[str, RunData]]:
        """Return weighted or unweighted runs, defaulting to current state."""
        if weighted is None:
            weighted = self.weight_mode == "Weighted"
        return self.weighted_runs if weighted else self.unweighted_runs

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
