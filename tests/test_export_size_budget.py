from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# This baseline tracks the current representative export fixture on this branch.
# The runtime split added source files, but the generated runtime asset remains
# small; the larger size drift comes from the repository's current export
# payload/embedded dependency footprint rather than from a major new runtime
# bundle.
# Updated after declarative page features expanded the representative full export.
# Keep the growth allowance separate so future changes still surface clearly.
EXPORT_HTML_BASELINE_BYTES = 10_325_291
EXPORT_HTML_GROWTH_BUDGET_BYTES = 350_000

@pytest.mark.full_export
def test_export_html_size_budget_for_representative_fixture(
    representative_full_export_html: str,
) -> None:
    html = representative_full_export_html
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
