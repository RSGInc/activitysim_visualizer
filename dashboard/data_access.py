"""Dashboard-owned data access models for summaries and optional raw runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import polars as pl

from runtime.models import RunData
from summarize.cache import SummaryRun, strip_weights

RawRunAvailability = Literal["loaded", "unavailable", "not_requested"]


@dataclass(frozen=True)
class DashboardSummarySeries:
    """Summary tables available for one run in dashboard-friendly form."""

    label: str
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]]
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


@dataclass
class DashboardRawRunProvider:
    """Explicit raw-run access for dashboard pages that may need disaggregate data."""

    availability: RawRunAvailability
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
    ) -> "DashboardRawRunProvider":
        return cls("loaded", weighted_runs=list(runs or []))

    @classmethod
    def unavailable(cls) -> "DashboardRawRunProvider":
        return cls("unavailable")

    @classmethod
    def not_requested(cls) -> "DashboardRawRunProvider":
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
