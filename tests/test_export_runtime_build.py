from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.export.build_export_runtime import OUTPUT_PATH, build_runtime_source


def test_build_export_runtime_script_reproduces_committed_runtime_asset() -> None:
    generated = build_runtime_source()
    committed = OUTPUT_PATH.read_text(encoding="utf-8")

    assert committed == generated
    assert "// BEGIN renderers/nodes.js" in committed
    assert "// BEGIN plotly_lifecycle.js" in committed
