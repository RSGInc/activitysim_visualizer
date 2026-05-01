(function () {
  const SUPPORTED_SCHEMA_VERSION = "__EXPORT_SCHEMA_VERSION__";
  const dataElement = document.getElementById("activitysim-export-data");
  const app = document.getElementById("app");

  let payload = null;
  let state = null;
  let logger = null;
  let plotManager = null;
