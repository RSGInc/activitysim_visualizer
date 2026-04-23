"""Contracts enforced by the offline HTML export path."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import panel as pn

from dashboard.page_definitions import DashboardPageDefinition


@runtime_checkable
class ExportableDashboardPage(Protocol):
    """Minimum interface required for offline export serialization."""

    definition: DashboardPageDefinition
    view: pn.viewable.Viewable | None

    def refresh(self, force: bool = False) -> None: ...


def validate_export_page(page: Any) -> None:
    """Fail early when a page instance does not satisfy the export contract."""

    if not hasattr(page, "refresh") or not callable(page.refresh):
        raise TypeError(
            f"Dashboard page {type(page).__name__} does not implement refresh(force=...)."
        )

    page_def = getattr(page, "definition", None)
    if not isinstance(page_def, DashboardPageDefinition):
        raise TypeError(
            f"Dashboard page {type(page).__name__} is missing a valid DashboardPageDefinition."
        )

    if not hasattr(page, "view"):
        raise TypeError(
            f"Dashboard page {type(page).__name__} is missing the required 'view' attribute."
        )
