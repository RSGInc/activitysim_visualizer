"""Registry of exportable dashboard pages and page-level selectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import panel as pn

from summarize.reader import Config


@dataclass(frozen=True)
class ExportSelectorDefinition:
    """One page-level selector that may be supported in HTML export."""

    selector_id: str
    widget_attr: str
    label: str
    enabled_when: Callable[[Any, Config], bool] | None = None

    def widget_for(self, page: Any) -> pn.widgets.Widget | None:
        widget = getattr(page, self.widget_attr, None)
        return widget if isinstance(widget, pn.widgets.Widget) else None

    def available_for(self, page: Any, config: Config) -> bool:
        if self.enabled_when is not None and not self.enabled_when(page, config):
            return False
        return self.widget_for(page) is not None


@dataclass(frozen=True)
class ExportPageDefinition:
    """A dashboard page and the selectors we may eventually export."""

    page_id: str
    page_name: str
    selectors: tuple[ExportSelectorDefinition, ...] = field(default_factory=tuple)


EXPORT_PAGE_REGISTRY: tuple[ExportPageDefinition, ...] = (
    ExportPageDefinition("overview", "Overview"),
    ExportPageDefinition(
        "long_term",
        "Long-Term",
        selectors=(
            ExportSelectorDefinition(
                "geography",
                "geo_sel",
                "Geography",
                enabled_when=lambda page, config: config.geography_enabled,
            ),
        ),
    ),
    ExportPageDefinition(
        "tour_summary",
        "Tour Summary",
        selectors=(ExportSelectorDefinition("person_type", "ptype_sel", "Person Type"),),
    ),
    ExportPageDefinition(
        "joint_tours",
        "Joint Tours",
        selectors=(ExportSelectorDefinition("hh_size", "hhsize_sel", "HH Size"),),
    ),
    ExportPageDefinition(
        "destination",
        "Destination",
        selectors=(ExportSelectorDefinition("purpose", "purp_sel", "Purpose"),),
    ),
    ExportPageDefinition(
        "tour_tod",
        "Tour TOD",
        selectors=(ExportSelectorDefinition("purpose", "purp_sel", "Purpose"),),
    ),
    ExportPageDefinition(
        "tour_mode",
        "Tour Mode",
        selectors=(ExportSelectorDefinition("purpose", "purp_sel", "Purpose"),),
    ),
    ExportPageDefinition(
        "stop_frequency",
        "Stop Frequency",
        selectors=(
            ExportSelectorDefinition("tour_purpose", "purp_sel", "Tour Purpose"),
        ),
    ),
    ExportPageDefinition("stop_location", "Stop Location"),
    ExportPageDefinition(
        "stop_timing",
        "Stop Timing",
        selectors=(ExportSelectorDefinition("purpose", "purp_sel", "Purpose"),),
    ),
    ExportPageDefinition(
        "trip_mode",
        "Trip Mode",
        selectors=(
            ExportSelectorDefinition("tour_purpose", "purp_sel", "Tour Purpose"),
            ExportSelectorDefinition("tour_mode", "tmode_sel", "Tour Mode"),
        ),
    ),
)

_PAGE_BY_ID = {page.page_id: page for page in EXPORT_PAGE_REGISTRY}
_PAGE_BY_NAME = {page.page_name: page for page in EXPORT_PAGE_REGISTRY}


def export_page_definition_by_id(page_id: str) -> ExportPageDefinition | None:
    return _PAGE_BY_ID.get(page_id)


def export_page_definition_by_name(page_name: str) -> ExportPageDefinition | None:
    return _PAGE_BY_NAME.get(page_name)

