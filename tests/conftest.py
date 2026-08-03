from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def representative_full_export_html(
    tmp_path_factory: pytest.TempPathFactory,
) -> str:
    """Build the immutable all-page export once for cross-cutting assertions."""
    from dashboard.export.html import build_export_html_document
    from test_export_html import _full_summary_run, _write_config

    path = tmp_path_factory.mktemp("full_export")
    config = _write_config(
        path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )
    return build_export_html_document(
        [],
        config,
        summary_runs=[_full_summary_run()],
    )
