from __future__ import annotations

import json
from pathlib import Path
import sys
from uuid import uuid4

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
    path = Path("tmp_export_test_artifacts") / f"{label}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_export_html_smoke_writes_single_self_contained_file() -> None:
    tmp_path = _workspace_tmp_dir("html_smoke_file")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
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
        dashboard_pages=["trip_summaries"],
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
    assert trip_summaries["default_page_id"] == "trip_stop_purpose"
    assert [(child["id"], child["title"]) for child in trip_summaries["children"]] == [
        ("trip_stop_purpose", "Trip and Stop Purpose"),
        ("trip_mode", "Trip Mode"),
        ("trip_stop_time", "Trip and Stop Time"),
        ("trip_stop_distance", "Trip and Stop Distance"),
    ]
    trip_mode = next(child for child in trip_summaries["children"] if child["id"] == "trip_mode")
    assert trip_mode["selectors"] == [
        {
            "id": "tour_purpose",
            "label": "Tour Purpose",
            "available": True,
            "request_mode": "all",
            "requested_values": [],
            "resolved_values": ["All", "eatout", "social"],
            "default_value": "All",
            "options": ["All", "eatout", "social"],
            "export_enabled": True,
        }
    ]
    assert payload["states"]["Weighted||Percent"]["trip_mode"]["kind"] == "page"
    assert "Unsupported export schema version." in html
    assert "__EXPORT_SCHEMA_VERSION__" not in html


def test_export_runtime_assets_are_loaded_from_source_files() -> None:
    css = load_export_css()
    runtime_js = load_export_runtime_js()

    assert ".export-shell" in css
    assert ".export-error-panel" in css
    assert "function validatePayloadSchema(candidate)" in runtime_js
    assert "function renderPlot(node)" in runtime_js
    assert "function renderNode(node, leafPageId)" in runtime_js
    assert "function renderRegion(node, leafPageId)" in runtime_js
    assert "function resolveActiveChildPageId(pageDescriptor)" in runtime_js
    assert "Plotly.react" in runtime_js
    assert "__EXPORT_SCHEMA_VERSION__" not in runtime_js


def test_export_html_smoke_serializes_grouped_default_page_as_leaf_page_id() -> None:
    tmp_path = _workspace_tmp_dir("html_smoke_grouped_defaults")
    config = _write_config(
        tmp_path,
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
