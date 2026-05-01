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
