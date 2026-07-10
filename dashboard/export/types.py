"""Typed payload models for offline HTML export."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

EXPORT_SCHEMA_VERSION = "2.0"
EXPORT_CLIENT_RUNTIME = "region-swap-v1"
EXPORT_PAGE_SELECTOR_RUNTIME = "dashboard-and-page-selectors"

NodeKind = Literal[
    "container",
    "card",
    "tabs",
    "plotly",
    "table",
    "widget",
    "html",
    "spacer",
    "region",
]
ContainerLayout = Literal["row", "column"]
WidgetType = Literal["radio_button_group", "select", "float_input", "checkbox", "button"]
RegionContentMode = Literal["snapshot"]


class SelectorMetadataPayload(TypedDict):
    id: str
    label: str
    available: bool
    request_mode: str
    requested_values: list[str]
    resolved_values: list[str]
    default_value: Any
    options: list[str]
    export_enabled: bool


class PageSelectorReferencePayload(TypedDict):
    page_id: str
    selector_id: str


class PageDescriptorPayload(TypedDict):
    id: str
    title: str
    selectors: list[SelectorMetadataPayload]
    children: list["PageDescriptorPayload"]
    default_page_id: str | None


class ExportChromeControlsEnabled(TypedDict):
    weighting: bool
    values: bool


class ExportChrome(TypedDict):
    layout: str
    rail_sections: list[str]
    controls_enabled: ExportChromeControlsEnabled


class DashboardControlsPayload(TypedDict):
    weighting: list[str]
    values: list[str]


class DefaultStatePayload(TypedDict):
    weighting: str
    values: str


class ContainerNode(TypedDict):
    kind: Literal["container"]
    layout: ContainerLayout
    children: list["ExportNode"]
    child_count: int
    styles: dict[str, Any]
    css_classes: list[str]


class CardNode(TypedDict):
    kind: Literal["card"]
    title: str
    children: list["ExportNode"]


class TabPayload(TypedDict):
    title: str
    content: "ExportNode"


class TabsNode(TypedDict):
    kind: Literal["tabs"]
    tabs: list[TabPayload]


class PlotlyNode(TypedDict):
    kind: Literal["plotly"]
    figure: dict[str, Any]


class TableNode(TypedDict):
    kind: Literal["table"]
    columns: list[str]
    rows: list[dict[str, Any]]


class WidgetNode(TypedDict):
    kind: Literal["widget"]
    widget_type: WidgetType
    name: str
    value: Any
    options: list[Any]
    step: Any
    disabled: bool
    selector_id: str | None
    export_enabled: bool


class HtmlNode(TypedDict):
    kind: Literal["html"]
    html: str


class SpacerNode(TypedDict):
    kind: Literal["spacer"]


class RegionNode(TypedDict):
    kind: Literal["region"]
    region_id: str
    selector_ids: list[str]
    content_mode: RegionContentMode
    default_key: str
    default_content: "ExportNode"
    variants: dict[str, "ExportNode"]
    variant_aliases: dict[str, str]


ExportNode = (
    ContainerNode
    | CardNode
    | TabsNode
    | PlotlyNode
    | TableNode
    | WidgetNode
    | HtmlNode
    | SpacerNode
    | RegionNode
)


class PagePayload(TypedDict):
    kind: Literal["page"]
    content: ExportNode


PageContentPayload = PagePayload


class PageExportSupportPayload(TypedDict):
    client_side_runtime: str
    enabled_page_selectors: list[PageSelectorReferencePayload]


class ExportPayload(TypedDict):
    title: str
    runs_loaded: list[dict[str, str]]
    chrome: ExportChrome
    dashboard_controls: DashboardControlsPayload
    default_state: DefaultStatePayload
    pages: list[PageDescriptorPayload]
    states: dict[str, dict[str, PageContentPayload]]
    page_export_support: PageExportSupportPayload
    client_runtime: str
    schema_version: str
