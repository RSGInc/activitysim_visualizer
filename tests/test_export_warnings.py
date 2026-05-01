from __future__ import annotations

from pathlib import Path
import logging
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from dashboard.export.html import build_export_html_document
from test_export_html import _extract_payload, _full_summary_run, _write_config


def _workspace_tmp_dir(label: str) -> Path:
    path = Path("tmp_export_test_artifacts") / f"{label}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_export_logs_selector_unavailable_warning_once_and_falls_back(caplog: pytest.LogCaptureFixture) -> None:
    tmp_path = _workspace_tmp_dir("warning_unavailable")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  long_term_choices:",
            "    shadow_pricing:",
            "      student_type: all",
            "      parts:",
            "        school_plot:",
            "          enabled: false",
            "        school_table:",
            "          enabled: false",
        ],
    )

    with caplog.at_level(logging.WARNING, logger="dashboard.export"):
        html = build_export_html_document([], config, summary_runs=[_full_summary_run()])

    payload = _extract_payload(html)
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if "visualizer.export_html.pages.long_term_choices.shadow_pricing.student_type"
        in record.getMessage()
    ]

    assert payload["states"]["Weighted||Percent"]["shadow_pricing"]["kind"] == "page"
    assert warning_messages == [
        "Warning: visualizer.export_html.pages.long_term_choices.shadow_pricing.student_type is configured, but no enabled export part uses this selector. Ignoring the configuration."
    ]


def test_export_raises_readable_error_for_invalid_selector_values() -> None:
    tmp_path = _workspace_tmp_dir("warning_invalid_selector")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose:",
            "      - all",
            "      - invalid-purpose",
        ],
    )

    with pytest.raises(
        ValueError,
        match="Unsupported visualizer.export_html.pages.trip_summaries.trip_mode.tour_purpose values: 'invalid-purpose'",
    ):
        build_export_html_document([], config, summary_runs=[_full_summary_run()])


def test_export_rejects_unknown_page_and_selector_configuration_entries() -> None:
    tmp_path = _workspace_tmp_dir("warning_unknown_entries")
    bad_page_config = _write_config(
        tmp_path / "bad_page",
        export_html_lines=[
            "pages:",
            "  unknown_page:",
            "    purpose: all",
        ],
    )
    bad_selector_config = _write_config(
        tmp_path / "bad_selector",
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      unknown_selector: all",
        ],
    )

    with pytest.raises(
        ValueError, match="Unsupported visualizer.export_html.pages entries"
    ):
        build_export_html_document([], bad_page_config, summary_runs=[_full_summary_run()])

    with pytest.raises(
        ValueError,
        match="Unsupported visualizer.export_html.pages.trip_summaries.trip_mode entries",
    ):
        build_export_html_document(
            [],
            bad_selector_config,
            summary_runs=[_full_summary_run()],
        )
