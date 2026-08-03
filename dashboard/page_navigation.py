"""Grouped dashboard navigation behavior."""

from __future__ import annotations

import panel as pn

from dashboard.page_lifecycle import DashboardPage


class GroupedDashboardPage:
    """Top-level navigation item that renders child dashboard pages as tabs."""

    def __init__(
        self,
        group_id: str,
        title: str,
        pages: list[DashboardPage],
        default_child_page_id: str | None = None,
    ) -> None:
        if not pages:
            raise ValueError("GroupedDashboardPage requires at least one child page.")
        self._group_id = group_id
        self.name = title
        self.pages = pages
        self.view = pn.Tabs(*[(page.name, page.view) for page in pages], dynamic=False)
        self._active_child = self._default_child_index(default_child_page_id)
        self.view.active = self._active_child
        self.view.param.watch(self._on_child_tab_change, "active")

    def _default_child_index(self, default_child_page_id: str | None) -> int:
        if default_child_page_id is not None:
            for index, page in enumerate(self.pages):
                if page.page_id() == default_child_page_id:
                    return index
        return 0

    def _on_child_tab_change(self, event) -> None:
        self._active_child = int(event.new)
        self.refresh_if_needed()

    def page_id(self) -> str:
        return self._group_id

    @property
    def active_child(self) -> DashboardPage:
        return self.pages[self._active_child]

    def refresh_if_needed(self) -> None:
        self.active_child.refresh_if_needed()

    def refresh(self, force: bool = False) -> None:
        self.active_child.refresh(force=force)

    def mark_stale(self) -> None:
        for page in self.pages:
            page.mark_stale()


__all__ = ["GroupedDashboardPage"]
