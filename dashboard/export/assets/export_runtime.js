// Generated from dashboard/export/js_runtime by scripts/build_export_runtime.py
// BEGIN header.js
(function () {
  const SUPPORTED_SCHEMA_VERSION = "__EXPORT_SCHEMA_VERSION__";
  const dataElement = document.getElementById("activitysim-export-data");
  const app = document.getElementById("app");

  let payload = null;
  let state = null;
  let logger = null;
  let plotManager = null;
// END header.js

// BEGIN dom.js
  function el(tag, options, children) {
    const element = document.createElement(tag);
    const config = options || {};
    const childNodes = children || [];

    if (config.className) {
      element.className = config.className;
    }
    if (config.text !== undefined && config.text !== null) {
      element.textContent = String(config.text);
    }
    if (config.attrs) {
      Object.entries(config.attrs).forEach(([name, value]) => {
        if (value !== undefined && value !== null) {
          element.setAttribute(name, String(value));
        }
      });
    }
    if (config.style) {
      Object.entries(config.style).forEach(([name, value]) => {
        if (value !== undefined && value !== null) {
          element.style[name] = String(value);
        }
      });
    }

    appendChildren(element, childNodes);
    return element;
  }

  function appendChildren(parent, children) {
    (children || []).forEach((child) => {
      if (child !== undefined && child !== null) {
        parent.appendChild(child);
      }
    });
    return parent;
  }

  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function makeButton(label, active, onClick, className) {
    let disabled = false;
    let resolvedLabel = label;
    let resolvedActive = !!active;
    let resolvedOnClick = onClick;
    let resolvedClassName = className;

    if (typeof active === "object" && active !== null) {
      disabled = !!active.disabled;
      resolvedOnClick = active.onClick;
      resolvedClassName = active.className;
      resolvedActive = !!active.active;
      resolvedLabel = active.label || label;
    }

    const button = el("button", {
      className:
        resolvedClassName
        + (resolvedActive ? " active" : "")
        + (disabled ? " disabled" : ""),
      text: resolvedLabel,
    });
    button.type = "button";
    button.disabled = disabled;
    if (!disabled && typeof resolvedOnClick === "function") {
      button.addEventListener("click", resolvedOnClick);
    }
    return button;
  }
// END dom.js

// BEGIN errors.js
  class ExportRuntimeError extends Error {
    constructor(message, detail, code) {
      super(detail ? message + " " + String(detail) : message);
      this.name = "ExportRuntimeError";
      this.code = code || "EXPORT_RUNTIME_ERROR";
      this.detail = detail || null;
      this.displayMessage = message;
    }
  }

  function fail(message, detail, code) {
    throw new ExportRuntimeError(message, detail, code);
  }

  function createErrorPanel(message, detail) {
    const detailText =
      detail && detail.message ? detail.message : (detail || "");
    return el("div", { className: "export-error-panel" }, [
      el("h1", {
        className: "export-error-title",
        text: "Offline export failed to load",
      }),
      el("p", {
        className: "export-error-message",
        text: message,
      }),
      detailText
        ? el("p", {
            className: "export-error-message",
            text: detailText,
          })
        : null,
    ]);
  }

  function renderRuntimeError(message, detail) {
    console.error("[activitysim-export] " + message, detail);
    clearElement(app);
    app.appendChild(
      el("div", { className: "export-shell" }, [
        createErrorPanel(message, detail),
      ])
    );
  }
// END errors.js

// BEGIN debug.js
  function shouldEnableDebugLogging(candidate) {
    try {
      if (
        typeof window !== "undefined"
        && window.location
        && window.location.search
        && window.location.search.indexOf("debug_export=1") !== -1
      ) {
        return true;
      }
    } catch (error) {
      // Ignore URL parsing issues in restricted browser environments.
    }
    try {
      if (
        typeof window !== "undefined"
        && window.localStorage
        && window.localStorage.getItem("debug_export") === "1"
      ) {
        return true;
      }
    } catch (error) {
      // Ignore localStorage access failures.
    }
    return !!(candidate && candidate.debug);
  }

  function createLogger(enabled) {
    return {
      enabled: !!enabled,
      debug: function () {
        if (this.enabled) {
          const args = Array.prototype.slice.call(arguments);
          console.debug.apply(console, ["[activitysim-export]"].concat(args));
        }
      },
      warn: function () {
        const args = Array.prototype.slice.call(arguments);
        console.warn.apply(console, ["[activitysim-export]"].concat(args));
      },
      error: function () {
        const args = Array.prototype.slice.call(arguments);
        console.error.apply(console, ["[activitysim-export]"].concat(args));
      },
    };
  }

  function countNodeKinds(node, counts) {
    if (!node || typeof node !== "object") {
      return counts;
    }
    counts[node.kind || "unknown"] = (counts[node.kind || "unknown"] || 0) + 1;
    if (node.kind === "container" || node.kind === "card") {
      (node.children || []).forEach((child) => {
        countNodeKinds(child, counts);
      });
      return counts;
    }
    if (node.kind === "tabs") {
      (node.tabs || []).forEach((tab) => {
        countNodeKinds(tab.content, counts);
      });
      return counts;
    }
    if (node.kind === "region") {
      countNodeKinds(node.default_content, counts);
      Object.values(node.variants || {}).forEach((variantNode) => {
        countNodeKinds(variantNode, counts);
      });
      return counts;
    }
    return counts;
  }

  function logRuntimeSummary(candidate) {
    if (!logger || !logger.enabled) {
      return;
    }
    const pageDescriptors = candidate.pages || [];
    const selectorCount = pageDescriptors.reduce((total, page) => {
      const children = page.children || [];
      const childSelectors = children.reduce((childTotal, childPage) => {
        return childTotal + ((childPage.selectors || []).length);
      }, 0);
      return total + ((page.selectors || []).length) + childSelectors;
    }, 0);
    const stateKeys = Object.keys(candidate.states || {});
    const nodeCounts = {};
    stateKeys.forEach((stateId) => {
      Object.values(candidate.states[stateId] || {}).forEach((pageNode) => {
        if (pageNode && pageNode.kind === "page") {
          countNodeKinds(pageNode.content, nodeCounts);
        }
      });
    });
    logger.debug("Runtime summary", {
      schema_version: candidate.schema_version,
      pages: pageDescriptors.length,
      selectors: selectorCount,
      states: stateKeys.length,
      region_nodes: nodeCounts.region || 0,
      plot_nodes: nodeCounts.plotly || 0,
    });
  }
// END debug.js

// BEGIN schema.js
  function parsePayload() {
    if (!dataElement) {
      fail("Export payload script element was not found.", null, "PAYLOAD_ELEMENT_MISSING");
    }
    try {
      return JSON.parse(dataElement.textContent || "");
    } catch (error) {
      fail(
        "This HTML export is not compatible with the embedded client runtime.",
        error && error.message ? error.message : error,
        "PAYLOAD_PARSE_FAILED"
      );
    }
  }

  function validatePayloadSchema(candidate) {
    if (!candidate || typeof candidate !== "object") {
      fail("Export payload was missing or malformed.", null, "INVALID_PAYLOAD");
    }
    if (candidate.schema_version !== SUPPORTED_SCHEMA_VERSION) {
      fail(
        "Unsupported export schema version. Expected "
          + SUPPORTED_SCHEMA_VERSION
          + " but received "
          + String(candidate.schema_version || "<missing>")
          + ".",
        null,
        "SCHEMA_VERSION_UNSUPPORTED"
      );
    }
    if (!Array.isArray(candidate.pages)) {
      fail("Export payload is missing its page descriptors.", null, "MISSING_PAGE_DESCRIPTORS");
    }
    if (!candidate.default_state || typeof candidate.default_state !== "object") {
      fail("Export payload is missing its default dashboard state.", null, "MISSING_DEFAULT_STATE");
    }
    if (!candidate.states || typeof candidate.states !== "object") {
      fail("Export payload is missing required dashboard state data.", null, "MISSING_STATE_DATA");
    }
    if (!candidate.dashboard_controls || typeof candidate.dashboard_controls !== "object") {
      fail("Export payload is missing dashboard controls metadata.", null, "MISSING_DASHBOARD_CONTROLS");
    }
  }
// END schema.js

// BEGIN state.js
  function stateKey(currentState) {
    return currentState.weighting + "||" + currentState.values;
  }

  function findPageById(pageDescriptors, pageId) {
    return (pageDescriptors || []).find((page) => page.id === pageId) || null;
  }

  function hasChildren(pageDescriptor) {
    return !!(pageDescriptor && pageDescriptor.children && pageDescriptor.children.length);
  }

  function resolveActiveChildPageIdForState(pageDescriptor, currentState) {
    const childIds = (pageDescriptor.children || []).map((childPage) => childPage.id);
    if (!childIds.length) {
      return null;
    }

    const preferredChildId = currentState.activeChildPage[pageDescriptor.id];
    if (preferredChildId && childIds.indexOf(preferredChildId) !== -1) {
      return preferredChildId;
    }
    if (
      pageDescriptor.default_page_id
      && childIds.indexOf(pageDescriptor.default_page_id) !== -1
    ) {
      return pageDescriptor.default_page_id;
    }
    return childIds[0];
  }

  function resolveActiveChildPageId(pageDescriptor) {
    const activeChildId = resolveActiveChildPageIdForState(pageDescriptor, state);
    if (!activeChildId) {
      fail(
        "Grouped export page " + pageDescriptor.id + " is missing child pages.",
        null,
        "MISSING_CHILD_PAGES"
      );
    }
    state.activeChildPage[pageDescriptor.id] = activeChildId;
    return activeChildId;
  }

  function currentLeafPageId(currentPayload, currentState) {
    if (!currentState.activePage) {
      return null;
    }
    const page = findPageById(currentPayload.pages || [], currentState.activePage);
    if (!page) {
      return null;
    }
    if (hasChildren(page)) {
      return resolveActiveChildPageIdForState(page, currentState);
    }
    return page.id;
  }

  function getInitialState(candidate) {
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
      if (hasChildren(page)) {
        const defaultChildId = resolveActiveChildPageIdForState(page, initialState);
        initialState.activeChildPage[page.id] = defaultChildId;
        (page.children || []).forEach(registerLeafPage);
        return;
      }
      registerLeafPage(page);
    });

    return initialState;
  }

  function updateSelectorState(currentState, pageId, selectorId, value) {
    const nextState = {
      weighting: currentState.weighting,
      values: currentState.values,
      activePage: currentState.activePage,
      activeChildPage: Object.assign({}, currentState.activeChildPage),
      pageSelectors: Object.assign({}, currentState.pageSelectors),
    };
    const pageState = Object.assign({}, nextState.pageSelectors[pageId] || {});
    pageState[selectorId] = value;
    nextState.pageSelectors[pageId] = pageState;
    return nextState;
  }
