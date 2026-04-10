"""Shared page-definition types for dashboard page registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

import panel as pn

from runtime.config import Config

if TYPE_CHECKING:
    from dashboard.page_base import DashboardPage

RawDataMode = Literal["none", "optional", "required"]


@dataclass(frozen=True)
class PageSelectorDefinition:
    """One page-level selector that may be supported in HTML export."""

    selector_id: str
    widget_attr: str
    label: str
    enabled_when: Callable[[Any, Config], bool] | None = None
    exportable: bool = True

    def widget_for(self, page: Any) -> pn.widgets.Widget | None:
        widget = getattr(page, self.widget_attr, None)
        return widget if isinstance(widget, pn.widgets.Widget) else None

    def available_for(self, page: Any, config: Config) -> bool:
        if self.enabled_when is not None and not self.enabled_when(page, config):
            return False
        return self.widget_for(page) is not None


@dataclass(frozen=True)
class DashboardPageDefinition:
    """A dashboard page definition consumed by live and export code."""

    page_id: str
    title: str
    order: int = 0
    default_enabled: bool = True
    raw_data_mode: RawDataMode = "none"
    controller_cls: type["DashboardPage"] | None = None
    selectors: tuple[PageSelectorDefinition, ...] = field(default_factory=tuple)
    required_summary_ids: tuple[str, ...] = field(default_factory=tuple)
