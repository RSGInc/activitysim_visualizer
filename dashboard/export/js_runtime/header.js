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
