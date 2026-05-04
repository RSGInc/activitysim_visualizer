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
