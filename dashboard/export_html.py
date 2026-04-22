"""Standalone single-file HTML export for offline dashboard viewing."""

from __future__ import annotations

import html
from itertools import product
import json
from pathlib import Path
from typing import Any

from activitysim_viz_logging import get_logger
import markdown
import numpy as np
import pandas as pd
import panel as pn
from plotly.offline import get_plotlyjs

from dashboard import DashboardState
from dashboard.components import (
    build_run_legend_entries,
    set_percent_mode,
    set_run_colors,
)
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from dashboard.page_registry import (
    all_page_definitions,
    build_export_prepared_run_provider,
    build_registered_export_pages,
)
from processor.models import RunData
from processor.summarize.cache import SummaryRun
from runtime.config import Config, ExportSelectorRequest

LOGGER = get_logger("dashboard.export")


def build_export_html_document(
    prepared_runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> str:
    """Build a self-contained HTML document for offline dashboard viewing."""
    payload = _sanitize_export_payload(
        _build_export_payload(prepared_runs, config, summary_runs=summary_runs)
    )
    payload_json = json.dumps(
        payload,
        default=_json_default,
        allow_nan=False,
    ).replace("</", "<\\/")
    plotly_js = get_plotlyjs()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(config.dashboard_title)}</title>
  <style>
{_EXPORT_CSS}
  </style>
  <script>
{plotly_js}
  </script>
</head>
<body>
  <div id="app"></div>
  <script id="activitysim-export-data" type="application/json">{payload_json}</script>
  <script>
{_EXPORT_RUNTIME_JS}
  </script>
</body>
</html>
"""


def write_export_html_document(
    output_path: str | Path,
    prepared_runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> Path:
    """Write the standalone export HTML document to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_export_html_document(prepared_runs, config, summary_runs=summary_runs),
        encoding="utf-8",
    )
    return output_path


