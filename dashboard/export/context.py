"""Shared context for export payload construction."""

from __future__ import annotations

from dataclasses import dataclass, field

from dashboard import DashboardState
from dashboard.data_access import DashboardPreparedRunProvider
from runtime.config import Config
from processor.summarize.cache import SummaryRun


@dataclass(slots=True)
class ExportBuildContext:
    """Shared state reused across export payload construction."""

    config: Config
    summary_runs: list[SummaryRun] | None
    prepared_run_provider: DashboardPreparedRunProvider
    warned_unavailable_selectors: set[tuple[str, str]] = field(default_factory=set)

    def build_dashboard_state(self) -> DashboardState:
        """Create a dashboard state seeded with shared export dependencies."""
        return DashboardState(
            summary_runs=self.summary_runs,
            weighting_modes=self.config.weighting_modes,
            prepared_run_provider=self.prepared_run_provider,
        )
