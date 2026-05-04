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
