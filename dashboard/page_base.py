"""Base classes for persistent Panel dashboard pages."""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

import panel as pn

from activitysim_viz_logging import get_logger
from dashboard import DashboardState
from dashboard.components import data_unavailable_card
from runtime.config import Config

if TYPE_CHECKING:
    from dashboard.page_definitions import DashboardPageDefinition

LOGGER = get_logger("dashboard.page")


class DashboardPage:
    """Persistent page object for the live Panel dashboard."""

    definition: DashboardPageDefinition | None = None

    def __init__(self, name: str, state: DashboardState, config: Config) -> None:
        self.name = name
        self.state = state
        self.config = config
        self._page_state = state.get_page_state(name)
        self.view: pn.viewable.Viewable | None = None

    def refresh_if_needed(self) -> None:
        """Refresh the page when its rendered global state is stale."""
        if self._page_state.get("last_rendered_state") != self.state.global_state_key():
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """Refresh the page content."""
        if (
            not force
            and self._page_state.get("last_rendered_state")
            == self.state.global_state_key()
        ):
            return
        self._refresh()
        self._page_state["last_rendered_state"] = self.state.global_state_key()

    def mark_stale(self) -> None:
        """Mark the page stale so the next activation refreshes it."""
        self._page_state["last_rendered_state"] = None

    def _watch_widget(self, widget: pn.widgets.Widget) -> None:
        widget.param.watch(lambda event: self.refresh(force=True), "value")

    @property
    def as_percent(self) -> bool:
        """Return whether the current display mode should show percentages."""
        return self.state.value_mode == "Percent"

    @property
    def weighting_key(self) -> str:
        """Return the current weighting key used for raw summary caches."""
        return self.state.weighting_key()

    @classmethod
    def page_id(cls) -> str | None:
        """Return the registered page id when one has been assigned."""
        return cls.definition.page_id if cls.definition is not None else None

    @classmethod
    def page_title(cls) -> str | None:
        """Return the registered page title when one has been assigned."""
        return cls.definition.title if cls.definition is not None else None

    @property
    def required_summary_ids(self) -> tuple[str, ...]:
        if self.definition is None:
            return ()
        return self.definition.required_summary_ids

    @property
    def raw_data_mode(self) -> str:
        if self.definition is None:
            return "none"
        return self.definition.raw_data_mode

    def _warn_once(self, key: str, message: str) -> None:
        warnings = self._page_state.setdefault("warnings_emitted", set())
        if key in warnings:
            return
        LOGGER.warning(message)
        warnings.add(key)

    def data_not_available_card(
        self,
        *,
        detail: str,
        missing_items: list[str] | tuple[str, ...] | None = None,
        title: str = "Data Not Available",
    ) -> pn.Card:
        return data_unavailable_card(title, detail, missing_items=missing_items)

    def get_summary(self, summary_name: str):
        """Return one summary table per run for the current weighting mode."""
        return self.state.get_summary_table_set(summary_name, self.weighting_key)

    def has_summary(self, summary_name: str) -> bool:
        return self.state.has_summary_table_set(summary_name, self.weighting_key)

    def require_summary(self, summary_name: str):
        summary = self.get_summary(summary_name)
        if summary is None:
            self._warn_once(
                f"missing-summary:{summary_name}",
                (
                    f"Warning: dashboard page '{self.name}' requires summary "
                    f"'{summary_name}' for weighting mode '{self.weighting_key}', "
                    "but it is unavailable."
                ),
            )
        return summary

    def require_summaries(self, *summary_names: str) -> dict[str, Any] | None:
        missing = [
            summary_name
            for summary_name in summary_names
            if not self.has_summary(summary_name)
        ]
        if missing:
            for summary_name in missing:
                self._warn_once(
                    f"missing-summary:{summary_name}",
                    (
                        f"Warning: dashboard page '{self.name}' requires summary "
                        f"'{summary_name}' for weighting mode '{self.weighting_key}', "
                        "but it is unavailable."
                    ),
                )
            return None
        return {
            summary_name: self.get_summary(summary_name)
            for summary_name in summary_names
        }

    def get_raw_runs(self, *, weighted: bool | None = None):
        """Return raw runs when this dashboard session has loaded them explicitly."""
        return self.state.get_raw_runs_if_loaded(weighted=weighted)

    def require_raw_runs(self, *, weighted: bool | None = None):
        raw_runs = self.get_raw_runs(weighted=weighted)
        if raw_runs is not None:
            return raw_runs

        availability = self.state.raw_run_availability
        reason = (
            "raw run data was not requested for this dashboard session"
            if availability == "not_requested"
            else "raw run data is unavailable"
        )
        self._warn_once(
            f"missing-raw-runs:{availability}",
            (
                f"Warning: dashboard page '{self.name}' requires raw run data, "
                f"but {reason}."
            ),
        )
        return None

    def get_filtered_view(self, view_name: str, *filters: Any, factory):
        """Return a cached chart-ready filtered view for the current page state."""
        return self.state.get_or_create_cached(
            "filtered_view",
            self.name,
            self.weighting_key,
            view_name,
            *filters,
            factory=factory,
        )

    def _refresh(self) -> None:
        raise NotImplementedError