def _build_export_payload(
    prepared_runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> dict[str, Any]:
    """Build the client-side payload consumed by the export runtime."""
    set_run_colors(config.run_colors)
    _validate_page_export_config(config)
    export_weight_values = config.export_html.panel_weighting_values()
    export_value_values = config.export_html.panel_value_values()
    prepared_run_provider = build_export_prepared_run_provider(prepared_runs, config)
    chrome_state = DashboardState(
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
        prepared_run_provider=prepared_run_provider,
    )
    state_payloads: dict[str, dict[str, Any]] = {}
    warned_unavailable_selectors: set[tuple[str, str]] = set()

    page_order: list[dict[str, str]] | None = None
    for weight_mode in export_weight_values:
        for value_mode in export_value_values:
            state_key = _state_key(weight_mode, value_mode)
            state_payloads[state_key] = _serialize_dashboard_state(
                prepared_runs,
                # Prepared runs are the only disaggregate contract the dashboard should see.
                config,
                summary_runs=summary_runs,
                weight_mode=weight_mode,
                value_mode=value_mode,
                warned_unavailable_selectors=warned_unavailable_selectors,
            )
            if page_order is None:
                page_order = state_payloads[state_key]["pages"]

    return {
        "title": config.dashboard_title,
        "runs_loaded": build_run_legend_entries(chrome_state.run_labels),
        "chrome": {
            "layout": "left_rail",
            "rail_sections": ["runs_loaded", "display_options"],
            "controls_enabled": {
                "weighting": len(export_weight_values) > 1,
                "values": len(export_value_values) > 1,
            },
        },
        "dashboard_controls": {
            "weighting": export_weight_values,
            "values": export_value_values,
        },
        "default_state": {
            "weighting": export_weight_values[0],
            "values": export_value_values[0],
        },
        "pages": page_order or [],
        "states": {
            key: payload["content_by_page"] for key, payload in state_payloads.items()
        },
        "page_export_support": {
            "client_side_runtime": "dashboard-and-page-selectors",
            "enabled_page_selectors": _enabled_page_selectors_payload(),
        },
        "client_runtime": "figure-swap-v1",
    }


def _serialize_dashboard_state(
    prepared_runs: list[tuple[str, RunData]],
    config: Config,
    *,
    summary_runs: list[SummaryRun] | None = None,
    weight_mode: str,
    value_mode: str,
    warned_unavailable_selectors: set[tuple[str, str]],
) -> dict[str, Any]:
    """Serialize one dashboard-level weighting/value state combination."""
    prepared_run_provider = build_export_prepared_run_provider(prepared_runs, config)
    state = DashboardState(
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
        prepared_run_provider=prepared_run_provider,
    )
    state.weight_mode = weight_mode
    state.value_mode = value_mode
    set_percent_mode(value_mode == "Percent")
    pages = build_registered_export_pages(state, config)

    page_defs: list[dict[str, str]] = []
    content_by_page: dict[str, Any] = {}
    for page in pages:
        page.refresh(force=True)
        if page.view is None:
            continue
        page_def = _page_definition_for_page(page)
        widget_metadata = _build_widget_metadata(
            page_def,
            page,
            config,
            warned_unavailable_selectors,
        )
        page_defs.append(
            {
                "id": page_def.page_id,
                "title": page_def.title,
                "selectors": [
                    selector_meta
                    for _, selector_meta in widget_metadata.values()
                    if selector_meta is not None
                ],
            }
        )
        content_by_page[page_def.page_id] = _serialize_page_content(
            page,
            page_def=page_def,
            config=config,
            widget_metadata=widget_metadata,
        )
    return {"pages": page_defs, "content_by_page": content_by_page}


def _serialize_page_content(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
    config: Config,
    widget_metadata: dict[int, tuple[str | None, dict[str, Any] | None]],
) -> dict[str, Any]:
    """Serialize one page, expanding selector variants when export-enabled."""
    enabled_selectors = [
        selector_meta
        for _, selector_meta in widget_metadata.values()
        if selector_meta is not None and selector_meta["export_enabled"]
    ]
    if not enabled_selectors:
        return {
            "kind": "static_page",
            "content": _serialize_viewable(
                page.view,
                disable_widgets=True,
                widget_metadata=widget_metadata,
            ),
        }

    selector_order = [selector_meta["id"] for selector_meta in enabled_selectors]
    selector_values = [
        selector_meta["resolved_values"] for selector_meta in enabled_selectors
    ]
    selector_widgets = {
        selector_def.selector_id: selector_def.widget_for(page)
        for selector_def in page_def.selectors
    }
    variants: dict[str, Any] = {}
    default_values = [
        selector_meta["default_value"] for selector_meta in enabled_selectors
    ]
    # Pre-render every supported selector combination so the static HTML can
    # swap between variants client-side without a Python backend.
    for combination in product(*selector_values):
        for selector_id, selected_value in zip(selector_order, combination):
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = selected_value
        page.refresh(force=True)
        variants[_variant_key(combination)] = _serialize_viewable(
            page.view,
            disable_widgets=False,
            widget_metadata=widget_metadata,
        )

    for selector_id, selected_value in zip(selector_order, default_values):
        widget = selector_widgets.get(selector_id)
        if widget is not None:
            widget.value = selected_value
    page.refresh(force=True)
    return {
        "kind": "page_variants",
        "selector_ids": selector_order,
        "default_key": _variant_key(default_values),
        "variants": variants,
    }


def _serialize_viewable(
    obj: Any,
    *,
    disable_widgets: bool,
    widget_metadata: dict[int, tuple[str | None, dict[str, Any] | None]] | None = None,
) -> dict[str, Any]:
    """Serialize a supported Panel viewable into the export JSON tree."""
    widget_metadata = widget_metadata or {}
    if isinstance(obj, pn.Card):
        return {
            "kind": "card",
            "title": obj.title or "",
            "children": [
                _serialize_viewable(
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
                _serialize_viewable(
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
                _serialize_viewable(
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
                    "content": _serialize_viewable(
                        child,
                        disable_widgets=disable_widgets,
                        widget_metadata=widget_metadata,
                    ),
                }
                for title, child in _iter_tabs(obj)
            ],
        }
    if isinstance(obj, pn.pane.Plotly):
        return {
            "kind": "plotly",
            "figure": obj.object.to_plotly_json(),
        }
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


def _iter_tabs(tabs: pn.Tabs) -> list[tuple[str, Any]]:
    """Return tab titles paired with their child objects."""
    result: list[tuple[str, Any]] = []
    for index, child in enumerate(tabs.objects):
        title = tabs._names[index] if index < len(tabs._names) else f"Tab {index + 1}"
        result.append((title, child))
    return result


def _page_definition_for_page(page: Any) -> DashboardPageDefinition:
    """Return the registered page definition attached to a page instance."""
    page_def = getattr(page, "definition", None)
    if isinstance(page_def, DashboardPageDefinition):
        return page_def
    raise ValueError(
        f"Dashboard page {type(page).__name__} is missing its registered PAGE definition."
    )


def _build_widget_metadata(
    page_def: DashboardPageDefinition,
    page: Any,
    config: Config,
    warned_unavailable_selectors: set[tuple[str, str]],
) -> dict[int, tuple[str | None, dict[str, Any] | None]]:
    """Build selector metadata keyed by widget identity for serialization."""
    metadata: dict[int, tuple[str | None, dict[str, Any] | None]] = {}
    for selector_def in page_def.selectors:
        selector_meta = _resolve_selector_metadata(
            page_def,
            selector_def,
            page,
            config,
            warned_unavailable_selectors,
        )
        widget = selector_def.widget_for(page)
        if widget is not None:
            metadata[id(widget)] = (selector_def.selector_id, selector_meta)
    return metadata


def _resolve_selector_metadata(
    page_def: DashboardPageDefinition,
    selector_def: PageSelectorDefinition,
    page: Any,
    config: Config,
    warned_unavailable_selectors: set[tuple[str, str]],
) -> dict[str, Any]:
    """Resolve one page selector into export metadata."""
    page_id = page_def.page_id
    selector_id = selector_def.selector_id
    request = config.export_html.selector_request(page_id, selector_id)
    configured = selector_id in config.export_html.pages.get(page_id, {})
    widget = selector_def.widget_for(page)
    available = selector_def.available_for(page, config)
    export_enabled = bool(selector_def.exportable)

    if not available or widget is None:
        if configured:
            warning_key = (page_id, selector_id)
            if warning_key not in warned_unavailable_selectors:
                LOGGER.warning(
                    "Warning: "
                    f"visualizer.export_html.pages.{page_id}.{selector_id} is configured, "
                    "but the selector is unavailable for this export. "
                    "Ignoring the configuration and exporting the page with its fallback layout."
                )
                warned_unavailable_selectors.add(warning_key)
        return {
            "id": selector_id,
            "label": selector_def.label,
            "available": False,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [],
            "default_value": None,
            "options": [],
            "export_enabled": False,
        }

    options = [str(option) for option in widget.options]
    default_value = str(widget.value)
    resolved_values = _resolve_selector_values(
        request=request,
        options=options,
        default_value=default_value,
        field_name=f"visualizer.export_html.pages.{page_id}.{selector_id}",
    )
    return {
        "id": selector_id,
        "label": selector_def.label,
        "available": True,
        "request_mode": request.mode,
        "requested_values": list(request.values),
        "resolved_values": resolved_values,
        "default_value": default_value,
        "options": options,
        "export_enabled": export_enabled,
    }


def _resolve_selector_values(
    *,
    request: ExportSelectorRequest,
    options: list[str],
    default_value: str,
    field_name: str,
) -> list[str]:
    """Resolve configured selector requests against actual widget options."""
    if request.mode == "default":
        return [default_value]
    if request.mode == "all":
        if not options:
            raise ValueError(f"{field_name} resolved to no values.")
        return list(options)

    option_lookup = {option.strip().lower(): option for option in options}
    resolved: list[str] = []
    invalid: list[str] = []
    for token in request.values:
        option = option_lookup.get(token)
        if option is None:
            invalid.append(token)
            continue
        if option not in resolved:
            resolved.append(option)
    if invalid:
        raise ValueError(
            f"Unsupported {field_name} values: "
            + ", ".join(repr(token) for token in invalid)
        )
    if not resolved:
        raise ValueError(f"{field_name} resolved to no values.")
    return resolved


def _validate_page_export_config(config: Config) -> None:
    """Validate export page and selector ids against the live registry."""
    known_pages = {page.page_id: page for page in all_page_definitions()}
    unknown_pages = sorted(
        page_id for page_id in config.export_html.pages if page_id not in known_pages
    )
    if unknown_pages:
        raise ValueError(
            "Unsupported visualizer.export_html.pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_pages)
        )

    for page_id, selectors in config.export_html.pages.items():
        known_selectors = {
            selector.selector_id for selector in known_pages[page_id].selectors
        }
        unknown_selectors = sorted(
            selector_id
            for selector_id in selectors
            if selector_id not in known_selectors
        )
        if unknown_selectors:
            raise ValueError(
                f"Unsupported visualizer.export_html.pages.{page_id} entries: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )


def _enabled_page_selectors_payload() -> list[dict[str, str]]:
    """Return every exportable page selector in stable sorted order."""
    return sorted(
        [
            {"page_id": page.page_id, "selector_id": selector.selector_id}
            for page in all_page_definitions()
            for selector in page.selectors
            if selector.exportable
        ],
        key=lambda item: (item["page_id"], item["selector_id"]),
    )


def _state_key(weight_mode: str, value_mode: str) -> str:
    return f"{weight_mode}||{value_mode}"


def _variant_key(values: list[str] | tuple[str, ...]) -> str:
    return json.dumps(list(values), separators=(",", ":"))


def _sanitize_export_payload(value: Any) -> Any:
    """Recursively replace JSON-unsafe numeric values with null."""
    if isinstance(value, dict):
        return {key: _sanitize_export_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_export_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_export_payload(item) for item in value]
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


def _json_default(value: Any) -> Any:
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


_EXPORT_CSS = """
:root {
  --accent: #4E79A7;
  --accent-dark: #315c88;
  --ink: #1f2937;
  --muted: #6b7280;
  --line: #d4dbe5;
  --surface: #ffffff;
  --surface-soft: #f8fafc;
  --shadow: 0 10px 35px rgba(31, 41, 55, 0.08);
}
body {
  margin: 0;
  font-family: Inter, 'Segoe UI', Arial, sans-serif;
  background: linear-gradient(180deg, #f6f8fb 0%, #eef3f9 100%);
  color: var(--ink);
}
.export-shell {
  max-width: 1680px;
  margin: 0 auto;
  padding: 24px;
}
.export-header {
  background: var(--surface);
  border-radius: 16px;
  padding: 24px;
  box-shadow: var(--shadow);
  margin-bottom: 20px;
  border-top: 8px solid var(--accent);
}
.export-header h1 {
  margin: 0 0 8px;
  font-size: 30px;
}
.export-note {
  color: #4b5563;
  margin: 0;
}
.export-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.export-rail, .export-main {
  min-width: 0;
}
.export-rail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.rail-card, .page-panel, .card, .widget-shell {
  background: var(--surface);
  border-radius: 16px;
  box-shadow: var(--shadow);
}
.rail-card {
  padding: 18px 20px;
}
.rail-section-title {
  margin: 0 0 12px;
  font-size: 22px;
  line-height: 1.2;
}
.run-legend-list {
  display: flex;
  flex-direction: column;
}
.run-legend-item {
  font-size: 14px;
}
.run-legend-empty, .display-options-note {
  font-size: 12px;
  color: #666;
  margin: 0;
}
.rail-divider {
  height: 1px;
  background: rgba(148, 163, 184, 0.28);
  margin: 6px 0 0;
}
.control-row, .page-tab-row, .local-tab-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.control-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.control-group-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}
.toggle-chip {
  border: 1px solid #cbd5e1;
  background: var(--surface-soft);
  color: #334155;
  border-radius: 999px;
  padding: 8px 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.toggle-chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--surface);
}
.toggle-chip.disabled {
  cursor: default;
  opacity: 0.7;
}
.page-tab-row {
  margin-bottom: 16px;
}
.page-tab-button, .local-tab-button {
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
  font-weight: 600;
  color: #334155;
}
.page-tab-button.active, .local-tab-button.active {
  background: var(--accent);
  color: var(--surface);
  border-color: var(--accent);
}
.page-panel {
  padding: 22px;
}
.container-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: stretch;
}
.container-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.container-row > * {
  flex: 1 1 320px;
}
.card {
  padding: 14px 16px;
}
.card-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 10px;
}
.widget-shell {
  padding: 14px 16px;
  display: inline-flex;
  flex-direction: column;
  gap: 8px;
  min-width: 220px;
}
.widget-label {
  font-size: 13px;
  color: #6b7280;
  font-weight: 700;
}
.widget-shell select {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid #cbd5e1;
  background: var(--surface-soft);
}
.widget-radio-options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.widget-radio-option {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #475569;
  font-weight: 600;
}
.widget-radio-option.active {
  background: #dbeafe;
  border-color: #93c5fd;
  color: #1d4ed8;
}
.table-wrap {
  overflow-x: auto;
}
table.export-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
}
table.export-table th,
table.export-table td {
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
  text-align: left;
  font-size: 14px;
}
table.export-table thead th {
  background: #f8fafc;
}
.local-tab-panel {
  margin-top: 12px;
}
.unsupported-export-item {
  padding: 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  color: var(--muted);
  background: var(--surface-soft);
}
@media (max-width: 900px) {
  .export-shell {
    padding: 14px;
  }
  .export-layout {
    grid-template-columns: 1fr;
  }
  .page-panel {
    padding: 16px;
  }
}
"""


_EXPORT_RUNTIME_JS = r"""
(function () {
  const payload = JSON.parse(document.getElementById("activitysim-export-data").textContent);
  const state = {
    weighting: payload.default_state.weighting,
    values: payload.default_state.values,
    activePage: payload.pages.length ? payload.pages[0].id : null,
    pageSelectors: {},
  };

  const app = document.getElementById("app");

  (payload.pages || []).forEach((page) => {
    const selectorState = {};
    (page.selectors || []).forEach((selector) => {
      if (selector.export_enabled) {
        selectorState[selector.id] = selector.default_value;
      }
    });
    state.pageSelectors[page.id] = selectorState;
  });

  function stateKey() {
    return state.weighting + "||" + state.values;
  }

  function clearElement(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function makeButton(label, active, onClick, className) {
    let disabled = false;
    if (typeof active === "object" && active !== null) {
      const config = active;
      disabled = !!config.disabled;
      onClick = config.onClick;
      className = config.className;
      active = !!config.active;
      label = config.label || label;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = className + (active ? " active" : "") + (disabled ? " disabled" : "");
    button.textContent = label;
    button.disabled = disabled;
    if (!disabled) {
      button.addEventListener("click", onClick);
    }
    return button;
  }

  function renderWidget(node) {
    const wrapper = document.createElement("div");
    wrapper.className = "widget-shell";
    const label = document.createElement("div");
    label.className = "widget-label";
    label.textContent = node.name || "";
    wrapper.appendChild(label);

    if (node.widget_type === "select") {
      const select = document.createElement("select");
      select.disabled = !!node.disabled;
      node.options.forEach((option) => {
        const opt = document.createElement("option");
        opt.value = option;
        opt.textContent = option;
        if (option === node.value) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
      if (node.export_enabled && node.selector_id) {
        select.addEventListener("change", () => {
          const pageState = state.pageSelectors[state.activePage] || {};
          pageState[node.selector_id] = select.value;
          state.pageSelectors[state.activePage] = pageState;
          renderApp();
        });
      }
      wrapper.appendChild(select);
      return wrapper;
    }

    const options = document.createElement("div");
    options.className = "widget-radio-options";
    node.options.forEach((option) => {
      const chip = document.createElement("div");
      chip.className = "widget-radio-option" + (option === node.value ? " active" : "");
      chip.textContent = option;
      options.appendChild(chip);
    });
    wrapper.appendChild(options);
    return wrapper;
  }

  function renderTable(node) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    table.className = "export-table";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    node.columns.forEach((column) => {
      const th = document.createElement("th");
      th.textContent = column;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    node.rows.forEach((row) => {
      const tr = document.createElement("tr");
      node.columns.forEach((column) => {
        const td = document.createElement("td");
        const value = row[column];
        td.textContent = value == null ? "" : String(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function renderTabs(node) {
    const root = document.createElement("div");
    let activeIndex = 0;
    const tabRow = document.createElement("div");
    tabRow.className = "local-tab-row";
    const panel = document.createElement("div");
    panel.className = "local-tab-panel";

    function paint() {
      clearElement(tabRow);
      clearElement(panel);
      node.tabs.forEach((tab, index) => {
        tabRow.appendChild(
          makeButton(
            tab.title,
            index === activeIndex,
            () => {
              activeIndex = index;
              paint();
            },
            "local-tab-button"
          )
        );
      });
      if (node.tabs[activeIndex]) {
        panel.appendChild(renderNode(node.tabs[activeIndex].content));
      }
    }

    paint();
    root.appendChild(tabRow);
    root.appendChild(panel);
    return root;
  }

  function renderNode(node) {
    if (!node) {
      return document.createElement("div");
    }
    if (node.kind === "container") {
      const container = document.createElement("div");
      container.className = node.layout === "row" ? "container-row" : "container-column";
      (node.children || []).forEach((child) => container.appendChild(renderNode(child)));
      return container;
    }
    if (node.kind === "card") {
      const card = document.createElement("div");
      card.className = "card";
      if (node.title) {
        const title = document.createElement("div");
        title.className = "card-title";
        title.textContent = node.title;
        card.appendChild(title);
      }
      (node.children || []).forEach((child) => card.appendChild(renderNode(child)));
      return card;
    }
    if (node.kind === "html") {
      const div = document.createElement("div");
      div.innerHTML = node.html || "";
      return div;
    }
    if (node.kind === "plotly") {
      const div = document.createElement("div");
      const figure = node.figure || {data: [], layout: {}};
      Plotly.newPlot(div, figure.data || [], figure.layout || {}, {
        responsive: true,
        displayModeBar: false,
      });
      return div;
    }
    if (node.kind === "table") {
      return renderTable(node);
    }
    if (node.kind === "widget") {
      return renderWidget(node);
    }
    if (node.kind === "tabs") {
      return renderTabs(node);
    }
    return document.createElement("div");
  }

  function renderControls() {
    const shell = document.createElement("div");
    shell.className = "rail-card";
    const title = document.createElement("h2");
    title.className = "rail-section-title";
    title.textContent = "Display Options";
    shell.appendChild(title);

    const note = document.createElement("p");
    note.className = "display-options-note";
    note.textContent = "Display mode controls.";
    shell.appendChild(note);

    [
      ["Weighting", payload.dashboard_controls.weighting, "weighting"],
      ["Values", payload.dashboard_controls.values, "values"],
    ].forEach(([label, options, key]) => {
      const group = document.createElement("div");
      group.className = "control-group";
      if (shell.children.length > 2) {
        group.style.marginTop = "16px";
      } else {
        group.style.marginTop = "12px";
      }
      const title = document.createElement("div");
      title.className = "control-group-title";
      title.textContent = label;
      group.appendChild(title);
      const chips = document.createElement("div");
      chips.className = "control-row";
      const enabled = !!(payload.chrome && payload.chrome.controls_enabled && payload.chrome.controls_enabled[key]);
      options.forEach((option) => {
        chips.appendChild(
          makeButton(
            option,
            {
              active: state[key] === option,
              disabled: !enabled,
              onClick: () => {
                state[key] = option;
                renderApp();
              },
              className: "toggle-chip",
            },
            null,
            "toggle-chip"
          )
        );
      });
      group.appendChild(chips);
      shell.appendChild(group);
    });

    return shell;
  }

  function renderRunsLoaded() {
    const shell = document.createElement("div");
    shell.className = "rail-card";

    const title = document.createElement("h2");
    title.className = "rail-section-title";
    title.textContent = "Runs Loaded";
    shell.appendChild(title);

    const list = document.createElement("div");
    list.className = "run-legend-list";
    const runs = payload.runs_loaded || [];
    if (!runs.length) {
      const empty = document.createElement("p");
      empty.className = "run-legend-empty";
      empty.textContent = "No runs loaded.";
      list.appendChild(empty);
    } else {
      runs.forEach((run) => {
        const item = document.createElement("div");
        item.className = "run-legend-item";
        item.setAttribute("data-run-label", run.label || "");
        item.setAttribute("data-run-color", run.color || "");
        item.style.padding = "8px 10px";
        item.style.borderLeft = "4px solid " + (run.color || "#94a3b8");
        item.style.margin = "6px 0";
        item.style.borderRadius = "6px";
        item.style.background = "rgba(127,127,127,0.06)";
        const label = document.createElement("b");
        label.style.color = run.color || "";
        label.textContent = run.label || "";
        item.appendChild(label);
        list.appendChild(item);
      });
    }
    shell.appendChild(list);
    return shell;
  }

  function renderRail() {
    const rail = document.createElement("aside");
    rail.className = "export-rail";
    const sections = (payload.chrome && payload.chrome.rail_sections) || [];
    sections.forEach((section, index) => {
      if (section === "runs_loaded") {
        rail.appendChild(renderRunsLoaded());
      } else if (section === "display_options") {
        if (index > 0) {
          const divider = document.createElement("div");
          divider.className = "rail-divider";
          rail.appendChild(divider);
        }
        rail.appendChild(renderControls());
      }
    });
    return rail;
  }

  function renderPageTabs() {
    const row = document.createElement("div");
    row.className = "page-tab-row";
    payload.pages.forEach((page) => {
      row.appendChild(
        makeButton(
          page.title,
          page.id === state.activePage,
          () => {
            state.activePage = page.id;
            renderApp();
          },
          "page-tab-button"
        )
      );
    });
    return row;
  }

  function renderPagePanel() {
    const panel = document.createElement("div");
    panel.className = "page-panel";
    const pagesForState = payload.states[stateKey()] || {};
    const pageNode = pagesForState[state.activePage];
    panel.appendChild(renderNode(resolvePageContent(pageNode)));
    return panel;
  }

  function resolvePageContent(pageNode) {
    if (!pageNode) {
      return null;
    }
    if (pageNode.kind === "static_page") {
      return pageNode.content;
    }
    if (pageNode.kind === "page_variants") {
      const values = (pageNode.selector_ids || []).map((selectorId) => {
        const pageSelectorState = state.pageSelectors[state.activePage] || {};
        return pageSelectorState[selectorId];
      });
      const variantKey = JSON.stringify(values);
      return pageNode.variants[variantKey] || pageNode.variants[pageNode.default_key] || null;
    }
    return pageNode;
  }

  function renderApp() {
    clearElement(app);
    const shell = document.createElement("div");
    shell.className = "export-shell";

    const header = document.createElement("div");
    header.className = "export-header";
    const title = document.createElement("h1");
    title.textContent = payload.title;
    header.appendChild(title);
    if (payload.client_export_note && String(payload.client_export_note).trim()) {
      const note = document.createElement("p");
      note.className = "export-note";
      note.textContent = payload.client_export_note;
      header.appendChild(note);
    }

    shell.appendChild(header);
    const layout = document.createElement("div");
    layout.className = "export-layout";
    layout.appendChild(renderRail());

    const main = document.createElement("main");
    main.className = "export-main";
    main.appendChild(renderPageTabs());
    main.appendChild(renderPagePanel());
    layout.appendChild(main);

    shell.appendChild(layout);
    app.appendChild(shell);
  }

  renderApp();
})();
"""
