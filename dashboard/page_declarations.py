"""Author-facing selector and section declarations for dashboard pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, TypeAlias

import panel as pn

from dashboard.page_definitions import PreparedDataMode

SectionContent: TypeAlias = (
    pn.viewable.Viewable | list[pn.viewable.Viewable] | tuple[pn.viewable.Viewable, ...]
)
SelectorOptions: TypeAlias = list | tuple | dict
OptionProvider: TypeAlias = Callable[[], SelectorOptions]
DefaultPolicy: TypeAlias = (
    Literal["first", "last"] | Callable[[SelectorOptions], object]
)

PAGE_SELECTOR_STYLESHEET = """
:host(.page-selector-widget) { max-width: 300px; }
:host(.page-selector-widget) .bk-input-group { width: auto; }
:host(.page-selector-widget) .bk-input-group-label,
:host(.page-selector-widget) label {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 6px;
}
:host(.page-selector-widget) select,
:host(.page-selector-widget) input { font-size: 13px; font-weight: 500; }
"""

UNSET = object()


@dataclass(frozen=True)
class RegisteredPageSelector:
    selector_id: str
    widget: pn.widgets.Widget
    label: str
    exportable: bool = True
    options: OptionProvider | None = None
    default: DefaultPolicy = "first"


@dataclass
class RegisteredPageSection:
    section_id: str
    container: pn.Column
    selector_ids: tuple[str, ...]
    export: bool
    export_data_mode: PreparedDataMode
    render: Callable[[], SectionContent]
    dirty: bool = True


def option_values(options: SelectorOptions) -> list[object]:
    """Return the selectable values represented by Panel options."""
    return list(options.values()) if isinstance(options, dict) else list(options)


def default_value(options: SelectorOptions, policy: DefaultPolicy) -> object:
    """Resolve a selector's value after its previous value becomes stale."""
    values = option_values(options)
    if callable(policy):
        return policy(options)
    if not values:
        return None
    return values[-1] if policy == "last" else values[0]


__all__ = [
    "DefaultPolicy",
    "OptionProvider",
    "RegisteredPageSection",
    "RegisteredPageSelector",
    "SectionContent",
    "SelectorOptions",
]
