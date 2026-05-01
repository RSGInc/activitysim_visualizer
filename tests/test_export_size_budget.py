from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.export.html import build_export_html_document
from test_export_html import _full_summary_run, _write_config

# This baseline tracks the current representative export fixture on this branch.
# The runtime split added source files, but the generated runtime asset remains
# small; the larger size drift comes from the repository's current export
# payload/embedded dependency footprint rather than from a major new runtime
# bundle.
EXPORT_HTML_BASELINE_BYTES = 8_833_840
EXPORT_HTML_GROWTH_BUDGET_BYTES = 350_000


def _workspace_tmp_dir(label: str) -> Path:
    path = Path("tmp_export_test_artifacts") / f"{label}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_export_html_size_budget_for_representative_fixture() -> None:
    tmp_path = _workspace_tmp_dir("size_budget")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    actual_size = len(html.encode("utf-8"))
    max_size = EXPORT_HTML_BASELINE_BYTES + EXPORT_HTML_GROWTH_BUDGET_BYTES

    assert (
        actual_size <= max_size
    ), (
        "Representative export HTML grew beyond the agreed budget: "
        f"baseline={EXPORT_HTML_BASELINE_BYTES}B, "
        f"budget={EXPORT_HTML_GROWTH_BUDGET_BYTES}B, "
        f"actual={actual_size}B, "
        f"delta={actual_size - EXPORT_HTML_BASELINE_BYTES}B."
    )
