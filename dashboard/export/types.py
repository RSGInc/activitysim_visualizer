"""Typed payload models for offline HTML export."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

EXPORT_SCHEMA_VERSION = "1.0"
EXPORT_CLIENT_RUNTIME = "figure-swap-v1"
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
]
ContainerLayout = Literal["row", "column"]
WidgetType = Literal["radio_button_group", "select"]


class SelectorMetadataPayload(TypedDict):
    id: str
    label: str
    available: bool
    request_mode: str
    requested_values: list[str]
    resolved_values: list[str]
    default_value: str | None
    options: list[str]
    export_enabled: bool


class PageSelectorReferencePayload(TypedDict):
    page_id: str
    selector_id: str


class PageDescriptorPayload(TypedDict):
    id: str
    title: str
    selectors: list[SelectorMetadataPayload]


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
    disabled: bool
    selector_id: str | None
    export_enabled: bool


class HtmlNode(TypedDict):
    kind: Literal["html"]
    html: str


class SpacerNode(TypedDict):
    kind: Literal["spacer"]


ExportNode = (
    ContainerNode
    | CardNode
    | TabsNode
    | PlotlyNode
    | TableNode
    | WidgetNode
    | HtmlNode
    | SpacerNode
)


class StaticPagePayload(TypedDict):
    kind: Literal["static_page"]
    content: ExportNode


class PageVariantsPayload(TypedDict):
    kind: Literal["page_variants"]
    selector_ids: list[str]
    default_key: str
    variants: dict[str, ExportNode]


PageContentPayload = StaticPagePayload | PageVariantsPayload


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
