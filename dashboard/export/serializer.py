"""Panel-to-payload serializer helpers for offline HTML export."""

from __future__ import annotations

import html
import json
from typing import Any

import markdown
import numpy as np
import pandas as pd
import panel as pn

from dashboard.export.types import ExportNode
from dashboard.page_definitions import DashboardPageDefinition


def serialize_viewable(
    obj: Any,
    *,
    disable_widgets: bool,
    widget_metadata: dict[int, tuple[str | None, dict[str, Any] | None]] | None = None,
) -> ExportNode:
    """Serialize a supported Panel viewable into the export JSON tree."""
    widget_metadata = widget_metadata or {}
    if isinstance(obj, pn.Card):
        return {
            "kind": "card",
            "title": obj.title or "",
            "children": [
                serialize_viewable(
                    child,
                    disable_widgets=disable_widgets,
                    widget_metadata=widget_metadata,
                )
                for child in obj.objects
            ],
        }
    if isinstance(obj, pn.Column):
        return {
            "kind": "container",
            "layout": "column",
            "children": [
                serialize_viewable(
                    child,
                    disable_widgets=disable_widgets,
                    widget_metadata=widget_metadata,
                )
                for child in obj.objects
            ],
        }
    if isinstance(obj, pn.Row):
        return {
            "kind": "container",
            "layout": "row",
            "children": [
                serialize_viewable(
                    child,
                    disable_widgets=disable_widgets,
                    widget_metadata=widget_metadata,
                )
                for child in obj.objects
            ],
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
                    ),
                }
                for title, child in iter_tabs(obj)
            ],
        }
    if isinstance(obj, pn.pane.Plotly):
        return {"kind": "plotly", "figure": obj.object.to_plotly_json()}
    if isinstance(obj, pn.widgets.Tabulator):
        frame = obj.value
        return {
            "kind": "table",
            "columns": [str(column) for column in frame.columns],
            "rows": frame.to_dict(orient="records"),
        }
    if isinstance(obj, pn.widgets.RadioButtonGroup):
        selector_id, selector_meta = widget_metadata.get(id(obj), (None, None))
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
            "name": obj.name or "",
            "value": obj.value,
            "options": options,
            "disabled": disabled,
            "selector_id": selector_id,
            "export_enabled": bool(selector_meta and selector_meta["export_enabled"]),
        }
    if isinstance(obj, pn.widgets.Select):
        selector_id, selector_meta = widget_metadata.get(id(obj), (None, None))
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
            "widget_type": "select",
            "name": obj.name or "",
            "value": obj.value,
            "options": options,
            "disabled": disabled,
            "selector_id": selector_id,
            "export_enabled": bool(selector_meta and selector_meta["export_enabled"]),
        }
    if isinstance(obj, pn.pane.Markdown):
        source = (
            obj.object if isinstance(obj.object, str) else obj.object._repr_markdown_()
        )
        return {"kind": "html", "html": markdown.markdown(source, extensions=["nl2br"])}
    if isinstance(obj, pn.pane.HTML):
        return {"kind": "html", "html": obj.object or ""}
    if isinstance(obj, pn.Spacer):
        return {"kind": "spacer"}
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
