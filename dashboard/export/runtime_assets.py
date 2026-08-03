"""Embedded runtime asset loaders for offline HTML export."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dashboard.export.types import EXPORT_SCHEMA_VERSION

ASSET_DIR = Path(__file__).with_name("assets")
EXPORT_CSS_PATH = ASSET_DIR / "export.css"
EXPORT_RUNTIME_JS_PATH = ASSET_DIR / "export_runtime.js"


@lru_cache(maxsize=1)
def load_export_css() -> str:
    """Load the export stylesheet source from disk."""

    return EXPORT_CSS_PATH.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def load_export_runtime_js() -> str:
    """Load and parameterize the export runtime source from disk."""

    return (
        EXPORT_RUNTIME_JS_PATH.read_text(encoding="utf-8")
        .replace("__EXPORT_SCHEMA_VERSION__", EXPORT_SCHEMA_VERSION)
        .strip()
    )


def build_export_html_shell_parts(*, title: str, plotly_js: str) -> tuple[str, str]:
    """Build the shell surrounding the export payload JSON."""

    export_css = load_export_css()
    runtime_js = load_export_runtime_js()
    prefix = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
{export_css}
  </style>
  <script>
{plotly_js}
  </script>
</head>
<body>
  <div id="app"></div>
  <script id="activitysim-export-data" type="application/json">"""
    suffix = f"""</script>
  <script>
{runtime_js}
  </script>
</body>
</html>
"""
    return prefix, suffix


def build_export_html_shell(*, title: str, payload_json: str, plotly_js: str) -> str:
    """Assemble the final self-contained HTML document."""

    prefix, suffix = build_export_html_shell_parts(title=title, plotly_js=plotly_js)
    return f"{prefix}{payload_json}{suffix}"
