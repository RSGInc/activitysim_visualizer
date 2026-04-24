from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dashboard_expectations import EXPECTED_DEFAULT_PAGES
from dashboard.export.payload import build_export_payload
from dashboard.export.types import (
    EXPORT_CLIENT_RUNTIME,
    EXPORT_PAGE_SELECTOR_RUNTIME,
    EXPORT_SCHEMA_VERSION,
)
from test_export_html import _full_summary_run, _walk_nodes, _write_config


def _workspace_tmp_dir(label: str) -> Path:
    path = Path("tmp_export_test_artifacts") / f"{label}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_build_export_payload_has_stable_top_level_contract() -> None:
    tmp_path = _workspace_tmp_dir("payload_contract")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])

    assert list(payload) == [
        "schema_version",
        "title",
        "runs_loaded",
        "chrome",
        "dashboard_controls",
        "default_state",
        "pages",
        "states",
        "page_export_support",
        "client_runtime",
    ]
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert payload["client_runtime"] == EXPORT_CLIENT_RUNTIME
    assert (
        payload["page_export_support"]["client_side_runtime"]
        == EXPORT_PAGE_SELECTOR_RUNTIME
    )
    assert [(page["id"], page["title"]) for page in payload["pages"]] == EXPECTED_DEFAULT_PAGES
    assert sorted(payload["states"]) == [
        "Unweighted||Count",
        "Unweighted||Percent",
        "Weighted||Count",
        "Weighted||Percent",
    ]


def test_build_export_payload_serializes_representative_page_variants_structure(
) -> None:
    tmp_path = _workspace_tmp_dir("payload_variants")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  trip_mode:",
            "    tour_purpose: all",
            "    tour_mode: all",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])

    assert payload["pages"] == [
        {
            "id": "trip_mode",
            "title": "Trip Mode",
            "selectors": [
                {
                    "id": "tour_purpose",
                    "label": "Tour Purpose",
                    "available": True,
                    "request_mode": "all",
                    "requested_values": [],
                    "resolved_values": ["Total", "eatout", "social"],
                    "default_value": "Total",
                    "options": ["Total", "eatout", "social"],
                    "export_enabled": True,
                },
                {
                    "id": "tour_mode",
                    "label": "Tour Mode",
                    "available": True,
                    "request_mode": "all",
                    "requested_values": [],
                    "resolved_values": ["All", "DRIVE", "WALK"],
                    "default_value": "All",
                    "options": ["All", "DRIVE", "WALK"],
                    "export_enabled": True,
                },
            ],
            "children": [],
            "default_child_id": None,
        }
    ]

    trip_mode = payload["states"]["Weighted||Percent"]["trip_mode"]
    assert trip_mode["kind"] == "page_variants"
    assert trip_mode["selector_ids"] == ["tour_purpose", "tour_mode"]
    assert trip_mode["default_key"] == '["Total","All"]'
    assert sorted(trip_mode["variants"]) == [
        '["Total","All"]',
        '["Total","DRIVE"]',
        '["Total","WALK"]',
        '["eatout","All"]',
        '["eatout","DRIVE"]',
        '["eatout","WALK"]',
        '["social","All"]',
        '["social","DRIVE"]',
        '["social","WALK"]',
    ]
    variant_nodes = _walk_nodes(trip_mode["variants"]['["eatout","DRIVE"]'])
    assert any(node.get("kind") == "plotly" for node in variant_nodes)
    assert any(
        node.get("kind") == "widget"
        and node.get("selector_id") == "tour_purpose"
        and node.get("export_enabled")
        for node in variant_nodes
    )
    assert any(
        node.get("kind") == "widget"
        and node.get("selector_id") == "tour_mode"
        and node.get("export_enabled")
        for node in variant_nodes
    )


def test_build_export_payload_keeps_static_pages_when_no_page_selectors_are_enabled() -> None:
    tmp_path = _workspace_tmp_dir("payload_static")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  overview: {}",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])

    assert payload["pages"] == [
        {
            "id": "overview",
            "title": "Overview",
            "selectors": [],
            "children": [],
            "default_child_id": None,
        }
    ]
    overview = payload["states"]["Weighted||Percent"]["overview"]
    assert overview["kind"] == "static_page"
    nodes = _walk_nodes(overview)
    assert any(node.get("kind") == "card" for node in nodes)


def test_build_export_payload_normalizes_group_default_child_ids_to_leaf_page_ids() -> None:
    tmp_path = _workspace_tmp_dir("payload_group_defaults")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])
    page_by_id = {page["id"]: page for page in payload["pages"]}

    assert page_by_id["tours"]["default_child_id"] == "tour_summary"
    assert page_by_id["stops"]["default_child_id"] == "stop_frequency"
    assert page_by_id["tours"]["default_child_id"] in [
        child["id"] for child in page_by_id["tours"]["children"]
    ]
    assert page_by_id["stops"]["default_child_id"] in [
        child["id"] for child in page_by_id["stops"]["children"]
    ]
    assert page_by_id["tours"]["default_child_id"] != "summary"
    assert page_by_id["stops"]["default_child_id"] != "frequency"
