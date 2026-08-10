from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.export.html import write_export_html_document
from dashboard.export.runtime_assets import (
    load_export_css,
    load_export_runtime_js,
)
from dashboard.export.types import EXPORT_SCHEMA_VERSION
from test_export_html import _full_summary_run, _write_config


def _workspace_tmp_dir(label: str) -> Path:
    path = Path(".pytest_tmp") / "export_helpers" / label
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_export_html_smoke_writes_single_self_contained_file() -> None:
    tmp_path = _workspace_tmp_dir("html_smoke_file")
    config = _write_config(
        tmp_path,
        dashboard_pages=[{"trip_summaries": ["trip_mode"]}],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  trip_mode: {}",
        ],
    )
    out_path = tmp_path / "smoke" / "dashboard.html"

    write_export_html_document(
        out_path,
        [],
        config,
        summary_runs=[_full_summary_run()],
    )

    assert out_path.exists()
    assert sorted(path.name for path in out_path.parent.iterdir()) == [
        "dashboard.diagnostics.json",
        "dashboard.html",
    ]

    html = out_path.read_text(encoding="utf-8")
    assert "activitysim-export-data" in html
    assert "Export payload JSON could not be parsed." in html
    assert "Plotly.react" in html
    assert 'displayModeBar: "hover"' in html
    assert "scale: 2" in html
    assert 'name: "Download CSV"' in html
    assert "modeBarButtonsToAdd: [makePlotCsvDownloadButton(figure)]" in html
    assert "Offline export failed to load" in html
    assert "This HTML export encountered a runtime rendering error." in html
    assert "Unknown export node kind encountered:" in html
    assert "Missing page state for the active dashboard selection." in html
    assert "Runs Loaded" in html
    assert "Display Options" in html
    assert "Tour Purpose" in html
    assert "panel.models.state.State" not in html


def test_export_html_smoke_embeds_versioned_payload_and_runtime() -> None:
    tmp_path = _workspace_tmp_dir("html_smoke_payload")
    config = _write_config(
        tmp_path,
        dashboard_pages=[{"trip_summaries": ["trip_mode"]}],
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose: all",
        ],
    )
    out_path = tmp_path / "smoke" / "trip_mode.html"

    write_export_html_document(
        out_path,
        [],
        config,
        summary_runs=[_full_summary_run()],
    )

    html = out_path.read_text(encoding="utf-8")
    start_token = '<script id="activitysim-export-data" type="application/json">'
    start = html.index(start_token) + len(start_token)
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])

    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert [(page["id"], page["title"]) for page in payload["pages"]] == [
        ("trip_summaries", "Trip Summaries")
    ]
    trip_summaries = payload["pages"][0]
    assert trip_summaries["default_page_id"] == "trip_mode"
    assert [(child["id"], child["title"]) for child in trip_summaries["children"]] == [
        ("trip_mode", "Trip Mode"),
    ]
    trip_mode = next(child for child in trip_summaries["children"] if child["id"] == "trip_mode")
    selectors = {selector["id"]: selector for selector in trip_mode["selectors"]}
    assert selectors["tour_purpose"] == {
        "id": "tour_purpose",
        "label": "Tour Purpose",
        "available": True,
        "request_mode": "all",
        "requested_values": [],
        "resolved_values": ["All Tour Purposes", "eatout", "social"],
        "default_value": "All Tour Purposes",
        "options": ["All Tour Purposes", "eatout", "social"],
        "export_enabled": True,
    }
    assert selectors["hide_drive_alone"]["resolved_values"] == ["False", "True"]
    assert payload["states"]["Weighted||Percent"]["trip_mode"]["kind"] == "page"
    assert "Unsupported export schema version." in html
    assert "__EXPORT_SCHEMA_VERSION__" not in html


def test_export_runtime_assets_are_loaded_from_source_files() -> None:
    css = load_export_css()
    runtime_js = load_export_runtime_js()

    assert ".export-shell" in css
    assert ".export-error-panel" in css
    assert ".export-table-sort" in css
    assert ".export-layout.rail-collapsed" in css
    assert ".export-layout.rail-collapsed .export-rail" in css
    assert ".export-logo" in css
    assert "function validatePayloadSchema(candidate)" in runtime_js
    assert "function renderPlot(node, context)" in runtime_js
    assert "function renderTable(node)" in runtime_js
    assert "function renderNode(node, context, actions, leafPageId)" in runtime_js
    assert "function renderRegion(node, context, actions, leafPageId)" in runtime_js
    assert "function getLeafPageId(currentPayload, currentState)" in runtime_js
    assert "function createRuntimeContext(config)" in runtime_js
    assert "function createRuntimeActions(context)" in runtime_js
    assert 'className: "export-logo"' in runtime_js
    assert "Plotly.react" in runtime_js
    assert "__EXPORT_SCHEMA_VERSION__" not in runtime_js


def test_export_html_smoke_serializes_grouped_default_page_as_leaf_page_id() -> None:
    tmp_path = _workspace_tmp_dir("html_smoke_grouped_defaults")
    config = _write_config(
        tmp_path,
        dashboard_pages=[
            {"daily_travel": ["daily_activity_pattern"]},
            {"tour_summaries": ["tour_purpose"]},
            {"trip_summaries": ["trip_stop_purpose"]},
        ],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )
    out_path = tmp_path / "smoke" / "grouped_dashboard.html"

    write_export_html_document(
        out_path,
        [],
        config,
        summary_runs=[_full_summary_run()],
    )

    html = out_path.read_text(encoding="utf-8")
    start_token = '<script id="activitysim-export-data" type="application/json">'
    start = html.index(start_token) + len(start_token)
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    page_by_id = {page["id"]: page for page in payload["pages"]}

    assert page_by_id["daily_travel"]["default_page_id"] == "daily_activity_pattern"
    assert page_by_id["tour_summaries"]["default_page_id"] == "tour_purpose"
    assert page_by_id["trip_summaries"]["default_page_id"] == "trip_stop_purpose"
    assert page_by_id["daily_travel"]["default_page_id"] in [
        child["id"] for child in page_by_id["daily_travel"]["children"]
    ]
    assert page_by_id["tour_summaries"]["default_page_id"] in [
        child["id"] for child in page_by_id["tour_summaries"]["children"]
    ]
    assert page_by_id["trip_summaries"]["default_page_id"] in [
        child["id"] for child in page_by_id["trip_summaries"]["children"]
    ]
