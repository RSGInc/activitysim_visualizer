"""Base classes for persistent Panel dashboard pages."""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

import panel as pn

from dashboard import DashboardState
from summarize.reader import Config

if TYPE_CHECKING:
    from dashboard.page_definitions import DashboardPageDefinition


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

    def get_summary(self, summary_name: str, factory):
        """Return a cached raw summary for the current weighting mode."""
        precomputed = self.state.get_precomputed_summary(
            summary_name, self.weighting_key
        )
        if precomputed is not None:
            return precomputed
        return self.state.get_or_create_cached(
            "page_summary",
            self.name,
            self.weighting_key,
            summary_name,
            factory=factory,
        )

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
