"""Panel-to-payload serializer helpers for offline HTML export."""

from __future__ import annotations

import html
import inspect
import json
from typing import Any

import markdown
import numpy as np
import pandas as pd
import panel as pn

from dashboard.components import format_numeric_for_display
from dashboard.export.types import ExportNode
from dashboard.page_definitions import DashboardPageDefinition


def _serialize_table_cell(value: Any) -> Any:
    """Return export-ready display values for table cells.

    Export tables are rendered by the lightweight browser runtime rather than
    Tabulator, so we normalize numeric display here using the same
    significant-digit rule as live dashboard tables.
    """
    return format_numeric_for_display(sanitize_export_payload(value), precision=2)


def serialize_viewable(
    obj: Any,
    *,
    disable_widgets: bool,
    widget_metadata: dict[int, tuple[str | None, dict[str, Any] | None]] | None = None,
    region_nodes_by_id: dict[int, dict[str, Any]] | None = None,
    hidden_widget_ids: set[int] | None = None,
    hidden_view_ids: set[int] | None = None,
) -> ExportNode:
    """Serialize a supported Panel viewable into the export JSON tree."""
    widget_metadata = widget_metadata or {}
    region_nodes_by_id = region_nodes_by_id or {}
    hidden_widget_ids = hidden_widget_ids or set()
    hidden_view_ids = hidden_view_ids or set()

    def _is_hidden_view(viewable: Any) -> bool:
        if id(viewable) in hidden_view_ids:
            return True
        note_target_id = getattr(viewable, "_calculation_note_target_id", None)
        if note_target_id in hidden_view_ids:
            return True
        css_classes = set(getattr(viewable, "css_classes", []) or [])
        if not css_classes.intersection(
            {"calculation-note-section", "calculation-note-view"}
        ):
            return False
        return any(
            id(child) in hidden_view_ids
            for child in getattr(viewable, "objects", [])
        )

    if id(obj) in region_nodes_by_id:
        return region_nodes_by_id[id(obj)]

    def _container_styles(viewable: Any) -> dict[str, Any]:
        styles = getattr(viewable, "styles", None)
        if not isinstance(styles, dict):
            return {}
        return {str(key): value for key, value in styles.items() if value is not None}

    def _container_css_classes(viewable: Any) -> list[str]:
        css_classes = getattr(viewable, "css_classes", None)
        if not css_classes:
            return []
        return [str(css_class) for css_class in css_classes if css_class]
    if isinstance(obj, pn.Card):
        children = [
            serialize_viewable(
                child,
                disable_widgets=disable_widgets,
                widget_metadata=widget_metadata,
                region_nodes_by_id=region_nodes_by_id,
                hidden_widget_ids=hidden_widget_ids,
                hidden_view_ids=hidden_view_ids,
            )
            for child in obj.objects
            if not _is_hidden_view(child)
            and not (
                isinstance(child, pn.widgets.Widget) and id(child) in hidden_widget_ids
            )
        ]
        return {
            "kind": "card",
            "title": obj.title or "",
            "children": children,
        }
    if isinstance(obj, pn.Column):
        children = [
            serialize_viewable(
                child,
                disable_widgets=disable_widgets,
                widget_metadata=widget_metadata,
                region_nodes_by_id=region_nodes_by_id,
                hidden_widget_ids=hidden_widget_ids,
                hidden_view_ids=hidden_view_ids,
            )
            for child in obj.objects
            if not _is_hidden_view(child)
            and not (
                isinstance(child, pn.widgets.Widget) and id(child) in hidden_widget_ids
            )
        ]
        return {
            "kind": "container",
            "layout": "column",
            "child_count": len(children),
            "children": children,
            "styles": _container_styles(obj),
            "css_classes": _container_css_classes(obj),
        }
    if isinstance(obj, pn.Row):
        children = [
            serialize_viewable(
                child,
                disable_widgets=disable_widgets,
                widget_metadata=widget_metadata,
                region_nodes_by_id=region_nodes_by_id,
                hidden_widget_ids=hidden_widget_ids,
                hidden_view_ids=hidden_view_ids,
            )
            for child in obj.objects
            if not _is_hidden_view(child)
            and not (
                isinstance(child, pn.widgets.Widget) and id(child) in hidden_widget_ids
            )
        ]
        return {
            "kind": "container",
            "layout": "row",
            "child_count": len(children),
            "children": children,
            "styles": _container_styles(obj),
            "css_classes": _container_css_classes(obj),
        }
    if isinstance(obj, pn.Tabs):
        return {
            "kind": "tabs",
            "tabs": [
                {
                    "title": title,
                    "content": serialize_viewable(
                        child,
                        disable_widgets=disable_widgets,
                        widget_metadata=widget_metadata,
                        region_nodes_by_id=region_nodes_by_id,
                        hidden_widget_ids=hidden_widget_ids,
                        hidden_view_ids=hidden_view_ids,
                    ),
                }
                for title, child in iter_tabs(obj)
                if not _is_hidden_view(child)
            ],
        }
    if isinstance(obj, pn.pane.Plotly):
        figure = obj.object.to_plotly_json()
        layout = figure.get("layout", {}) if isinstance(figure, dict) else {}
        height = layout.get("height") if isinstance(layout, dict) else None
        return {"kind": "plotly", "figure": figure, "height": height}
    if isinstance(obj, pn.widgets.Tabulator):
        frame = obj.value
        title_map = {
            str(column): str(title)
            for column, title in (obj.titles or {}).items()
            if title is not None
        }
        columns = [str(column) for column in frame.columns]
        display_columns = [title_map.get(column, column) for column in columns]
        return {
            "kind": "table",
            "columns": display_columns,
            "rows": [
                {
                    display_column: _serialize_table_cell(row.get(column))
                    for column, display_column in zip(columns, display_columns)
                }
                for row in frame.to_dict(orient="records")
            ],
        }
    if isinstance(obj, pn.widgets.RadioButtonGroup):
        if id(obj) in hidden_widget_ids:
            return {"kind": "spacer", "height": 0, "width": 0}
        selector_id, selector_meta = widget_metadata.get(id(obj), (None, None))
        widget_name = (
            str(selector_meta.get("label"))
            if selector_meta and selector_meta.get("label")
            else obj.name or ""
        )
        options = list(obj.options)
        disabled = True if disable_widgets else bool(obj.disabled)
        if selector_meta:
            if selector_meta["export_enabled"]:
                options = list(selector_meta["resolved_values"])
                disabled = False
            else:
                disabled = True
        return {
            "kind": "widget",
            "widget_type": "radio_button_group",
            "name": widget_name,
            "value": obj.value,
            "options": options,
            "disabled": disabled,
            "selector_id": selector_id,
            "export_enabled": bool(selector_meta and selector_meta["export_enabled"]),
        }
    if isinstance(obj, pn.widgets.Select):
        if id(obj) in hidden_widget_ids:
            return {"kind": "spacer", "height": 0, "width": 0}
        selector_id, selector_meta = widget_metadata.get(id(obj), (None, None))
        widget_name = (
            str(selector_meta.get("label"))
            if selector_meta and selector_meta.get("label")
            else obj.name or ""
        )
        options = list(obj.options)
        disabled = True if disable_widgets else bool(obj.disabled)
        if selector_meta:
            if selector_meta["export_enabled"]:
                options = list(selector_meta["resolved_values"])
                disabled = False
            else:
                disabled = True
        payload = {
            "kind": "widget",
            "widget_type": "select",
            "name": widget_name,
            "value": obj.value,
            "options": options,
            "disabled": disabled,
            "selector_id": selector_id,
            "export_enabled": bool(selector_meta and selector_meta["export_enabled"]),
        }
        if selector_meta and selector_meta.get("parent_selector_id"):
            payload.update(
                {
                    "parent_selector_id": selector_meta["parent_selector_id"],
                    "options_by_parent_value": selector_meta.get(
                        "options_by_parent_value", {}
                    ),
                    "disabled_parent_values": selector_meta.get(
                        "disabled_parent_values", []
                    ),
                }
            )
        return payload
    if isinstance(obj, pn.widgets.Checkbox):
        if id(obj) in hidden_widget_ids:
            return {"kind": "spacer", "height": 0, "width": 0}
        selector_id, selector_meta = widget_metadata.get(id(obj), (None, None))
        widget_name = (
            str(selector_meta.get("label"))
            if selector_meta and selector_meta.get("label")
            else obj.name or ""
        )
        options = ["False", "True"]
        disabled = True if disable_widgets else bool(obj.disabled)
        if selector_meta:
            if selector_meta["export_enabled"]:
                options = list(selector_meta["resolved_values"])
                disabled = False
            else:
                disabled = True
        return {
            "kind": "widget",
            "widget_type": "checkbox",
            "name": widget_name,
            "value": "True" if obj.value else "False",
            "options": options,
            "disabled": disabled,
            "selector_id": selector_id,
            "export_enabled": bool(selector_meta and selector_meta["export_enabled"]),
        }
    if isinstance(obj, pn.widgets.FloatInput):
        if id(obj) in hidden_widget_ids:
            return {"kind": "spacer", "height": 0, "width": 0}
        selector_id, selector_meta = widget_metadata.get(id(obj), (None, None))
        widget_name = (
            str(selector_meta.get("label"))
            if selector_meta and selector_meta.get("label")
            else obj.name or ""
        )
        disabled = True if disable_widgets else bool(obj.disabled)
        if selector_meta and not selector_meta["export_enabled"]:
            disabled = True
        return {
            "kind": "widget",
            "widget_type": "float_input",
            "name": widget_name,
            "value": obj.value,
            "options": [],
            "step": obj.step,
            "disabled": disabled,
            "selector_id": selector_id,
            "export_enabled": bool(selector_meta and selector_meta["export_enabled"]),
        }
    if isinstance(obj, pn.widgets.Button):
        return {
            "kind": "widget",
            "widget_type": "button",
            "name": obj.name or "",
            "value": obj.name or "",
            "options": [],
            "step": None,
            "disabled": True if disable_widgets else bool(obj.disabled),
            "selector_id": None,
            "export_enabled": False,
        }
    if isinstance(obj, pn.pane.Markdown):
        source = (
            obj.object if isinstance(obj.object, str) else obj.object._repr_markdown_()
        )
        normalized_source = inspect.cleandoc(source)
        return {
            "kind": "html",
            "html": markdown.markdown(normalized_source, extensions=["nl2br"]),
        }
    if isinstance(obj, pn.pane.HTML):
        return {"kind": "html", "html": obj.object or ""}
    if isinstance(obj, pn.Spacer):
        height = getattr(obj, "height", None)
        width = getattr(obj, "width", None)
        return {"kind": "spacer", "height": height, "width": width}
    if isinstance(obj, str):
        return {"kind": "html", "html": html.escape(obj)}
    return {
        "kind": "html",
        "html": (
            "<div class='unsupported-export-item'>"
            f"Unsupported export item: {html.escape(type(obj).__name__)}"
            "</div>"
        ),
    }


def iter_tabs(tabs: pn.Tabs) -> list[tuple[str, Any]]:
    """Return tab titles paired with their child objects."""
    result: list[tuple[str, Any]] = []
    for index, child in enumerate(tabs.objects):
        title = tabs._names[index] if index < len(tabs._names) else f"Tab {index + 1}"
        result.append((title, child))
    return result


def page_definition_for_page(page: Any) -> DashboardPageDefinition:
    """Return the registered page definition attached to a page instance."""
    page_def = getattr(page, "definition", None)
    if isinstance(page_def, DashboardPageDefinition):
        return page_def
    raise ValueError(
        f"Dashboard page {type(page).__name__} is missing its registered PAGE definition."
    )


def variant_key(values: list[str] | tuple[str, ...]) -> str:
    """Return the stable string key used for selector combinations."""
    return json.dumps(list(values), separators=(",", ":"))


def sanitize_export_payload(value: Any) -> Any:
    """Recursively replace JSON-unsafe numeric values with null."""
    if isinstance(value, dict):
        return {key: sanitize_export_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_export_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_export_payload(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def json_default(value: Any) -> Any:
    """Serialize pandas/numpy scalars that standard ``json`` cannot handle."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
        return value
    if pd.isna(value):
        return None
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
