from __future__ import annotations

import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.abspath(sys.path[0]) == SCRIPT_DIR:
    sys.path.pop(0)

from pathlib import Path


EXPORT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = EXPORT_ROOT / "js_runtime"
OUTPUT_PATH = EXPORT_ROOT / "assets" / "export_runtime.js"

SOURCE_FILES = [
    "header.js",
    "dom.js",
    "errors.js",
    "debug.js",
    "schema.js",
    "state.js",
    "plotly_lifecycle.js",
    "renderers/widgets.js",
    "renderers/tables.js",
    "renderers/tabs.js",
    "renderers/plots.js",
    "renderers/regions.js",
    "renderers/nodes.js",
    "renderers/app.js",
    "index.js",
]


def build_runtime_source() -> str:
    parts = [
        "// Generated from dashboard/export/js_runtime by dashboard/export/build_export_runtime.py",
    ]
    for relative_path in SOURCE_FILES:
        source_path = SOURCE_ROOT / relative_path
        parts.append(f"// BEGIN {relative_path}")
        parts.append(source_path.read_text(encoding="utf-8").rstrip())
        parts.append(f"// END {relative_path}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    OUTPUT_PATH.write_text(build_runtime_source(), encoding="utf-8")


if __name__ == "__main__":
    main()
