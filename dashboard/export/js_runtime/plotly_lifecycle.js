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
