from __future__ import annotations

import json
from pathlib import Path
import logging
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

import dashboard.export.payload as export_payload
from dashboard.export.html import build_export_html_document, write_export_html_document
from dashboard.export.payload import analyze_export_payload_size
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

    with caplog.at_level(logging.WARNING, logger="activitysim_viz.dashboard.export"):
        html = build_export_html_document([], config, summary_runs=[_full_summary_run()])

    payload = _extract_payload(html)
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if "visualizer.export_html.pages.long_term_choices.children.shadow_pricing.student_type"
        in record.getMessage()
    ]

    assert payload["states"]["Weighted||Percent"]["shadow_pricing"]["kind"] == "page"
    assert warning_messages == [
        "Warning: visualizer.export_html.pages.long_term_choices.children.shadow_pricing.student_type is configured, but no enabled export part uses this selector. Ignoring the configuration."
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
        match="Unsupported visualizer.export_html.pages.trip_summaries.children.trip_mode.tour_purpose values: 'invalid-purpose'",
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


def test_export_logs_total_payload_warning_for_large_default_export(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = _workspace_tmp_dir("warning_total_payload")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_WARNING_BYTES", 1_000)
    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_STRONG_WARNING_BYTES", 2_000)

    with caplog.at_level(logging.WARNING, logger="activitysim_viz.dashboard.export"):
        build_export_html_document([], config, summary_runs=[_full_summary_run()])

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "HTML export payload is estimated at" in message
        and "dashboard states before Plotly JS" in message
        and "serialized separately" in message
        for message in messages
    )


def test_export_logs_static_heavy_region_warning_with_disable_hint(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = _workspace_tmp_dir("warning_static_region")
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview"],
        export_html_lines=[
            "pages:",
            "  overview: {}",
        ],
    )

    monkeypatch.setattr(export_payload, "PAGE_WARNING_BYTES", 1_000)
    monkeypatch.setattr(export_payload, "STATIC_REGION_WARNING_BYTES", 1_000)
    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_WARNING_BYTES", 10**9)
    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_STRONG_WARNING_BYTES", 10**9)

    with caplog.at_level(logging.WARNING, logger="activitysim_viz.dashboard.export"):
        build_export_html_document([], config, summary_runs=[_full_summary_run()])

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "HTML export page overview contributes about" in message
        for message in messages
    )
    assert any(
        "overview is large because region body contributes about"
        in message
        and "visualizer.export_html.pages.overview.parts.body.enabled: false"
        in message
        for message in messages
    )


def test_export_logs_selector_expansion_warning_with_disable_hint(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = _workspace_tmp_dir("warning_selector_region")
    config = _write_config(
        tmp_path,
        dashboard_pages=["tour_summaries"],
        export_html_lines=[
            "pages:",
            "  tour_summaries:",
            "    tour_mode:",
            "      tour_purpose: all",
        ],
    )

    monkeypatch.setattr(export_payload, "PAGE_WARNING_BYTES", 1_000)
    monkeypatch.setattr(export_payload, "SELECTOR_REGION_WARNING_BYTES", 1_000)
    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_WARNING_BYTES", 10**9)
    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_STRONG_WARNING_BYTES", 10**9)

    with caplog.at_level(logging.WARNING, logger="activitysim_viz.dashboard.export"):
        build_export_html_document([], config, summary_runs=[_full_summary_run()])

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "tour_mode expands region tour_mode_modes to 8 selector combinations"
        in message
        and "selectors: tour_purpose, auto_sufficiency" in message
        and "visualizer.export_html.pages.tour_summaries.children.tour_mode.parts.tour_mode_modes.enabled: false"
        in message
        for message in messages
    )


def test_export_size_warnings_stay_quiet_for_small_export(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = _workspace_tmp_dir("warning_small_export")
    config = _write_config(
        tmp_path,
        dashboard_pages=["raw_trip_demo"],
        export_html_lines=[
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )

    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_WARNING_BYTES", 10**9)
    monkeypatch.setattr(export_payload, "TOTAL_PAYLOAD_STRONG_WARNING_BYTES", 10**9)
    monkeypatch.setattr(export_payload, "PAGE_WARNING_BYTES", 10**9)
    monkeypatch.setattr(export_payload, "STATIC_REGION_WARNING_BYTES", 10**9)
    monkeypatch.setattr(export_payload, "SELECTOR_REGION_WARNING_BYTES", 10**9)

    with caplog.at_level(logging.WARNING, logger="activitysim_viz.dashboard.export"):
        build_export_html_document([], config, summary_runs=[_full_summary_run()])

    messages = [record.getMessage() for record in caplog.records]
    assert not any(
        "HTML export payload is estimated at" in message
        or "HTML export page" in message
        for message in messages
    )


def test_export_size_analysis_is_written_to_diagnostics_sidecar() -> None:
    tmp_path = _workspace_tmp_dir("warning_size_sidecar")
    config = _write_config(
        tmp_path,
        dashboard_pages=["raw_trip_demo"],
        export_html_lines=[
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )
    out_path = tmp_path / "dashboard.html"

    write_export_html_document(out_path, [], config, summary_runs=[_full_summary_run()])

    diagnostics = (tmp_path / "dashboard.diagnostics.json").read_text(encoding="utf-8")
    parsed = json.loads(diagnostics)
    size_analysis = parsed["size_analysis"]

    assert size_analysis["total_payload_bytes"] > 0
    assert size_analysis["state_count"] == 4
    assert "Weighted||Percent" in size_analysis["states"]
    assert size_analysis["states"]["Weighted||Percent"]["pages"]["raw_trip_demo"]["payload_bytes"] > 0


def test_export_size_analysis_sanitizes_nan_values() -> None:
    payload = {
        "states": {
            "Weighted||Percent": {
                "example": {
                    "kind": "page",
                    "content": {
                        "kind": "region",
                        "region_id": "body",
                        "selector_ids": [],
                        "default_content": {"value": float("nan")},
                        "variants": {},
                    },
                }
            }
        }
    }

    analysis = analyze_export_payload_size(payload)

    assert analysis["total_payload_bytes"] > 0
    assert analysis["states"]["Weighted||Percent"]["pages"]["example"]["payload_bytes"] > 0
