// Generated from dashboard/export/js_runtime by dashboard/export/build_export_runtime.py
// BEGIN header.js
(function () {
  /**
   * Runtime bootstrap header.
   *
   * This file intentionally keeps only DOM entrypoints and constants at module
   * scope. All export payload, state, and rendering dependencies are threaded
   * through explicit runtime context objects created in index.js.
   */
  const SUPPORTED_SCHEMA_VERSION = "__EXPORT_SCHEMA_VERSION__";
  const dataElement = document.getElementById("activitysim-export-data");
  const app = document.getElementById("app");
// END header.js

// BEGIN dom.js
  /**
   * DOM helpers used by the export runtime.
   *
   * These helpers are intentionally small and explicit so Python developers can
   * read the renderers as plain "build element tree" code.
   */

  /**
   * Create a DOM element and apply a small set of supported properties.
   */
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

  /**
   * Append child nodes while ignoring null placeholders produced by render code.
   */
  function appendChildren(parent, children) {
    for (const child of children || []) {
      if (child !== undefined && child !== null) {
        parent.appendChild(child);
      }
    }
    return parent;
  }

  /**
   * Remove all current children before repainting a container.
   */
  function clearElement(element) {
    while (element && element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  /**
   * Build a button from a single config object.
   *
   * The previous overloaded helper accepted multiple call styles, which made
   * call sites harder to scan. The runtime now uses one explicit API.
   */
  function makeButton(config) {
    const button = el("button", {
      className:
        (config.className || "")
        + (config.active ? " active" : "")
        + (config.disabled ? " disabled" : ""),
      text: config.label,
    });
    button.type = "button";
    button.disabled = !!config.disabled;
    if (!config.disabled && typeof config.onClick === "function") {
      button.addEventListener("click", config.onClick);
    }
    return button;
  }
// END dom.js

// BEGIN errors.js
  /**
   * Runtime error helpers.
   *
   * The browser runtime raises typed errors with stable codes so payload or
   * renderer contract issues are easier to diagnose from the console.
   */

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

  /**
   * Build the user-visible error panel shown inside exported HTML files.
   */
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

  /**
   * Replace the app shell with a runtime error view.
   */
  function renderRuntimeError(targetApp, message, detail) {
    console.error("[activitysim-export] " + message, detail);
    clearElement(targetApp);
    targetApp.appendChild(
      el("div", { className: "export-shell" }, [
        createErrorPanel(message, detail),
      ])
    );
  }
// END errors.js

// BEGIN debug.js
  /**
   * Debug helpers for the export runtime.
   *
   * These helpers keep optional logging and summary reporting out of the main
   * render path while making runtime behavior easier to inspect from the
   * browser console.
   */

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

  /**
   * Create a small console logger with a fixed export-runtime prefix.
   */
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

  /**
   * Count node kinds recursively for optional debug summaries.
   */
  function countNodeKinds(node, counts) {
    if (!node || typeof node !== "object") {
      return counts;
    }
    counts[node.kind || "unknown"] = (counts[node.kind || "unknown"] || 0) + 1;
    if (node.kind === "container" || node.kind === "card") {
      for (const child of node.children || []) {
        countNodeKinds(child, counts);
      }
      return counts;
    }
    if (node.kind === "tabs") {
      for (const tab of node.tabs || []) {
        countNodeKinds(tab.content, counts);
      }
      return counts;
    }
    if (node.kind === "region") {
      countNodeKinds(node.default_content, counts);
      for (const variantNode of Object.values(node.variants || {})) {
        countNodeKinds(variantNode, counts);
      }
      return counts;
    }
    return counts;
  }

  /**
   * Log a summary of the payload currently loaded into the browser runtime.
   */
  function logRuntimeSummary(runtimeLogger, candidate) {
    if (!runtimeLogger || !runtimeLogger.enabled) {
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
    for (const stateId of stateKeys) {
      for (const pageNode of Object.values(candidate.states[stateId] || {})) {
        if (pageNode && pageNode.kind === "page") {
          countNodeKinds(pageNode.content, nodeCounts);
        }
      }
    }
    runtimeLogger.debug("Runtime summary", {
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
  /**
   * Payload parsing and validation helpers.
   *
   * The runtime still trusts Python to build the payload, but we validate the
   * most important cross-field references here so contract drift fails fast
   * with targeted runtime errors instead of confusing partial renders.
   */

  function parsePayload() {
    if (!dataElement) {
      fail("Export payload script element was not found.", null, "PAYLOAD_ELEMENT_MISSING");
    }
    try {
      return JSON.parse(dataElement.textContent || "");
    } catch (error) {
      fail(
        "Export payload JSON could not be parsed.",
        error && error.message ? error.message : error,
        "PAYLOAD_PARSE_FAILED"
      );
    }
  }

  function collectLeafPages(pageDescriptors, leafPages) {
    for (const pageDescriptor of pageDescriptors || []) {
      if (hasChildren(pageDescriptor)) {
        collectLeafPages(pageDescriptor.children || [], leafPages);
      } else {
        leafPages.push(pageDescriptor);
      }
    }
    return leafPages;
  }

  function collectPageDescriptors(pageDescriptors, allPages) {
    for (const pageDescriptor of pageDescriptors || []) {
      allPages.push(pageDescriptor);
      if (hasChildren(pageDescriptor)) {
        collectPageDescriptors(pageDescriptor.children || [], allPages);
      }
    }
    return allPages;
  }

  function collectRegionsForValidation(node, regions) {
    if (!node || typeof node !== "object") {
      return regions;
    }
    if (node.kind === "region") {
      regions.push(node);
      collectRegionsForValidation(node.default_content, regions);
      for (const variantNode of Object.values(node.variants || {})) {
        collectRegionsForValidation(variantNode, regions);
      }
      return regions;
    }
    if (node.kind === "container" || node.kind === "card") {
      for (const child of node.children || []) {
        collectRegionsForValidation(child, regions);
      }
      return regions;
    }
    if (node.kind === "tabs") {
      for (const tab of node.tabs || []) {
        collectRegionsForValidation(tab.content, regions);
      }
    }
    return regions;
  }

  function validateUniquePageIds(candidate) {
    const pages = collectPageDescriptors(candidate.pages || [], []);
    const seenPageIds = {};
    for (const pageDescriptor of pages) {
      if (seenPageIds[pageDescriptor.id]) {
        fail(
          "Export payload contains duplicate page id " + pageDescriptor.id + ".",
          null,
          "DUPLICATE_PAGE_ID"
        );
      }
      seenPageIds[pageDescriptor.id] = true;
    }
  }

  function validateDefaultState(candidate) {
    const stateKey = buildDashboardStateKey(candidate.default_state);
    if (!candidate.states[stateKey]) {
      fail(
        "Export payload is missing state data for its default dashboard state " + stateKey + ".",
        null,
        "MISSING_DEFAULT_STATE_ENTRY"
      );
    }
    if (
      (candidate.dashboard_controls.weighting || []).indexOf(candidate.default_state.weighting) === -1
      || (candidate.dashboard_controls.values || []).indexOf(candidate.default_state.values) === -1
    ) {
      fail(
        "Export payload default dashboard state does not match the available dashboard controls.",
        null,
        "INVALID_DEFAULT_DASHBOARD_STATE"
      );
    }
  }

  function validatePageDescriptors(candidate) {
    for (const pageDescriptor of collectPageDescriptors(candidate.pages || [], [])) {
      if (hasChildren(pageDescriptor)) {
        const childIds = (pageDescriptor.children || []).map((childPage) => childPage.id);
        if (!pageDescriptor.default_page_id || childIds.indexOf(pageDescriptor.default_page_id) === -1) {
          fail(
            "Grouped export page " + pageDescriptor.id + " has an invalid default_page_id.",
            null,
            "INVALID_DEFAULT_PAGE_REFERENCE"
          );
        }
      }
      for (const selector of pageDescriptor.selectors || []) {
        if (
          selector.default_value !== undefined
          && selector.default_value !== null
          && (selector.options || []).indexOf(selector.default_value) === -1
        ) {
          fail(
            "Selector " + selector.id + " on page " + pageDescriptor.id + " has a default_value that is not in options.",
            null,
            "INVALID_SELECTOR_DEFAULT"
          );
        }
      }
    }
  }

  function validateStates(candidate) {
    const leafPages = collectLeafPages(candidate.pages || [], []);
    const leafPageIds = {};
    for (const leafPage of leafPages) {
      leafPageIds[leafPage.id] = leafPage;
    }

    for (const [stateId, pagesForState] of Object.entries(candidate.states || {})) {
      for (const leafPage of leafPages) {
        const pageNode = pagesForState[leafPage.id];
        if (!pageNode) {
          fail(
            "State " + stateId + " is missing page content for leaf page " + leafPage.id + ".",
            null,
            "MISSING_STATE_PAGE"
          );
        }
        if (!pageNode || pageNode.kind !== "page") {
          fail(
            "State " + stateId + " contains invalid page content for leaf page " + leafPage.id + ".",
            null,
            "INVALID_STATE_PAGE"
          );
        }
        const selectorIds = {};
        for (const selector of leafPage.selectors || []) {
          selectorIds[selector.id] = true;
        }
        const seenRegionIds = {};
        for (const regionNode of collectRegionsForValidation(pageNode.content, [])) {
          if (!regionNode.region_id) {
            fail(
              "Leaf page " + leafPage.id + " contains a region without region_id.",
              null,
              "MISSING_REGION_ID"
            );
          }
          if (seenRegionIds[regionNode.region_id]) {
            fail(
              "Leaf page " + leafPage.id + " contains duplicate region id " + regionNode.region_id + ".",
              null,
              "DUPLICATE_REGION_ID"
            );
          }
          seenRegionIds[regionNode.region_id] = true;
          for (const selectorId of regionNode.selector_ids || []) {
            if (!selectorIds[selectorId]) {
              fail(
                "Region " + regionNode.region_id + " on page " + leafPage.id + " references unknown selector " + selectorId + ".",
                null,
                "UNKNOWN_REGION_SELECTOR"
              );
            }
          }
        }
      }

      for (const pageId of Object.keys(pagesForState || {})) {
        if (!leafPageIds[pageId]) {
          fail(
            "State " + stateId + " references unknown page id " + pageId + ".",
            null,
            "UNKNOWN_STATE_PAGE"
          );
        }
      }
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
    validateUniquePageIds(candidate);
    validateDefaultState(candidate);
    validatePageDescriptors(candidate);
    validateStates(candidate);
  }
// END schema.js

// BEGIN state.js
  /**
   * State helpers for the export runtime.
   *
   * These helpers are intentionally pure where possible so the runtime reads
   * more like Python data transformation code than browser-oriented state
   * mutation.
   */

  function buildDashboardStateKey(currentState) {
    return currentState.weighting + "||" + currentState.values;
  }

  function findPageById(pageDescriptors, pageId) {
    for (const page of pageDescriptors || []) {
      if (page.id === pageId) {
        return page;
      }
    }
    return null;
  }

  function hasChildren(pageDescriptor) {
    return !!(pageDescriptor && pageDescriptor.children && pageDescriptor.children.length);
  }

  /**
   * Resolve the leaf child page for a grouped page without mutating state.
   */
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

  function getActivePageDescriptor(currentPayload, currentState) {
    if (!currentState.activePage) {
      return null;
    }
    return findPageById(currentPayload.pages || [], currentState.activePage);
  }

  function getLeafPageId(currentPayload, currentState) {
    const pageDescriptor = getActivePageDescriptor(currentPayload, currentState);
    if (!pageDescriptor) {
      return null;
    }
    if (hasChildren(pageDescriptor)) {
      return resolveActiveChildPageIdForState(pageDescriptor, currentState);
    }
    return pageDescriptor.id;
  }

  function getPagesForCurrentState(currentPayload, currentState) {
    return currentPayload.states[buildDashboardStateKey(currentState)] || null;
  }

  function getPageSelectorState(currentState, leafPageId) {
    return currentState.pageSelectors[leafPageId] || {};
  }

  function cloneState(currentState) {
    return {
      weighting: currentState.weighting,
      values: currentState.values,
      activePage: currentState.activePage,
      activeChildPage: Object.assign({}, currentState.activeChildPage),
      pageSelectors: Object.assign({}, currentState.pageSelectors),
    };
  }

  function registerLeafPageSelectorDefaults(initialState, pageDescriptor) {
    const selectorState = {};
    for (const selector of pageDescriptor.selectors || []) {
      if (selector.export_enabled) {
        selectorState[selector.id] = selector.default_value;
      }
    }
    initialState.pageSelectors[pageDescriptor.id] = selectorState;
  }

  /**
   * Normalize state in one explicit place.
   *
   * This is where default page/child-page fallbacks are applied so "read"
   * helpers elsewhere can remain side-effect free.
   */
  function normalizeState(currentPayload, currentState) {
    const nextState = cloneState(currentState);
    const rootPages = currentPayload.pages || [];
    if (!nextState.activePage) {
      nextState.activePage = rootPages.length ? rootPages[0].id : null;
    }

    for (const pageDescriptor of rootPages) {
      if (hasChildren(pageDescriptor)) {
        const activeChildId = resolveActiveChildPageIdForState(pageDescriptor, nextState);
        if (!activeChildId) {
          fail(
            "Grouped export page " + pageDescriptor.id + " is missing child pages.",
            null,
            "MISSING_CHILD_PAGES"
          );
        }
        nextState.activeChildPage[pageDescriptor.id] = activeChildId;
      }
    }
    return nextState;
  }

  function getInitialState(candidate) {
    const initialState = {
      weighting: candidate.default_state.weighting,
      values: candidate.default_state.values,
      activePage: candidate.pages.length ? candidate.pages[0].id : null,
      activeChildPage: {},
      pageSelectors: {},
    };

    for (const pageDescriptor of candidate.pages || []) {
      if (hasChildren(pageDescriptor)) {
        for (const childPage of pageDescriptor.children || []) {
          registerLeafPageSelectorDefaults(initialState, childPage);
        }
      } else {
        registerLeafPageSelectorDefaults(initialState, pageDescriptor);
      }
    }

    return normalizeState(candidate, initialState);
  }

  function updateDashboardControlState(currentPayload, currentState, controlKey, value) {
    const nextState = cloneState(currentState);
    nextState[controlKey] = value;
    return normalizeState(currentPayload, nextState);
  }

  function setActivePageInState(currentPayload, currentState, pageId) {
    const nextState = cloneState(currentState);
    nextState.activePage = pageId;
    return normalizeState(currentPayload, nextState);
  }

  function setActiveChildPageInState(currentPayload, currentState, pageId, childPageId) {
    const nextState = cloneState(currentState);
    nextState.activeChildPage[pageId] = childPageId;
    return normalizeState(currentPayload, nextState);
  }

  function updateSelectorState(currentPayload, currentState, pageId, selectorId, value) {
    const nextState = cloneState(currentState);
    const pageState = Object.assign({}, nextState.pageSelectors[pageId] || {});
    pageState[selectorId] = value;
    nextState.pageSelectors[pageId] = pageState;
    return normalizeState(currentPayload, nextState);
  }
// END state.js

// BEGIN plotly_lifecycle.js
  /**
   * Plotly lifecycle helpers.
   *
   * Plotly needs a small amount of browser-specific coordination when the page
   * first renders or when layout sizes change. Keeping that timing logic here
   * avoids spreading retries, observers, and direct Plotly access through the
   * main renderers.
   */
  const PLOT_RESIZE_RETRY_DELAYS_MS = [60, 180, 320];
  const PLOT_RESIZE_DEBOUNCE_DELAY_MS = 40;

  function createPlotManager(config) {
    const plotly = config.plotly;
    const runtimeLogger = config.logger;
    const onRuntimeError = config.onRuntimeError;
    const plotFigures = new WeakMap();
    const registeredPlots = new Set();
    let resizeObserver = null;
    let resizeDebounceTimer = null;
    let resizeFrameHandle = null;
    let resizeRetryTimers = [];

    function clearScheduledResizeWork() {
      if (resizeDebounceTimer) {
        clearTimeout(resizeDebounceTimer);
        resizeDebounceTimer = null;
      }
      if (resizeFrameHandle !== null) {
        cancelAnimationFrame(resizeFrameHandle);
        resizeFrameHandle = null;
      }
      for (const retryTimer of resizeRetryTimers) {
        clearTimeout(retryTimer);
      }
      resizeRetryTimers = [];
    }

    function getRegisteredPlotTargets() {
      const targets = [];
      for (const container of registeredPlots) {
        if (!document.contains(container)) {
          registeredPlots.delete(container);
          continue;
        }
        const renderedPlot = container.querySelector(".js-plotly-plot");
        targets.push(renderedPlot || container);
      }
      return targets;
    }

    function resizePlots() {
      if (
        !plotly
        || !plotly.Plots
        || typeof plotly.Plots.resize !== "function"
      ) {
        return;
      }
      for (const plot of getRegisteredPlotTargets()) {
        try {
          plotly.Plots.resize(plot);
        } catch (error) {
          runtimeLogger.warn("Plot resize failed", error);
        }
      }
    }

    /**
     * Plot containers often report one layout size on the first frame and a
     * final size shortly after the surrounding flex/grid layout settles. We
     * keep a small, named retry schedule here instead of scattering setTimeout
     * calls through the renderers.
     */
    function scheduleResize() {
      if (
        !plotly
        || !plotly.Plots
        || typeof plotly.Plots.resize !== "function"
      ) {
        return;
      }
      clearScheduledResizeWork();
      resizeFrameHandle = requestAnimationFrame(() => {
        resizeFrameHandle = null;
        resizePlots();
        resizeRetryTimers = PLOT_RESIZE_RETRY_DELAYS_MS.map((delay) => {
          return setTimeout(resizePlots, delay);
        });
      });
    }

    function debouncedScheduleResize() {
      if (resizeDebounceTimer) {
        clearTimeout(resizeDebounceTimer);
      }
      resizeDebounceTimer = setTimeout(scheduleResize, PLOT_RESIZE_DEBOUNCE_DELAY_MS);
    }

    /**
     * Register a plot container and remember the serialized figure associated
     * with it. The WeakMap is the runtime's plot registry for figure payloads.
     */
    function registerPlot(element, figure) {
      plotFigures.set(element, figure);
      registeredPlots.add(element);
    }

    /**
     * Render any plot containers that were added during the latest DOM paint.
     */
    function renderPendingPlots(root) {
      if (!plotly || typeof plotly.react !== "function") {
        fail(
          "Plotly.react is unavailable in the embedded export runtime.",
          null,
          "PLOTLY_UNAVAILABLE"
        );
      }

      const scope = root || document;
      for (const div of scope.querySelectorAll('.plot-shell[data-plot-pending="true"]')) {
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
      }
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
      for (const element of (root || document).querySelectorAll(
        ".page-panel, .container-row, .container-column, .plot-shell"
      )) {
        resizeObserver.observe(element);
      }
    }

    function disconnect() {
      if (resizeObserver) {
        resizeObserver.disconnect();
        resizeObserver = null;
      }
      clearScheduledResizeWork();
    }

    return {
      registerPlot: registerPlot,
      renderPendingPlots: renderPendingPlots,
      scheduleResize: scheduleResize,
      observeLayout: observeLayout,
      disconnect: disconnect,
    };
  }
// END plotly_lifecycle.js

// BEGIN renderers/widgets.js
  /**
   * Widget renderers for export payload nodes.
   */

  function renderWidget(node, context, actions) {
    const wrapper = el("div", { className: "widget-shell" }, [
      el("div", {
        className: "widget-label",
        text: node.name || "",
      }),
    ]);

    if (node.widget_type === "select") {
      const select = document.createElement("select");
      select.disabled = !!node.disabled;
      for (const option of node.options || []) {
        const opt = document.createElement("option");
        opt.value = option;
        opt.textContent = option;
        if (option === node.value) {
          opt.selected = true;
        }
        select.appendChild(opt);
      }
      if (node.export_enabled && node.selector_id) {
        select.addEventListener("change", () => {
          actions.setPageSelector(node.selector_id, select.value, {
            preferPartialRegionUpdate: true,
          });
        });
      }
      wrapper.appendChild(select);
      return wrapper;
    }

    if (node.widget_type === "radio_button_group") {
      wrapper.appendChild(
        el("div", { className: "widget-radio-options" }, (node.options || []).map((option) => {
          return makeButton({
            label: option,
            active: option === node.value,
            disabled: !!node.disabled,
            onClick: () => {
              if (node.export_enabled && node.selector_id) {
                actions.setPageSelector(node.selector_id, option);
              }
            },
            className: "widget-radio-option",
          });
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
  /**
   * Table renderer for serialized tabular export nodes.
   */
  function renderTable(node) {
    const table = el("table", { className: "export-table" });
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const column of node.columns || []) {
      headRow.appendChild(el("th", { text: column }));
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const row of node.rows || []) {
      const tr = document.createElement("tr");
      for (const column of node.columns || []) {
        const value = row[column];
        tr.appendChild(
          el("td", {
            text: value == null ? "" : String(value),
          })
        );
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);

    return el("div", { className: "table-wrap" }, [table]);
  }
// END renderers/tables.js

// BEGIN renderers/tabs.js
  /**
   * Local tab renderer used inside exported pages.
   */
  function renderTabs(node, context, actions, leafPageId) {
    const root = document.createElement("div");
    let activeIndex = 0;
    const tabRow = el("div", { className: "local-tab-row" });
    const panel = el("div", { className: "local-tab-panel" });

    function paint() {
      clearElement(tabRow);
      clearElement(panel);
      for (const [index, tab] of (node.tabs || []).entries()) {
        tabRow.appendChild(
          makeButton({
            label: tab.title,
            active: index === activeIndex,
            onClick: () => {
              activeIndex = index;
              paint();
            },
            className: "local-tab-button",
          })
        );
      }
      if (node.tabs && node.tabs[activeIndex]) {
        panel.appendChild(renderNode(node.tabs[activeIndex].content, context, actions, leafPageId));
      }
      requestAnimationFrame(() => {
        context.plotManager.renderPendingPlots(panel);
        context.plotManager.scheduleResize();
      });
    }

    paint();
    root.appendChild(tabRow);
    root.appendChild(panel);
    return root;
  }
// END renderers/tabs.js

// BEGIN renderers/plots.js
  /**
   * Plot renderer that registers serialized Plotly figures with the plot
   * lifecycle manager for later browser-side rendering.
   */
  function renderPlot(node, context) {
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
    context.plotManager.registerPlot(plotElement, figure);
    return plotElement;
  }
// END renderers/plots.js

// BEGIN renderers/regions.js
  /**
   * Region helpers and renderers.
   *
   * Regions are the runtime's selector-driven swap points. The JavaScript
   * lookup key must match the Python serializer exactly: selector values are
   * ordered by `node.selector_ids` and then serialized with JSON.stringify.
   */

  function buildRenderedRegionKey(leafPageId, regionId) {
    return String(leafPageId || "") + "::" + String(regionId || "");
  }

  function clearRenderedRegionRegistry(context) {
    context.renderedRegions = {};
  }

  function registerRenderedRegion(context, leafPageId, regionNode, wrapper) {
    const regionId = regionNode.region_id;
    if (!regionId) {
      fail(
        "Region nodes must include a region_id for runtime updates.",
        null,
        "MISSING_REGION_ID"
      );
    }
    const regionKey = buildRenderedRegionKey(leafPageId, regionId);
    if (context.renderedRegions[regionKey]) {
      fail(
        "Duplicate rendered region encountered for page " + leafPageId + " and region " + regionId + ".",
        null,
        "DUPLICATE_RENDERED_REGION"
      );
    }
    context.renderedRegions[regionKey] = wrapper;
  }

  function buildRegionVariantKey(selectorValues) {
    return JSON.stringify(selectorValues);
  }

  function getRegionSelectorValues(node, context, leafPageId) {
    const pageSelectorState = getPageSelectorState(context.state, leafPageId);
    return (node.selector_ids || []).map((selectorId) => {
      return pageSelectorState[selectorId];
    });
  }

  function resolveRegionContent(node, context, leafPageId) {
    const selectorValues = getRegionSelectorValues(node, context, leafPageId);
    const variantLookupKey = buildRegionVariantKey(selectorValues);
    if (node.variants && Object.prototype.hasOwnProperty.call(node.variants, variantLookupKey)) {
      return node.variants[variantLookupKey];
    }
    // Falling back to default_content is expected when Python intentionally
    // emitted a default snapshot for unmatched selector combinations. If that
    // was not intended, this usually indicates payload/schema drift.
    return node.default_content;
  }

  function renderRegion(node, context, actions, leafPageId) {
    const wrapper = el("div", {
      className: "export-region",
      attrs: {
        "data-region-id": node.region_id || "",
        "data-leaf-page-id": leafPageId || "",
        "data-selector-ids": JSON.stringify(node.selector_ids || []),
      },
    });
    registerRenderedRegion(context, leafPageId, node, wrapper);
    wrapper.appendChild(renderNode(resolveRegionContent(node, context, leafPageId), context, actions, leafPageId));
    return wrapper;
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
      for (const child of node.children || []) {
        collectRegionNodes(child, regions);
      }
      return regions;
    }
    if (node.kind === "tabs") {
      for (const tab of node.tabs || []) {
        collectRegionNodes(tab.content, regions);
      }
      return regions;
    }
    return regions;
  }

  function updateRenderedRegions(context, actions, leafPageId, changedSelectorId) {
    const pagesForState = getPagesForCurrentState(context.payload, context.state);
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
    for (const regionNode of regionNodes) {
      const wrapper = context.renderedRegions[
        buildRenderedRegionKey(leafPageId, regionNode.region_id)
      ];
      if (!wrapper) {
        return false;
      }
      clearElement(wrapper);
      wrapper.appendChild(
        renderNode(resolveRegionContent(regionNode, context, leafPageId), context, actions, leafPageId)
      );
      context.plotManager.renderPendingPlots(wrapper);
    }
    context.plotManager.scheduleResize();
    return true;
  }
// END renderers/regions.js

// BEGIN renderers/nodes.js
  /**
   * Node-level renderer registry.
   *
   * Each payload node kind maps to one small renderer so new node types have a
   * predictable place to live.
   */

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

  function renderContainer(node, context, actions, leafPageId) {
    const layoutClass = node.layout === "row" ? "container-row" : "container-column";
    const childCount = Number(node.child_count || (node.children || []).length || 0);
    const container = el("div", {
      className: layoutClass + " child-count-" + String(childCount),
    });
    for (const child of node.children || []) {
      const wrapper = el("div", {
        className: "container-item container-item--" + nodeRole(child),
      }, [
        renderNode(child, context, actions, leafPageId),
      ]);
      container.appendChild(wrapper);
    }
    return container;
  }

  function renderCard(node, context, actions, leafPageId) {
    const card = el("div", { className: "card" });
    if (node.title) {
      card.appendChild(el("div", { className: "card-title", text: node.title }));
    }
    for (const child of node.children || []) {
      card.appendChild(renderNode(child, context, actions, leafPageId));
    }
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

  function renderNode(node, context, actions, leafPageId) {
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
    return renderer(node, context, actions, leafPageId);
  }
// END renderers/nodes.js

// BEGIN renderers/app.js
  /**
   * Top-level app renderers.
   *
   * The app renderer translates payload pages, dashboard controls, and runtime
   * state into the final offline HTML shell shown in the browser.
   */

  function renderControlGroup(context, actions, config, isFirstGroup) {
    const group = el("div", {
      className: "control-group",
      style: {
        marginTop: isFirstGroup ? "12px" : "16px",
      },
    });
    group.appendChild(
      el("div", {
        className: "control-group-title",
        text: config.label,
      })
    );

    const chips = el("div", { className: "control-row" });
    for (const option of config.options || []) {
      chips.appendChild(
        makeButton({
          label: option,
          active: context.state[config.stateKey] === option,
          disabled: !config.enabled,
          onClick: () => {
            config.onSelect(option);
          },
          className: "toggle-chip",
        })
      );
    }
    group.appendChild(chips);
    return group;
  }

  function renderControls(context, actions) {
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

    const controlConfigs = [
      {
        label: "Weighting",
        options: context.payload.dashboard_controls.weighting,
        stateKey: "weighting",
        enabled: !!(
          context.payload.chrome
          && context.payload.chrome.controls_enabled
          && context.payload.chrome.controls_enabled.weighting
        ),
        onSelect: actions.setWeighting,
      },
      {
        label: "Values",
        options: context.payload.dashboard_controls.values,
        stateKey: "values",
        enabled: !!(
          context.payload.chrome
          && context.payload.chrome.controls_enabled
          && context.payload.chrome.controls_enabled.values
        ),
        onSelect: actions.setValues,
      },
    ];

    for (const [index, config] of controlConfigs.entries()) {
      shell.appendChild(renderControlGroup(context, actions, config, index === 0));
    }

    return shell;
  }

  function renderRunLegendItem(run) {
    const runColor = run.color || "#94a3b8";
    return el("div", {
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
  }

  function renderRunsLoaded(context) {
    const shell = el("div", { className: "rail-card" }, [
      el("h2", {
        className: "rail-section-title",
        text: "Runs Loaded",
      }),
    ]);
    const list = el("div", { className: "run-legend-list" });
    const runs = context.payload.runs_loaded || [];
    if (!runs.length) {
      list.appendChild(
        el("p", {
          className: "run-legend-empty",
          text: "No runs loaded.",
        })
      );
    } else {
      for (const run of runs) {
        list.appendChild(renderRunLegendItem(run));
      }
    }
    shell.appendChild(list);
    return shell;
  }

  function renderRailSection(context, actions, section, index) {
    if (section === "runs_loaded") {
      return [renderRunsLoaded(context)];
    }
    if (section === "display_options") {
      return [
        index > 0 ? el("div", { className: "rail-divider" }) : null,
        renderControls(context, actions),
      ];
    }
    fail(
      "Unknown rail section encountered in export payload:",
      section,
      "UNKNOWN_RAIL_SECTION"
    );
  }

  function renderRail(context, actions) {
    const rail = el("aside", { className: "export-rail" });
    const sections = (context.payload.chrome && context.payload.chrome.rail_sections) || [];
    for (const [index, section] of sections.entries()) {
      appendChildren(rail, renderRailSection(context, actions, section, index));
    }
    return rail;
  }

  function renderPageTabs(context, actions) {
    return el("div", { className: "page-tab-row" }, (context.payload.pages || []).map((page) => {
      return makeButton({
        label: page.title,
        active: page.id === context.state.activePage,
        onClick: () => {
          actions.setActivePage(page.id);
        },
        className: "page-tab-button",
      });
    }));
  }

  function renderChildPageTabs(context, actions, pageDescriptor) {
    const activeChildId = resolveActiveChildPageIdForState(pageDescriptor, context.state);
    return el("div", { className: "local-tab-row" }, (pageDescriptor.children || []).map((childPage) => {
      return makeButton({
        label: childPage.title,
        active: childPage.id === activeChildId,
        onClick: () => {
          actions.setActiveChildPage(pageDescriptor.id, childPage.id);
        },
        className: "local-tab-button",
      });
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

  function resolveActivePageNode(context) {
    const pagesForState = getPagesForCurrentState(context.payload, context.state);
    if (!pagesForState) {
      fail(
        "Missing page state for dashboard combination " + buildDashboardStateKey(context.state) + ".",
        null,
        "MISSING_PAGE_STATE"
      );
    }
    const pageDescriptor = getActivePageDescriptor(context.payload, context.state);
    if (!pageDescriptor) {
      fail(
        "Missing page descriptor for active page " + context.state.activePage + ".",
        null,
        "MISSING_PAGE_DESCRIPTOR"
      );
    }

    const leafPageId = getLeafPageId(context.payload, context.state);
    if (!leafPageId) {
      fail(
        "Missing leaf page selection for active page " + pageDescriptor.id + ".",
        null,
        "MISSING_PAGE_STATE"
      );
    }

    return {
      pageDescriptor: pageDescriptor,
      leafPageId: leafPageId,
      pageNode: pagesForState[leafPageId],
    };
  }

  function renderPagePanel(context, actions) {
    const panel = el("div", { className: "page-panel" });
    const resolvedPage = resolveActivePageNode(context);
    const pageDescriptor = resolvedPage.pageDescriptor;
    let leafPageId = resolvedPage.leafPageId;

    if (hasChildren(pageDescriptor)) {
      panel.appendChild(renderChildPageTabs(context, actions, pageDescriptor));
    }

    panel.appendChild(
      renderNode(resolvePageContent(resolvedPage.pageNode), context, actions, leafPageId)
    );
    return panel;
  }

  function renderShell(context, actions) {
    const headerChildren = [
      el("h1", { text: context.payload.title }),
    ];
    if (context.payload.client_export_note && String(context.payload.client_export_note).trim()) {
      headerChildren.push(
        el("p", {
          className: "export-note",
          text: context.payload.client_export_note,
        })
      );
    }

    const main = el("main", { className: "export-main" }, [
      renderPageTabs(context, actions),
      renderPagePanel(context, actions),
    ]);

    return el("div", { className: "export-shell" }, [
      el("div", { className: "export-header" }, headerChildren),
      el("div", { className: "export-layout" }, [
        renderRail(context, actions),
        main,
      ]),
    ]);
  }

  function renderApp(context, actions) {
    try {
      context.state = normalizeState(context.payload, context.state);
      clearRenderedRegionRegistry(context);
      clearElement(context.app);
      context.app.appendChild(renderShell(context, actions));
      context.plotManager.renderPendingPlots(context.app);
      context.plotManager.observeLayout(context.app);
      context.plotManager.scheduleResize();
    } catch (error) {
      renderRuntimeError(
        context.app,
        "This HTML export encountered a runtime rendering error.",
        error && error.message ? error.message : error
      );
    }
  }
// END renderers/app.js

// BEGIN index.js
  /**
   * Runtime bootstrap.
   *
   * This is the only place that wires concrete browser dependencies into the
   * runtime context and actions.
   */

  function createRuntimeContext(config) {
    return {
      payload: config.payload,
      state: config.state,
      logger: config.logger,
      plotManager: config.plotManager,
      app: config.app,
      renderedRegions: {},
    };
  }

  function createRuntimeActions(context) {
    return {
      setWeighting: function (value) {
        context.state = updateDashboardControlState(context.payload, context.state, "weighting", value);
        renderApp(context, runtimeActions);
      },
      setValues: function (value) {
        context.state = updateDashboardControlState(context.payload, context.state, "values", value);
        renderApp(context, runtimeActions);
      },
      setActivePage: function (pageId) {
        context.state = setActivePageInState(context.payload, context.state, pageId);
        renderApp(context, runtimeActions);
      },
      setActiveChildPage: function (pageId, childPageId) {
        context.state = setActiveChildPageInState(context.payload, context.state, pageId, childPageId);
        renderApp(context, runtimeActions);
      },
      setPageSelector: function (selectorId, value, options) {
        const leafPageId = getLeafPageId(context.payload, context.state);
        if (!leafPageId) {
          fail(
            "Cannot update a page selector because no active page is selected.",
            null,
            "MISSING_PAGE_STATE"
          );
        }
        context.state = updateSelectorState(context.payload, context.state, leafPageId, selectorId, value);
        // A partial region update is safe when the triggering control already
        // updated its own DOM state (for example, a native <select>). We fall
        // back to a full render for controls like radio-button groups that need
        // the renderer to repaint active styling.
        if (
          options
          && options.preferPartialRegionUpdate
          && updateRenderedRegions(context, runtimeActions, leafPageId, selectorId)
        ) {
          return;
        }
        renderApp(context, runtimeActions);
      },
    };
  }

  let payload = null;
  let logger = null;

  try {
    payload = parsePayload();
    validatePayloadSchema(payload);
    logger = createLogger(shouldEnableDebugLogging(payload));
    logRuntimeSummary(logger, payload);
  } catch (error) {
    renderRuntimeError(
      app,
      "This HTML export is not compatible with the embedded client runtime.",
      error && error.message ? error.message : error
    );
    return;
  }

  const plotManager = createPlotManager({
    plotly: typeof Plotly === "undefined" ? null : Plotly,
    logger: logger,
    onRuntimeError: function (message, detail) {
      renderRuntimeError(app, message, detail);
    },
  });
  const runtimeContext = createRuntimeContext({
    payload: payload,
    state: getInitialState(payload),
    logger: logger,
    plotManager: plotManager,
    app: app,
  });
  const runtimeActions = createRuntimeActions(runtimeContext);

  window.addEventListener("resize", () => {
    runtimeContext.plotManager.scheduleResize();
  });

  renderApp(runtimeContext, runtimeActions);
})();
// END index.js
