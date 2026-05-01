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
