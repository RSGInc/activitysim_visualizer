"""Embedded runtime assets for offline HTML export."""

from __future__ import annotations

from dashboard.export_types import EXPORT_SCHEMA_VERSION


EXPORT_CSS = """
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
.export-error-panel {
  background: #fff4f4;
  border: 1px solid #f0b6b6;
  border-left: 6px solid #c53d3d;
  border-radius: 16px;
  box-shadow: var(--shadow);
  padding: 20px 22px;
}
.export-error-title {
  margin: 0 0 8px;
  color: #7f1d1d;
  font-size: 22px;
}
.export-error-message {
  margin: 0;
  color: #5b2430;
  line-height: 1.5;
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


EXPORT_RUNTIME_JS = r"""
(function () {
  const SUPPORTED_SCHEMA_VERSION = "__EXPORT_SCHEMA_VERSION__";
  const dataElement = document.getElementById("activitysim-export-data");
  const app = document.getElementById("app");
  let payload = null;

  function clearElement(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function renderRuntimeError(message, detail) {
    console.error("[activitysim-export] " + message, detail);
    clearElement(app);

    const shell = document.createElement("div");
    shell.className = "export-shell";

    const panel = document.createElement("div");
    panel.className = "export-error-panel";

    const title = document.createElement("h1");
    title.className = "export-error-title";
    title.textContent = "Offline export failed to load";
    panel.appendChild(title);

    const body = document.createElement("p");
    body.className = "export-error-message";
    body.textContent = message;
    panel.appendChild(body);

    if (detail) {
      const extra = document.createElement("p");
      extra.className = "export-error-message";
      extra.textContent = String(detail);
      panel.appendChild(extra);
    }

    shell.appendChild(panel);
    app.appendChild(shell);
  }

  function validatePayloadSchema(candidate) {
    if (!candidate || typeof candidate !== "object") {
      throw new Error("Export payload was missing or malformed.");
    }
    if (candidate.schema_version !== SUPPORTED_SCHEMA_VERSION) {
      throw new Error(
        "Unsupported export schema version. Expected "
          + SUPPORTED_SCHEMA_VERSION
          + " but received "
          + String(candidate.schema_version || "<missing>")
          + "."
      );
    }
    if (!Array.isArray(candidate.pages)) {
      throw new Error("Export payload is missing its page descriptors.");
    }
    if (!candidate.default_state || !candidate.states) {
      throw new Error("Export payload is missing required dashboard state data.");
    }
  }

  try {
    payload = JSON.parse(dataElement.textContent);
    validatePayloadSchema(payload);
  } catch (error) {
    renderRuntimeError(
      "This HTML export is not compatible with the embedded client runtime.",
      error && error.message ? error.message : error
    );
    return;
  }

  const state = {
    weighting: payload.default_state.weighting,
    values: payload.default_state.values,
    activePage: payload.pages.length ? payload.pages[0].id : null,
    pageSelectors: {},
  };

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


def build_export_html_shell(*, title: str, payload_json: str, plotly_js: str) -> str:
    """Assemble the final self-contained HTML document."""
    runtime_js = EXPORT_RUNTIME_JS.replace(
        "__EXPORT_SCHEMA_VERSION__", EXPORT_SCHEMA_VERSION
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
{EXPORT_CSS}
  </style>
  <script>
{plotly_js}
  </script>
</head>
<body>
  <div id="app"></div>
  <script id="activitysim-export-data" type="application/json">{payload_json}</script>
  <script>
{runtime_js}
  </script>
</body>
</html>
"""
