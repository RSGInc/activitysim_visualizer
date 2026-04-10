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
from dashboard.components import set_percent_mode, set_run_colors
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from dashboard.page_registry import (
    all_page_definitions,
    build_export_raw_run_provider,
    build_registered_export_pages,
)
from runtime.config import Config, ExportSelectorRequest
from runtime.models import RunData
from summarize.cache import SummaryRun

LOGGER = get_logger("dashboard.export")


def build_export_html_document(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> str:
    """Build a self-contained client-side HTML export document."""
    payload = _build_export_payload(runs, config, summary_runs=summary_runs)
    payload_json = json.dumps(payload, default=_json_default).replace("</", "<\\/")
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
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> Path:
    """Write the standalone export HTML document to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_export_html_document(runs, config, summary_runs=summary_runs),
        encoding="utf-8",
    )
    return output_path


def _build_export_payload(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> dict[str, Any]:
    set_run_colors(config.run_colors)
    _validate_page_export_config(config)
    export_weight_values = config.export_html.panel_weighting_values()
    export_value_values = config.export_html.panel_value_values()
    state_payloads: dict[str, dict[str, Any]] = {}
    warned_unavailable_selectors: set[tuple[str, str]] = set()

    page_order: list[dict[str, str]] | None = None
    for weight_mode in export_weight_values:
        for value_mode in export_value_values:
            state_key = _state_key(weight_mode, value_mode)
            state_payloads[state_key] = _serialize_dashboard_state(
                runs,
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
        "client_export_note": (
            "Offline export uses client-side figure and table swapping for "
            "dashboard-level Weighting and Values controls. Supported page-level "
            "selectors currently include Long-Term > Geography, "
            "Tour Summary > Person Type, Joint Tours > HH Size, "
            "Destination > Purpose, Tour TOD > Purpose, Tour Mode > Purpose, "
            "Stop Frequency > Tour Purpose, Stop Timing > Purpose, and "
            "Trip Mode > Tour Purpose and Tour Mode."
        ),
    }


def _serialize_dashboard_state(
    runs: list[tuple[str, RunData]],
    config: Config,
    *,
    summary_runs: list[SummaryRun] | None = None,
    weight_mode: str,
    value_mode: str,
    warned_unavailable_selectors: set[tuple[str, str]],
) -> dict[str, Any]:
    raw_run_provider = build_export_raw_run_provider(runs, config)
    state = DashboardState(
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
        raw_run_provider=raw_run_provider,
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
    result: list[tuple[str, Any]] = []
    for index, child in enumerate(tabs.objects):
        title = tabs._names[index] if index < len(tabs._names) else f"Tab {index + 1}"
        result.append((title, child))
    return result


def _page_definition_for_page(page: Any) -> DashboardPageDefinition:
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


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


_EXPORT_CSS = """
body {
  margin: 0;
  font-family: Inter, 'Segoe UI', Arial, sans-serif;
  background: linear-gradient(180deg, #f6f8fb 0%, #eef3f9 100%);
  color: #1f2937;
}
.export-shell {
  max-width: 1600px;
  margin: 0 auto;
  padding: 24px;
}
.export-header {
  background: white;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 10px 35px rgba(31, 41, 55, 0.08);
  margin-bottom: 18px;
}
.export-header h1 {
  margin: 0 0 8px;
  font-size: 30px;
}
.export-note {
  color: #4b5563;
  margin: 0;
}
.control-row, .page-tab-row, .local-tab-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.control-panel {
  background: white;
  border-radius: 16px;
  padding: 18px 20px;
  box-shadow: 0 10px 35px rgba(31, 41, 55, 0.08);
  margin-bottom: 18px;
}
.control-group {
  display: inline-flex;
  flex-direction: column;
  gap: 8px;
  margin-right: 24px;
}
.control-group-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6b7280;
}
.toggle-chip {
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  color: #334155;
  border-radius: 999px;
  padding: 8px 14px;
  font-weight: 600;
  cursor: pointer;
}
.toggle-chip.active {
  background: #1f6feb;
  border-color: #1f6feb;
  color: white;
}
.page-tab-row {
  margin-bottom: 16px;
}
.page-tab-button, .local-tab-button {
  border: 1px solid #d4dbe5;
  background: white;
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
  font-weight: 600;
  color: #334155;
}
.page-tab-button.active, .local-tab-button.active {
  background: #0f172a;
  color: white;
  border-color: #0f172a;
}
.page-panel, .card, .widget-shell {
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 35px rgba(31, 41, 55, 0.08);
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
  background: #f8fafc;
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
  background: white;
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
  color: #6b7280;
  background: #f8fafc;
}
@media (max-width: 900px) {
  .export-shell {
    padding: 14px;
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
    const button = document.createElement("button");
    button.type = "button";
    button.className = className + (active ? " active" : "");
    button.textContent = label;
    button.addEventListener("click", onClick);
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
    shell.className = "control-panel";
    const row = document.createElement("div");
    row.className = "control-row";

    [
      ["Weighting", payload.dashboard_controls.weighting, "weighting"],
      ["Values", payload.dashboard_controls.values, "values"],
    ].forEach(([label, options, key]) => {
      const group = document.createElement("div");
      group.className = "control-group";
      const title = document.createElement("div");
      title.className = "control-group-title";
      title.textContent = label;
      group.appendChild(title);
      const chips = document.createElement("div");
      chips.className = "control-row";
      options.forEach((option) => {
        chips.appendChild(
          makeButton(
            option,
            state[key] === option,
            () => {
              state[key] = option;
              renderApp();
            },
            "toggle-chip"
          )
        );
      });
      group.appendChild(chips);
      row.appendChild(group);
    });

    shell.appendChild(row);
    return shell;
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
    const note = document.createElement("p");
    note.className = "export-note";
    note.textContent = payload.client_export_note;
    header.appendChild(title);
    header.appendChild(note);

    shell.appendChild(header);
    shell.appendChild(renderControls());
    shell.appendChild(renderPageTabs());
    shell.appendChild(renderPagePanel());
    app.appendChild(shell);
  }

  renderApp();
})();
"""
