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
