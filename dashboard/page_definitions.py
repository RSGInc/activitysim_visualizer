"""Shared page/group definition types for dashboard page registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

import panel as pn

from processor.models import PreparedTableName

if TYPE_CHECKING:
    from dashboard.page_base import DashboardPage
    from runtime.config import Config

PreparedDataMode = Literal["none", "optional", "required"]
DashboardPageSelectionMode = Literal["default", "all", "explicit"]


@dataclass(frozen=True)
class PageSelectorDefinition:
    """Describe one page-local widget that may participate in HTML export.

    Attributes:
        selector_id: Stable config-facing selector name used under
            ``visualizer.export_html.pages.<page_id>.<selector_id>``.
        widget_attr: Attribute name on the page instance that resolves to the
            backing Panel widget.
        label: Human-readable label used in serialized export metadata.
        enabled_when: Optional predicate that can disable export support when
            page state or config makes the widget unavailable.
        exportable: Whether the export path should attempt to treat this widget
            as an interactive selector.
    """

    selector_id: str
    widget_attr: str
    label: str
    enabled_when: Callable[[Any, Config], bool] | None = None
    exportable: bool = True

    def widget_for(self, page: Any) -> pn.widgets.Widget | None:
        """Return the backing widget from a page instance when present."""
        widget = getattr(page, self.widget_attr, None)
        return widget if isinstance(widget, pn.widgets.Widget) else None

    def available_for(self, page: Any, config: Config) -> bool:
        """Return whether this selector is available for the current page state."""
        if self.enabled_when is not None and not self.enabled_when(page, config):
            return False
        return self.widget_for(page) is not None


@dataclass(frozen=True)
class PageExportRegionDefinition:
    """Describe one explicit page-owned export region."""

    region_id: str
    view_attr: str
    selector_ids: tuple[str, ...] = field(default_factory=tuple)

    def view_for(self, page: Any) -> pn.viewable.Viewable | None:
        """Return the stable region root viewable from a page instance when present."""
        view = getattr(page, self.view_attr, None)
        return view if isinstance(view, pn.viewable.Viewable) else None


@dataclass(frozen=True)
class DashboardPageDefinition:
    """Register one dashboard page for live mode and HTML export."""

    page_id: str
    title: str
    order: int = 0
    group_id: str | None = None
    child_id: str | None = None
    child_order: int = 0
    default_enabled: bool = True
    prepared_data_mode: PreparedDataMode = "none"
    controller_cls: type["DashboardPage"] | None = None
    selectors: tuple[PageSelectorDefinition, ...] = field(default_factory=tuple)
    export_regions: tuple[PageExportRegionDefinition, ...] = field(default_factory=tuple)
    required_summary_ids: tuple[str, ...] = field(default_factory=tuple)
    required_prepared_tables: tuple[PreparedTableName, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DashboardDataRequirements:
    """Aggregated summary/prepared-table requirements for a page set."""

    prepared_data_mode: PreparedDataMode = "none"
    required_summary_ids: tuple[str, ...] = field(default_factory=tuple)
    required_prepared_tables: tuple[PreparedTableName, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DashboardGroupDefinition:
    """Register one top-level dashboard navigation group."""

    group_id: str
    title: str
    order: int = 0
    default_enabled: bool = True
    default_child_id: str | None = None


@dataclass(frozen=True)
class DashboardPageConfigEntry:
    """Normalized dashboard page-selection entry from config."""

    page_id: str
    mode: DashboardPageSelectionMode = "explicit"
    child_page_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExportPageConfigEntry:
    """Normalized export page-selection entry from config."""

    page_id: str
    mode: DashboardPageSelectionMode = "explicit"
    child_page_ids: tuple[str, ...] = field(default_factory=tuple)