// END state.js

// BEGIN plotly_lifecycle.js
  const PLOT_RESIZE_RETRY_DELAYS_MS = [60, 180, 320];

  function createPlotManager(config) {
    const plotly = config.plotly;
    const runtimeLogger = config.logger;
    const onRuntimeError = config.onRuntimeError;
    const plotFigures = new WeakMap();
    let resizeObserver = null;
    let resizeTimer = null;

    function resizePlots() {
      if (
        !plotly
        || !plotly.Plots
        || typeof plotly.Plots.resize !== "function"
      ) {
        return;
      }
      document.querySelectorAll(".plot-shell .js-plotly-plot").forEach((plot) => {
        try {
          plotly.Plots.resize(plot);
        } catch (error) {
          runtimeLogger.warn("Plot resize failed", error);
        }
      });
    }

    function scheduleResize() {
      if (
        !plotly
        || !plotly.Plots
        || typeof plotly.Plots.resize !== "function"
      ) {
        return;
      }
      requestAnimationFrame(() => {
        resizePlots();
        PLOT_RESIZE_RETRY_DELAYS_MS.forEach((delay) => {
          setTimeout(resizePlots, delay);
        });
      });
    }

    function debouncedScheduleResize() {
      if (resizeTimer) {
        clearTimeout(resizeTimer);
      }
      resizeTimer = setTimeout(scheduleResize, 40);
    }

    function renderPendingPlots(root) {
      if (!plotly || typeof plotly.react !== "function") {
        fail(
          "Plotly.react is unavailable in the embedded export runtime.",
          null,
          "PLOTLY_UNAVAILABLE"
        );
      }

      const scope = root || document;
      scope.querySelectorAll('.plot-shell[data-plot-pending="true"]').forEach((div) => {
        const figure = plotFigures.get(div) || { data: [], layout: {} };
        div.removeAttribute("data-plot-pending");
        Promise.resolve(
          plotly.react(div, figure.data || [], figure.layout || {}, {
            responsive: true,
            displayModeBar: false,
          })
        ).catch((error) => {
          onRuntimeError("Plot rendering failed while loading this export.", error);
        });
      });
    }

    function observeLayout(root) {
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      if (typeof ResizeObserver === "undefined") {
        return;
      }
      resizeObserver = new ResizeObserver(() => {
        debouncedScheduleResize();
      });
      (root || document).querySelectorAll(
        ".page-panel, .container-row, .container-column, .plot-shell"
      ).forEach((element) => {
        resizeObserver.observe(element);
      });
    }

    function disconnect() {
      if (resizeObserver) {
        resizeObserver.disconnect();
        resizeObserver = null;
      }
      if (resizeTimer) {
        clearTimeout(resizeTimer);
        resizeTimer = null;
      }
    }

    return {
      registerPlot: function (element, figure) {
        plotFigures.set(element, figure);
      },
      renderPendingPlots: renderPendingPlots,
      scheduleResize: scheduleResize,
      observeLayout: observeLayout,
      disconnect: disconnect,
    };
  }
