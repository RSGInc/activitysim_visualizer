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
from test_export_html import _full_summary_run, _region_nodes, _walk_nodes, _write_config


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


def test_build_export_payload_serializes_representative_page_region_structure(
) -> None:
    tmp_path = _workspace_tmp_dir("payload_variants")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose: all",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])

    page_by_id = {page["id"]: page for page in payload["pages"]}
    trip_summaries = page_by_id["trip_summaries"]
    trip_mode_page = next(child for child in trip_summaries["children"] if child["id"] == "trip_mode")
    assert trip_mode_page["selectors"] == [
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

    trip_mode = payload["states"]["Weighted||Percent"]["trip_mode"]
    assert trip_mode["kind"] == "page"
    regions = _region_nodes(trip_mode)
    assert sorted(regions) == ["trip_summary_mode_body"]
    trip_mode_region = regions["trip_summary_mode_body"]
    assert trip_mode_region["selector_ids"] == ["tour_purpose"]
    assert trip_mode_region["default_key"] == '["All"]'
    assert sorted(trip_mode_region["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]
    page_nodes = _walk_nodes(trip_mode)
    assert any(
        node.get("kind") == "widget"
        and node.get("selector_id") == "tour_purpose"
        and node.get("export_enabled")
        for node in page_nodes
    )
    assert not any(node.get("selector_id") == "tour_mode" for node in page_nodes)
    variant_nodes = _walk_nodes(trip_mode_region["variants"]['["eatout"]'])
    assert any(node.get("kind") == "plotly" for node in variant_nodes)


def test_build_export_payload_keeps_static_pages_when_no_page_selectors_are_enabled() -> None:
    tmp_path = _workspace_tmp_dir("payload_static")
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview"],
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
            "default_page_id": None,
        }
    ]
    overview = payload["states"]["Weighted||Percent"]["overview"]
    assert overview["kind"] == "page"
    nodes = _walk_nodes(overview)
    assert any(node.get("kind") == "card" for node in nodes)


def test_build_export_payload_normalizes_group_default_page_ids_to_leaf_page_ids() -> None:
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
    assert page_by_id["tour_summaries"]["default_page_id"] != "summary"
    assert page_by_id["trip_summaries"]["default_page_id"] != "purpose"


def test_build_export_payload_applies_excluded_pages_and_groups() -> None:
    tmp_path = _workspace_tmp_dir("payload_exclusions")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "exclude_pages:",
            "  - shadow_pricing",
            "exclude_groups:",
            "  - validation",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])
    page_ids = [page["id"] for page in payload["pages"]]
    leaf_page_ids = list(payload["states"]["Weighted||Percent"])

    assert "validation" not in page_ids
    assert "shadow_pricing" not in leaf_page_ids
    assert "traffic" not in leaf_page_ids
    assert "transit" not in leaf_page_ids
    assert "vmt" not in leaf_page_ids


def test_build_export_payload_disables_shadow_pricing_table_parts() -> None:
    tmp_path = _workspace_tmp_dir("payload_shadow_parts")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  long_term_choices:",
            "    shadow_pricing:",
            "      parts:",
            "        workplace_table:",
            "          enabled: false",
            "        school_table:",
            "          enabled: false",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])
    shadow_pricing = payload["states"]["Weighted||Percent"]["shadow_pricing"]
    nodes = _walk_nodes(shadow_pricing)
    region_ids = sorted(_region_nodes(shadow_pricing))

    assert region_ids == ["school_plot", "workplace_plot"]
    assert not any(node.get("kind") == "table" for node in nodes)
