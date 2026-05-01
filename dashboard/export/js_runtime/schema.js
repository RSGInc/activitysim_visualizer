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
