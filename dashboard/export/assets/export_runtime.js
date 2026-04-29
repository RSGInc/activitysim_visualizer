(function () {
  const SUPPORTED_SCHEMA_VERSION = "__EXPORT_SCHEMA_VERSION__";
  const dataElement = document.getElementById("activitysim-export-data");
  const app = document.getElementById("app");
  let payload = null;
  let resizeObserver = null;
  let resizeTimer = null;

  function debounce(fn, delay) {
    return () => {
      if (resizeTimer) {
        clearTimeout(resizeTimer);
      }
      resizeTimer = setTimeout(fn, delay);
    };
  }

  function schedulePlotResize() {
    if (typeof Plotly === "undefined" || !Plotly.Plots || typeof Plotly.Plots.resize !== "function") {
      return;
    }

    const resizePlots = () => {
      document.querySelectorAll(".plot-shell .js-plotly-plot").forEach((plot) => {
        try {
          Plotly.Plots.resize(plot);
        } catch (error) {
          console.warn("[activitysim-export] Plot resize failed", error);
        }
      });
    };

    requestAnimationFrame(() => {
      resizePlots();
      setTimeout(resizePlots, 60);
      setTimeout(resizePlots, 180);
      setTimeout(resizePlots, 320);
    });
  }

  const debouncedPlotResize = debounce(schedulePlotResize, 40);

  function initializePlots(root) {
    if (typeof Plotly === "undefined" || typeof Plotly.react !== "function") {
      fail("Plotly.react is unavailable in the embedded export runtime.");
    }

    const scope = root || document;
    scope.querySelectorAll('.plot-shell[data-plot-pending="true"]').forEach((div) => {
      const figure = div.__plotFigure || { data: [], layout: {} };
      delete div.__plotFigure;
      div.removeAttribute("data-plot-pending");
      Promise.resolve(
        Plotly.react(div, figure.data || [], figure.layout || {}, {
          responsive: true,
          displayModeBar: false,
        })
      ).catch((error) => {
        renderRuntimeError("Plot rendering failed while loading this export.", error);
      });
    });
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function createErrorPanel(message, detail) {
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

    return panel;
  }

  function renderRuntimeError(message, detail) {
    console.error("[activitysim-export] " + message, detail);
    clearElement(app);

    const shell = document.createElement("div");
    shell.className = "export-shell";
    shell.appendChild(createErrorPanel(message, detail));
    app.appendChild(shell);
  }

  function fail(message, detail) {
    throw new Error(detail ? message + " " + String(detail) : message);
  }

  function parsePayload() {
    if (!dataElement) {
      fail("Export payload script element was not found.");
    }
    try {
      return JSON.parse(dataElement.textContent || "");
    } catch (error) {
      fail(
        "This HTML export is not compatible with the embedded client runtime.",
        error && error.message ? error.message : error
      );
    }
  }

  function validatePayloadSchema(candidate) {
    if (!candidate || typeof candidate !== "object") {
      fail("Export payload was missing or malformed.");
    }
    if (candidate.schema_version !== SUPPORTED_SCHEMA_VERSION) {
      fail(
        "Unsupported export schema version. Expected "
          + SUPPORTED_SCHEMA_VERSION
          + " but received "
          + String(candidate.schema_version || "<missing>")
          + "."
      );
    }
    if (!Array.isArray(candidate.pages)) {
      fail("Export payload is missing its page descriptors.");
    }
    if (!candidate.default_state || typeof candidate.default_state !== "object") {
      fail("Export payload is missing its default dashboard state.");
    }
    if (!candidate.states || typeof candidate.states !== "object") {
      fail("Export payload is missing required dashboard state data.");
    }
    if (!candidate.dashboard_controls || typeof candidate.dashboard_controls !== "object") {
      fail("Export payload is missing dashboard controls metadata.");
    }
  }

  function initializeState(candidate) {
    const firstPage = candidate.pages.length ? candidate.pages[0] : null;
    const initialState = {
      weighting: candidate.default_state.weighting,
      values: candidate.default_state.values,
      activePage: firstPage ? firstPage.id : null,
      activeChildPage: {},
      pageSelectors: {},
    };

    function registerLeafPage(page) {
      const selectorState = {};
      (page.selectors || []).forEach((selector) => {
        if (selector.export_enabled) {
          selectorState[selector.id] = selector.default_value;
        }
      });
      initialState.pageSelectors[page.id] = selectorState;
    }

    (candidate.pages || []).forEach((page) => {
      if (page.children && page.children.length) {
        const defaultChildId = page.default_child_id || page.children[0].id;
        initialState.activeChildPage[page.id] = defaultChildId;
        page.children.forEach(registerLeafPage);
        return;
      }
      registerLeafPage(page);
    });

    return initialState;
  }

  try {
    payload = parsePayload();
    validatePayloadSchema(payload);
  } catch (error) {
    renderRuntimeError(
      "This HTML export is not compatible with the embedded client runtime.",
      error && error.message ? error.message : error
    );
    return;
  }

  const state = initializeState(payload);

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
    button.className =
      className + (active ? " active" : "") + (disabled ? " disabled" : "");
    button.textContent = label;
    button.disabled = disabled;
    if (!disabled) {
      button.addEventListener("click", onClick);
    }
    return button;
  }

  function currentLeafPageId() {
    if (!state.activePage) {
      return null;
    }
    const page = (payload.pages || []).find((item) => item.id === state.activePage);
    if (!page) {
      return null;
    }
    if (page.children && page.children.length) {
      return state.activeChildPage[page.id] || page.default_child_id || page.children[0].id;
    }
    return page.id;
  }

  function updateActivePageSelector(selectorId, value) {
    const leafPageId = currentLeafPageId();
    if (!leafPageId) {
      fail("Cannot update a page selector because no active page is selected.");
    }
    const pageState = state.pageSelectors[leafPageId] || {};
    pageState[selectorId] = value;
    state.pageSelectors[leafPageId] = pageState;
    if (!updateRenderedRegions(leafPageId, selectorId)) {
      renderApp();
    }
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
      (node.options || []).forEach((option) => {
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
          updateActivePageSelector(node.selector_id, select.value);
        });
      }
      wrapper.appendChild(select);
      return wrapper;
    }

    if (node.widget_type === "radio_button_group") {
      const options = document.createElement("div");
      options.className = "widget-radio-options";
      (node.options || []).forEach((option) => {
        options.appendChild(
          makeButton(
            option,
            {
              active: option === node.value,
              disabled: !!node.disabled,
              onClick: () => {
                if (node.export_enabled && node.selector_id) {
                  updateActivePageSelector(node.selector_id, option);
                }
              },
              className: "widget-radio-option",
            },
            null,
            "widget-radio-option"
          )
        );
      });
      wrapper.appendChild(options);
      return wrapper;
    }

    fail("Unknown widget type encountered in export payload:", node.widget_type);
  }

  function renderTable(node) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";

    const table = document.createElement("table");
    table.className = "export-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    (node.columns || []).forEach((column) => {
      const th = document.createElement("th");
      th.textContent = column;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    (node.rows || []).forEach((row) => {
      const tr = document.createElement("tr");
      (node.columns || []).forEach((column) => {
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

  function renderTabs(node, leafPageId) {
    const root = document.createElement("div");
    let activeIndex = 0;
    const tabRow = document.createElement("div");
    tabRow.className = "local-tab-row";
    const panel = document.createElement("div");
    panel.className = "local-tab-panel";

    function paint() {
      clearElement(tabRow);
      clearElement(panel);
      (node.tabs || []).forEach((tab, index) => {
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
      if (node.tabs && node.tabs[activeIndex]) {
        panel.appendChild(renderNode(node.tabs[activeIndex].content, leafPageId));
      }
      requestAnimationFrame(() => {
        initializePlots(panel);
        schedulePlotResize();
      });
    }

    paint();
    root.appendChild(tabRow);
    root.appendChild(panel);
    return root;
  }

  function renderPlot(node) {
    const div = document.createElement("div");
    div.className = "plot-shell";
    div.setAttribute("data-plot-pending", "true");
    if (node.height) {
      div.style.minHeight = String(node.height) + "px";
    }
    const baseFigure = node.figure || { data: [], layout: {} };
    const figure = {
      data: baseFigure.data || [],
      layout: Object.assign({}, baseFigure.layout || {}, {
        autosize: true,
        width: null,
      }),
    };
    div.__plotFigure = figure;
    return div;
  }

  function resolveRegionContent(node, leafPageId) {
    const pageSelectorState = state.pageSelectors[leafPageId] || {};
    const values = (node.selector_ids || []).map((selectorId) => {
      return pageSelectorState[selectorId];
    });
    const variantKey = JSON.stringify(values);
    return (
      (node.variants && node.variants[variantKey]) ||
      node.default_content
    );
  }

  function renderRegion(node, leafPageId) {
    const wrapper = document.createElement("div");
    wrapper.className = "export-region";
    wrapper.setAttribute("data-region-id", node.region_id || "");
    wrapper.setAttribute("data-leaf-page-id", leafPageId || "");
    wrapper.setAttribute("data-selector-ids", JSON.stringify(node.selector_ids || []));
    wrapper.appendChild(renderNode(resolveRegionContent(node, leafPageId), leafPageId));
    return wrapper;
  }

  function nodeRole(node) {
    if (!node || typeof node !== "object") {
      return "unknown";
    }
    if (node.kind === "plotly") {
      return "plot";
    }
    if (node.kind === "table") {
      return "table";
    }
    if (node.kind === "card") {
      return "card";
    }
    if (node.kind === "widget") {
      return "widget";
    }
    if (node.kind === "tabs") {
      return "tabs";
    }
    if (node.kind === "spacer") {
      return "spacer";
    }
    if (node.kind === "container") {
      return node.layout === "row" ? "row" : "column";
    }
    if (node.kind === "region") {
      return "region";
    }
    return "html";
  }

  function renderNode(node, leafPageId) {
    if (!node || typeof node !== "object") {
      fail("Encountered malformed export node content.");
    }

    if (node.kind === "container") {
      const container = document.createElement("div");
      const layoutClass = node.layout === "row" ? "container-row" : "container-column";
      const childCount = Number(node.child_count || (node.children || []).length || 0);
      container.className =
        layoutClass + " child-count-" + String(childCount);
      (node.children || []).forEach((child) => {
        const wrapper = document.createElement("div");
        wrapper.className =
          "container-item container-item--" + nodeRole(child);
        wrapper.appendChild(renderNode(child, leafPageId));
        container.appendChild(wrapper);
      });
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
      (node.children || []).forEach((child) => {
        card.appendChild(renderNode(child, leafPageId));
      });
      return card;
    }

    if (node.kind === "html") {
      const div = document.createElement("div");
      div.innerHTML = node.html || "";
      return div;
    }

    if (node.kind === "plotly") {
      return renderPlot(node);
    }

    if (node.kind === "table") {
      return renderTable(node);
    }

    if (node.kind === "widget") {
      return renderWidget(node);
    }

    if (node.kind === "tabs") {
      return renderTabs(node, leafPageId);
    }

    if (node.kind === "spacer") {
      const spacer = document.createElement("div");
      spacer.className = "export-spacer";
      if (node.height != null) {
        spacer.style.height = String(node.height) + "px";
      }
      if (node.width != null) {
        spacer.style.width = String(node.width) + "px";
      }
      return spacer;
    }

    if (node.kind === "region") {
      return renderRegion(node, leafPageId);
    }

    fail("Unknown export node kind encountered:", node.kind);
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
      group.style.marginTop = shell.children.length > 2 ? "16px" : "12px";

      const groupTitle = document.createElement("div");
      groupTitle.className = "control-group-title";
      groupTitle.textContent = label;
      group.appendChild(groupTitle);

      const chips = document.createElement("div");
      chips.className = "control-row";
      const enabled = !!(
        payload.chrome &&
        payload.chrome.controls_enabled &&
        payload.chrome.controls_enabled[key]
      );
      (options || []).forEach((option) => {
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

        const runLabel = document.createElement("b");
        runLabel.style.color = run.color || "";
        runLabel.textContent = run.label || "";
        item.appendChild(runLabel);
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
        return;
      }
      if (section === "display_options") {
        if (index > 0) {
          const divider = document.createElement("div");
          divider.className = "rail-divider";
          rail.appendChild(divider);
        }
        rail.appendChild(renderControls());
        return;
      }
      fail("Unknown rail section encountered in export payload:", section);
    });
    return rail;
  }

  function renderPageTabs() {
    const row = document.createElement("div");
    row.className = "page-tab-row";
    (payload.pages || []).forEach((page) => {
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

  function renderChildPageTabs(pageDescriptor) {
    const row = document.createElement("div");
    row.className = "local-tab-row";
    const activeChildId = resolveActiveChildPageId(pageDescriptor);
    (pageDescriptor.children || []).forEach((childPage) => {
      row.appendChild(
        makeButton(
          childPage.title,
          childPage.id === activeChildId,
          () => {
            state.activeChildPage[pageDescriptor.id] = childPage.id;
            renderApp();
          },
          "local-tab-button"
        )
      );
    });
    return row;
  }

  function resolveActiveChildPageId(pageDescriptor) {
    const childIds = (pageDescriptor.children || []).map((childPage) => childPage.id);
    if (!childIds.length) {
      fail("Grouped export page " + pageDescriptor.id + " is missing child pages.");
    }

    const preferredChildId = state.activeChildPage[pageDescriptor.id];
    if (preferredChildId && childIds.includes(preferredChildId)) {
      return preferredChildId;
    }
    if (pageDescriptor.default_child_id && childIds.includes(pageDescriptor.default_child_id)) {
      state.activeChildPage[pageDescriptor.id] = pageDescriptor.default_child_id;
      return pageDescriptor.default_child_id;
    }

    state.activeChildPage[pageDescriptor.id] = childIds[0];
    return childIds[0];
  }

  function resolvePageContent(pageNode) {
    if (!pageNode || typeof pageNode !== "object") {
      fail("Missing page state for the active dashboard selection.");
    }
    if (pageNode.kind === "page") {
      return pageNode.content;
    }
    fail("Unknown page content kind encountered:", pageNode.kind);
  }

  function renderPagePanel() {
    const panel = document.createElement("div");
    panel.className = "page-panel";

    const pagesForState = payload.states[stateKey()];
    if (!pagesForState) {
      fail("Missing page state for dashboard combination " + stateKey() + ".");
    }
    const pageDescriptor = (payload.pages || []).find((page) => page.id === state.activePage);
    if (!pageDescriptor) {
      fail("Missing page descriptor for active page " + state.activePage + ".");
    }
    let leafPageId = pageDescriptor.id;
    if (pageDescriptor.children && pageDescriptor.children.length) {
      panel.appendChild(renderChildPageTabs(pageDescriptor));
      leafPageId = resolveActiveChildPageId(pageDescriptor);
    }
    const pageNode = pagesForState[leafPageId];
    panel.appendChild(renderNode(resolvePageContent(pageNode), leafPageId));
    return panel;
  }

  function collectRegionNodes(node, regions) {
    if (!node || typeof node !== "object") {
      return regions;
    }
    if (node.kind === "region") {
      regions.push(node);
      return regions;
    }
    if (node.kind === "container" || node.kind === "card") {
      (node.children || []).forEach((child) => collectRegionNodes(child, regions));
      return regions;
    }
    if (node.kind === "tabs") {
      (node.tabs || []).forEach((tab) => collectRegionNodes(tab.content, regions));
      return regions;
    }
    return regions;
  }

  function updateRenderedRegions(leafPageId, changedSelectorId) {
    const pagesForState = payload.states[stateKey()];
    if (!pagesForState) {
      return false;
    }
    const pageNode = pagesForState[leafPageId];
    if (!pageNode || pageNode.kind !== "page") {
      return false;
    }
    const regionNodes = collectRegionNodes(pageNode.content, []).filter((regionNode) => {
      return (regionNode.selector_ids || []).includes(changedSelectorId);
    });
    if (!regionNodes.length) {
      return false;
    }
    regionNodes.forEach((regionNode) => {
      const wrapper = document.querySelector(
        '.export-region[data-leaf-page-id="' + leafPageId + '"][data-region-id="' + regionNode.region_id + '"]'
      );
      if (!wrapper) {
        return;
      }
      clearElement(wrapper);
      wrapper.appendChild(renderNode(resolveRegionContent(regionNode, leafPageId), leafPageId));
      initializePlots(wrapper);
    });
    schedulePlotResize();
    return true;
  }

  function renderShell() {
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
    return shell;
  }

  function renderApp() {
    try {
      clearElement(app);
      app.appendChild(renderShell());
      initializePlots(app);
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      if (typeof ResizeObserver !== "undefined") {
        resizeObserver = new ResizeObserver(() => {
          debouncedPlotResize();
        });
        document.querySelectorAll(".page-panel, .container-row, .container-column, .plot-shell").forEach((element) => {
          resizeObserver.observe(element);
        });
      }
      schedulePlotResize();
    } catch (error) {
      renderRuntimeError(
        "This HTML export encountered a runtime rendering error.",
        error && error.message ? error.message : error
      );
    }
  }

  window.addEventListener("resize", debouncedPlotResize);
  renderApp();
})();