// END plotly_lifecycle.js

// BEGIN renderers/widgets.js
  function updateActivePageSelector(selectorId, value) {
    const leafPageId = currentLeafPageId(payload, state);
    if (!leafPageId) {
      fail(
        "Cannot update a page selector because no active page is selected.",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    state = updateSelectorState(state, leafPageId, selectorId, value);
    renderApp();
  }

  function renderWidget(node) {
    const wrapper = el("div", { className: "widget-shell" }, [
      el("div", {
        className: "widget-label",
        text: node.name || "",
      }),
    ]);

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
      wrapper.appendChild(
        el("div", { className: "widget-radio-options" }, (node.options || []).map((option) => {
          return makeButton(
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
          );
        }))
      );
      return wrapper;
    }

    fail(
      "Unknown widget type encountered in export payload:",
      node.widget_type,
      "UNKNOWN_WIDGET_TYPE"
    );
  }
// END renderers/widgets.js

// BEGIN renderers/tables.js
  function renderTable(node) {
    const table = el("table", { className: "export-table" });
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    (node.columns || []).forEach((column) => {
      headRow.appendChild(el("th", { text: column }));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    (node.rows || []).forEach((row) => {
      const tr = document.createElement("tr");
      (node.columns || []).forEach((column) => {
        const value = row[column];
        tr.appendChild(
          el("td", {
            text: value == null ? "" : String(value),
          })
        );
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    return el("div", { className: "table-wrap" }, [table]);
  }
// END renderers/tables.js

// BEGIN renderers/tabs.js
  function renderTabs(node, leafPageId) {
    const root = document.createElement("div");
    let activeIndex = 0;
    const tabRow = el("div", { className: "local-tab-row" });
    const panel = el("div", { className: "local-tab-panel" });

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
        plotManager.renderPendingPlots(panel);
        plotManager.scheduleResize();
      });
    }

    paint();
    root.appendChild(tabRow);
    root.appendChild(panel);
    return root;
  }
// END renderers/tabs.js

// BEGIN renderers/plots.js
  function renderPlot(node) {
    const plotElement = el("div", {
      className: "plot-shell",
      attrs: { "data-plot-pending": "true" },
    });
    if (node.height) {
      plotElement.style.minHeight = String(node.height) + "px";
    }
    const baseFigure = node.figure || { data: [], layout: {} };
    const figure = {
      data: baseFigure.data || [],
      layout: Object.assign({}, baseFigure.layout || {}, {
        autosize: true,
        width: null,
      }),
    };
    plotManager.registerPlot(plotElement, figure);
    return plotElement;
  }
// END renderers/plots.js

// BEGIN renderers/regions.js
  function resolveRegionContent(node, leafPageId) {
    const pageSelectorState = state.pageSelectors[leafPageId] || {};
    const values = (node.selector_ids || []).map((selectorId) => {
      return pageSelectorState[selectorId];
    });
    const variantLookupKey = JSON.stringify(values);
    return (node.variants && node.variants[variantLookupKey]) || node.default_content;
  }

  function renderRegion(node, leafPageId) {
    return el("div", {
      className: "export-region",
      attrs: {
        "data-region-id": node.region_id || "",
        "data-leaf-page-id": leafPageId || "",
        "data-selector-ids": JSON.stringify(node.selector_ids || []),
      },
    }, [
      renderNode(resolveRegionContent(node, leafPageId), leafPageId),
    ]);
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
      (node.children || []).forEach((child) => {
        collectRegionNodes(child, regions);
      });
      return regions;
    }
    if (node.kind === "tabs") {
      (node.tabs || []).forEach((tab) => {
        collectRegionNodes(tab.content, regions);
      });
      return regions;
    }
    return regions;
  }

  function updateRenderedRegions(leafPageId, changedSelectorId) {
    const pagesForState = payload.states[stateKey(state)];
    if (!pagesForState) {
      return false;
    }
    const pageNode = pagesForState[leafPageId];
    if (!pageNode || pageNode.kind !== "page") {
      return false;
    }
    const regionNodes = collectRegionNodes(pageNode.content, []).filter((regionNode) => {
      return (regionNode.selector_ids || []).indexOf(changedSelectorId) !== -1;
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
      plotManager.renderPendingPlots(wrapper);
    });
    plotManager.scheduleResize();
    return true;
  }
// END renderers/regions.js

// BEGIN renderers/nodes.js
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

  function renderContainer(node, leafPageId) {
    const layoutClass = node.layout === "row" ? "container-row" : "container-column";
    const childCount = Number(node.child_count || (node.children || []).length || 0);
    const container = el("div", {
      className: layoutClass + " child-count-" + String(childCount),
    });
    (node.children || []).forEach((child) => {
      const wrapper = el("div", {
        className: "container-item container-item--" + nodeRole(child),
      }, [
        renderNode(child, leafPageId),
      ]);
      container.appendChild(wrapper);
    });
    return container;
  }

  function renderCard(node, leafPageId) {
    const card = el("div", { className: "card" });
    if (node.title) {
      card.appendChild(el("div", { className: "card-title", text: node.title }));
    }
    (node.children || []).forEach((child) => {
      card.appendChild(renderNode(child, leafPageId));
    });
    return card;
  }

  function renderTrustedHtml(node) {
    const div = document.createElement("div");
    // node.html is produced by dashboard-owned Python serializers.
    // Do not treat this as a safe sink for arbitrary untrusted user HTML.
    div.innerHTML = node.html || "";
    return div;
  }

  function renderSpacer(node) {
    const spacer = el("div", { className: "export-spacer" });
    if (node.height != null) {
      spacer.style.height = String(node.height) + "px";
    }
    if (node.width != null) {
      spacer.style.width = String(node.width) + "px";
    }
    return spacer;
  }

  const NODE_RENDERERS = {
    container: renderContainer,
    card: renderCard,
    html: renderTrustedHtml,
    plotly: renderPlot,
    table: renderTable,
    widget: renderWidget,
    tabs: renderTabs,
    spacer: renderSpacer,
    region: renderRegion,
  };

  function renderNode(node, leafPageId) {
    if (!node || typeof node !== "object") {
      fail("Encountered malformed export node content.", null, "INVALID_EXPORT_NODE");
    }
    const renderer = NODE_RENDERERS[node.kind];
    if (!renderer) {
      fail(
        "Unknown export node kind encountered:",
        node.kind,
        "UNKNOWN_NODE_KIND"
      );
    }
    return renderer(node, leafPageId);
  }
// END renderers/nodes.js

// BEGIN renderers/app.js
  function renderControls() {
    const shell = el("div", { className: "rail-card" }, [
      el("h2", {
        className: "rail-section-title",
        text: "Display Options",
      }),
      el("p", {
        className: "display-options-note",
        text: "Display mode controls.",
      }),
    ]);

    [
      ["Weighting", payload.dashboard_controls.weighting, "weighting"],
      ["Values", payload.dashboard_controls.values, "values"],
    ].forEach(([label, options, key]) => {
      const group = el("div", {
        className: "control-group",
        style: {
          marginTop: shell.children.length > 2 ? "16px" : "12px",
        },
      });
      group.appendChild(
        el("div", {
          className: "control-group-title",
          text: label,
        })
      );
      const chips = el("div", { className: "control-row" });
      const enabled = !!(
        payload.chrome
        && payload.chrome.controls_enabled
        && payload.chrome.controls_enabled[key]
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
    const shell = el("div", { className: "rail-card" }, [
      el("h2", {
        className: "rail-section-title",
        text: "Runs Loaded",
      }),
    ]);
    const list = el("div", { className: "run-legend-list" });
    const runs = payload.runs_loaded || [];
    if (!runs.length) {
      list.appendChild(
        el("p", {
          className: "run-legend-empty",
          text: "No runs loaded.",
        })
      );
    } else {
      runs.forEach((run) => {
        const runColor = run.color || "#94a3b8";
        const item = el("div", {
          className: "run-legend-item",
          attrs: {
            "data-run-label": run.label || "",
            "data-run-color": run.color || "",
          },
          style: {
            padding: "8px 10px",
            borderLeft: "4px solid " + runColor,
            margin: "6px 0",
            borderRadius: "6px",
            background: "rgba(127,127,127,0.06)",
          },
        }, [
          el("b", {
            text: run.label || "",
            style: {
              color: run.color || "",
            },
          }),
        ]);
        list.appendChild(item);
      });
    }
    shell.appendChild(list);
    return shell;
  }

  function renderRail() {
    const rail = el("aside", { className: "export-rail" });
    const sections = (payload.chrome && payload.chrome.rail_sections) || [];
    sections.forEach((section, index) => {
      if (section === "runs_loaded") {
        rail.appendChild(renderRunsLoaded());
        return;
      }
      if (section === "display_options") {
        if (index > 0) {
          rail.appendChild(el("div", { className: "rail-divider" }));
        }
        rail.appendChild(renderControls());
        return;
      }
      fail(
        "Unknown rail section encountered in export payload:",
        section,
        "UNKNOWN_RAIL_SECTION"
      );
    });
    return rail;
  }

  function renderPageTabs() {
    return el("div", { className: "page-tab-row" }, (payload.pages || []).map((page) => {
      return makeButton(
        page.title,
        page.id === state.activePage,
        () => {
          state.activePage = page.id;
          renderApp();
        },
        "page-tab-button"
      );
    }));
  }

  function renderChildPageTabs(pageDescriptor) {
    const activeChildId = resolveActiveChildPageId(pageDescriptor);
    return el("div", { className: "local-tab-row" }, (pageDescriptor.children || []).map((childPage) => {
      return makeButton(
        childPage.title,
        childPage.id === activeChildId,
        () => {
          state.activeChildPage[pageDescriptor.id] = childPage.id;
          renderApp();
        },
        "local-tab-button"
      );
    }));
  }

  function resolvePageContent(pageNode) {
    if (!pageNode || typeof pageNode !== "object") {
      fail(
        "Missing page state for the active dashboard selection.",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    if (pageNode.kind === "page") {
      return pageNode.content;
    }
    fail(
      "Unknown page content kind encountered:",
      pageNode.kind,
      "UNKNOWN_PAGE_CONTENT"
    );
  }

  function renderPagePanel() {
    const panel = el("div", { className: "page-panel" });
    const pagesForState = payload.states[stateKey(state)];
    if (!pagesForState) {
      fail(
        "Missing page state for dashboard combination " + stateKey(state) + ".",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    const pageDescriptor = findPageById(payload.pages || [], state.activePage);
    if (!pageDescriptor) {
      fail(
        "Missing page descriptor for active page " + state.activePage + ".",
        null,
        "MISSING_PAGE_DESCRIPTOR"
      );
    }

    let leafPageId = pageDescriptor.id;
    if (hasChildren(pageDescriptor)) {
      panel.appendChild(renderChildPageTabs(pageDescriptor));
      leafPageId = resolveActiveChildPageId(pageDescriptor);
    }

    panel.appendChild(renderNode(resolvePageContent(pagesForState[leafPageId]), leafPageId));
    return panel;
  }

  function renderShell() {
    const headerChildren = [
      el("h1", { text: payload.title }),
    ];
    if (payload.client_export_note && String(payload.client_export_note).trim()) {
      headerChildren.push(
        el("p", {
          className: "export-note",
          text: payload.client_export_note,
        })
      );
    }

    const main = el("main", { className: "export-main" }, [
      renderPageTabs(),
      renderPagePanel(),
    ]);

    return el("div", { className: "export-shell" }, [
      el("div", { className: "export-header" }, headerChildren),
      el("div", { className: "export-layout" }, [
        renderRail(),
        main,
      ]),
    ]);
  }

  function renderApp() {
    try {
      clearElement(app);
      app.appendChild(renderShell());
      plotManager.renderPendingPlots(app);
      plotManager.observeLayout(app);
      plotManager.scheduleResize();
    } catch (error) {
      renderRuntimeError(
        "This HTML export encountered a runtime rendering error.",
        error && error.message ? error.message : error
      );
    }
  }
// END renderers/app.js

// BEGIN index.js
  try {
    payload = parsePayload();
    validatePayloadSchema(payload);
    logger = createLogger(shouldEnableDebugLogging(payload));
    logRuntimeSummary(payload);
  } catch (error) {
    renderRuntimeError(
      "This HTML export is not compatible with the embedded client runtime.",
      error && error.message ? error.message : error
    );
    return;
  }

  state = getInitialState(payload);
  plotManager = createPlotManager({
    plotly: typeof Plotly === "undefined" ? null : Plotly,
    logger: logger,
    onRuntimeError: renderRuntimeError,
  });

  window.addEventListener("resize", () => {
    plotManager.scheduleResize();
  });

  renderApp();
})();
// END index.js
