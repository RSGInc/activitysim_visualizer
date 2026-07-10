from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dashboard_expectations import EXPECTED_DEFAULT_PAGES
from dashboard import DashboardState
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.export.context import ExportBuildContext
from dashboard.export.payload import (
    VMT_EXPORT_DROPDOWN_NOTE,
    _with_export_page_notes,
    build_export_payload,
)
from dashboard.export.types import (
    EXPORT_CLIENT_RUNTIME,
    EXPORT_PAGE_SELECTOR_RUNTIME,
    EXPORT_SCHEMA_VERSION,
)
from dashboard.page_definitions import DashboardPageDefinition
from test_export_html import (
    _full_summary_run,
    _segmented_summary_runs,
    _region_nodes,
    _skim_summary_run,
    _walk_nodes,
    _write_config,
)


def _workspace_tmp_dir(label: str) -> Path:
    path = Path("tmp_export_test_artifacts") / f"{label}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _first_plot_trace_names(page_payload: dict) -> list[str]:
    plot = next(node for node in _walk_nodes(page_payload) if node.get("kind") == "plotly")
    return [str(trace.get("name")) for trace in plot.get("figure", {}).get("data", [])]


def _plot_nodes(page_payload: dict) -> list[dict]:
    return [node for node in _walk_nodes(page_payload) if node.get("kind") == "plotly"]


def test_vmt_export_content_includes_dropdown_availability_note() -> None:
    title_node = {"kind": "html", "html": "<h2>VMT Validation</h2>"}
    section_node = {"kind": "html", "html": "<h3>Personal Auto VMT</h3>"}
    content = {
        "kind": "container",
        "layout": "column",
        "child_count": 2,
        "children": [title_node, section_node],
        "styles": {},
        "css_classes": [],
    }

    vmt_content = _with_export_page_notes(
        DashboardPageDefinition(page_id="vmt", title="VMT Validation"),
        content,
    )
    overview_content = _with_export_page_notes(
        DashboardPageDefinition(page_id="overview", title="Overview"),
        content,
    )

    assert overview_content is content
    assert vmt_content["kind"] == "container"
    assert vmt_content["child_count"] == 3
    assert vmt_content["children"][0] is title_node
    assert VMT_EXPORT_DROPDOWN_NOTE in vmt_content["children"][1]["html"]
    assert vmt_content["children"][2] is section_node


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


def test_trip_mode_export_keeps_explicit_height_for_overall_plot() -> None:
    tmp_path = _workspace_tmp_dir("payload_trip_mode_height")
    config = _write_config(
        tmp_path,
        dashboard_pages=["trip_mode"],
        export_html_lines=[
            "pages:",
            "  trip_mode: {}",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])
    plots = _plot_nodes(payload["states"]["Weighted||Count"]["trip_mode"])
    overall_plot = next(
        plot
        for plot in plots
        if plot.get("figure", {}).get("layout", {}).get("title", {}).get("text")
        == "Trip Mode Distribution for All Tours"
    )

    assert overall_plot["height"] == 400
    assert overall_plot["figure"]["layout"]["height"] == 400


def test_density_hover_mode_is_serialized_in_export_payload() -> None:
    tmp_path = _workspace_tmp_dir("payload_density_hover")
    config = _write_config(
        tmp_path,
        dashboard_pages=["tour_time"],
        extra_lines=[
            "display:",
            "  density_hover_mode: all",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])
    plots = _plot_nodes(payload["states"]["Weighted||Percent"]["tour_time"])

    assert any(
        plot.get("figure", {}).get("layout", {}).get("hovermode") == "x unified"
        for plot in plots
    )


def test_build_export_payload_defaults_to_live_segmentation_filter() -> None:
    tmp_path = _workspace_tmp_dir("payload_segmentation_fallback")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  daily_travel:",
            "    daily_activity_pattern: {}",
        ],
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: signup_platform",
            "    visibility: segments_only",
            "  definitions:",
            "    signup_platform:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: signup_platform",
            "      segments:",
            "        - id: browser",
            "          label: Browser",
            "          values: [browser]",
            "        - id: call",
            "          label: Call",
            "          values: [call]",
            "    person_sex:",
            "      source:",
            "        type: prepared_column",
            "        source_table: per",
            "        column: sex",
            "      segments:",
            "        - id: male",
            "          label: Male",
            "          values: [1]",
        ],
    )

    payload = build_export_payload([], config, summary_runs=_segmented_summary_runs())

    assert payload["runs_loaded"] == [
        {"label": "Base (Browser)", "color": "#1f77b4"},
        {"label": "Base (Call)", "color": "#ff7f0e"},
    ]
    assert _first_plot_trace_names(
        payload["states"]["Weighted||Percent"]["daily_activity_pattern"]
    ) == ["Base (Browser)", "Base (Call)"]


def test_build_export_payload_honors_export_segmentation_overrides() -> None:
    tmp_path = _workspace_tmp_dir("payload_segmentation_override")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  segmentation_type: person_sex",
            "  segmentation_visibility: full_and_segments",
            "pages:",
            "  daily_travel:",
            "    daily_activity_pattern: {}",
        ],
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: signup_platform",
            "    visibility: segments_only",
            "  definitions:",
            "    signup_platform:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: signup_platform",
            "      segments:",
            "        - id: browser",
            "          label: Browser",
            "          values: [browser]",
            "        - id: call",
            "          label: Call",
            "          values: [call]",
            "    person_sex:",
            "      source:",
            "        type: prepared_column",
            "        source_table: per",
            "        column: sex",
            "      segments:",
            "        - id: male",
            "          label: Male",
            "          values: [1]",
        ],
    )

    payload = build_export_payload([], config, summary_runs=_segmented_summary_runs())

    assert payload["runs_loaded"] == [
        {"label": "Base (Full)", "color": "#1f77b4"},
        {"label": "Base (Male)", "color": "#ff7f0e"},
    ]
    assert _first_plot_trace_names(
        payload["states"]["Weighted||Percent"]["daily_activity_pattern"]
    ) == ["Base (Full)", "Base (Male)"]


def test_build_export_payload_supports_export_full_only_segmentation() -> None:
    tmp_path = _workspace_tmp_dir("payload_segmentation_full_only")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  segmentation_type: signup_platform",
            "  segmentation_visibility: full_only",
            "pages:",
            "  daily_travel:",
            "    daily_activity_pattern: {}",
        ],
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: signup_platform",
            "    visibility: full_and_segments",
            "  definitions:",
            "    signup_platform:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: signup_platform",
            "      segments:",
            "        - id: browser",
            "          label: Browser",
            "          values: [browser]",
            "        - id: call",
            "          label: Call",
            "          values: [call]",
        ],
    )

    payload = build_export_payload([], config, summary_runs=_segmented_summary_runs())

    assert payload["runs_loaded"] == [{"label": "Base", "color": "#1f77b4"}]
    assert _first_plot_trace_names(
        payload["states"]["Weighted||Percent"]["daily_activity_pattern"]
    ) == ["Base"]


def test_export_build_context_does_not_change_live_segmentation_defaults() -> None:
    tmp_path = _workspace_tmp_dir("payload_segmentation_live_regression")
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  segmentation_type: person_sex",
            "  segmentation_visibility: full_only",
        ],
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: signup_platform",
            "    visibility: segments_only",
            "  definitions:",
            "    signup_platform:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: signup_platform",
            "      segments:",
            "        - id: browser",
            "          label: Browser",
            "          values: [browser]",
            "        - id: call",
            "          label: Call",
            "          values: [call]",
            "    person_sex:",
            "      source:",
            "        type: prepared_column",
            "        source_table: per",
            "        column: sex",
            "      segments:",
            "        - id: male",
            "          label: Male",
            "          values: [1]",
        ],
    )
    summary_runs = _segmented_summary_runs()

    live_state = DashboardState(
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
        dashboard_segmentation_type=config.segmentation.dashboard.segmentation_type,
        default_segmentation_visibility=config.segmentation.dashboard.visibility,
    )
    export_state = ExportBuildContext(
        config=config,
        summary_runs=summary_runs,
        prepared_run_provider=DashboardPreparedRunProvider.not_requested(),
    ).build_dashboard_state()

    assert live_state.run_labels == ["Base (Browser)", "Base (Call)"]
    assert export_state.run_labels == ["Base"]


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
        extra_lines=[
            "categories:",
            "  mode:",
            "    mapping:",
            "      DRIVEALONE: Drive Alone",
            "      WALK: Walk",
            "      SHARED: Shared Ride",
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
            "resolved_values": ["All Tour Purposes", "eatout", "social"],
            "default_value": "All Tour Purposes",
            "options": ["All Tour Purposes", "eatout", "social"],
            "export_enabled": True,
        },
        {
            "id": "hide_drive_alone",
            "label": "Hide Auto Modes",
            "available": True,
            "request_mode": "all",
            "requested_values": [],
            "resolved_values": ["False", "True"],
            "default_value": "False",
            "options": ["False", "True"],
            "export_enabled": True,
        },
    ]

    trip_mode = payload["states"]["Weighted||Percent"]["trip_mode"]
    assert trip_mode["kind"] == "page"
    regions = _region_nodes(trip_mode)
    assert sorted(regions) == ["trip_summary_mode_body"]
    trip_mode_region = regions["trip_summary_mode_body"]
    assert trip_mode_region["selector_ids"] == ["tour_purpose", "hide_drive_alone"]
    assert trip_mode_region["default_key"] == '["All Tour Purposes","False"]'
    assert sorted(trip_mode_region["variants"]) == [
        '["All Tour Purposes","False"]',
        '["All Tour Purposes","True"]',
        '["eatout","False"]',
        '["eatout","True"]',
        '["social","False"]',
        '["social","True"]',
    ]
    page_nodes = _walk_nodes(trip_mode)
    assert any(
        node.get("kind") == "widget"
        and node.get("selector_id") == "tour_purpose"
        and node.get("name") == "Tour Purpose"
        and node.get("export_enabled")
        for node in page_nodes
    )
    assert any(
        node.get("kind") == "widget"
        and node.get("selector_id") == "hide_drive_alone"
        and node.get("name") == "Hide Auto Modes"
        and node.get("export_enabled")
        for node in page_nodes
    )
    assert not any(
        node.get("kind") == "html" and "Tour Purpose:" in node.get("html", "")
        for node in page_nodes
    )
    assert not any(node.get("selector_id") == "tour_mode" for node in page_nodes)
    variant_nodes = _walk_nodes(trip_mode_region["variants"]['["eatout","False"]'])
    assert any(node.get("kind") == "plotly" for node in variant_nodes)
    checked_variant_nodes = _walk_nodes(trip_mode_region["variants"]['["eatout","True"]'])
    checked_plot = next(node for node in checked_variant_nodes if node.get("kind") == "plotly")
    checked_x_values = [
        value
        for trace in checked_plot.get("figure", {}).get("data", [])
        for value in trace.get("x", [])
    ]
    assert "Drive Alone" not in checked_x_values


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


def test_build_export_payload_keeps_grouped_trip_selector_pages_export_ready() -> None:
    tmp_path = _workspace_tmp_dir("payload_grouped_trip_selectors")
    config = _write_config(
        tmp_path,
        dashboard_pages=[{"trip_summaries": ["trip_mode", "trip_stop_time"]}],
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose: all",
            "    trip_stop_time:",
            "      tour_purpose: all",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])
    grouped_page = payload["pages"][0]
    weighted_percent = payload["states"]["Weighted||Percent"]

    assert grouped_page["id"] == "trip_summaries"
    assert grouped_page["default_page_id"] == "trip_mode"
    assert [child["id"] for child in grouped_page["children"]] == [
        "trip_mode",
        "trip_stop_time",
    ]
    assert any(
        selector["id"] == "tour_purpose" and selector["export_enabled"]
        for selector in grouped_page["children"][0]["selectors"]
    )
    assert any(
        selector["id"] == "tour_purpose" and selector["export_enabled"]
        for selector in grouped_page["children"][1]["selectors"]
    )
    assert "trip_mode" in weighted_percent
    assert "trip_stop_time" in weighted_percent


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


def test_build_export_payload_skips_prepared_only_sections_but_keeps_summary_safe_skims_content() -> None:
    tmp_path = _workspace_tmp_dir("payload_skims_summary_safe")
    config = _write_config(
        tmp_path,
        dashboard_pages=["skims"],
        export_html_lines=[
            "pages:",
            "  skims: {}",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_skim_summary_run()])

    assert payload["pages"] == [
        {
            "id": "skims",
            "title": "Skim Summaries",
            "selectors": [],
            "children": [
                {
                    "id": "tour_skims",
                    "title": "Tour Skims",
                    "selectors": [
                        {
                            "id": "tour_skim_family",
                            "label": "Tour Skim Family",
                            "available": True,
                            "request_mode": "all",
                            "requested_values": [],
                            "resolved_values": ["Walk Skims"],
                            "default_value": "Walk Skims",
                            "options": ["Walk Skims"],
                            "export_enabled": False,
                        },
                        {
                            "id": "tour_skim_direction",
                            "label": "Direction",
                            "available": True,
                            "request_mode": "all",
                            "requested_values": [],
                            "resolved_values": ["Outbound"],
                            "default_value": "Outbound",
                            "options": ["Outbound"],
                            "export_enabled": False,
                        },
                    ],
                    "children": [],
                    "default_page_id": None,
                },
                {
                    "id": "trip_skims",
                    "title": "Trip Skims",
                    "selectors": [
                        {
                            "id": "trip_skim_family",
                            "label": "Trip Skim Family",
                            "available": True,
                            "request_mode": "all",
                            "requested_values": [],
                            "resolved_values": ["Walk Skims"],
                            "default_value": "Walk Skims",
                            "options": ["Walk Skims"],
                            "export_enabled": False,
                        }
                    ],
                    "children": [],
                    "default_page_id": None,
                },
            ],
            "default_page_id": "tour_skims",
        }
    ]
    weighted_state = payload["states"]["Weighted||Percent"]
    nodes = _walk_nodes(weighted_state["tour_skims"]) + _walk_nodes(
        weighted_state["trip_skims"]
    )
    region_ids = sorted(
        list(_region_nodes(weighted_state["tour_skims"]).keys())
        + list(_region_nodes(weighted_state["trip_skims"]).keys())
    )

    assert region_ids == ["tour_skim_summary_section", "trip_skim_summary_section"]
    assert not any(node.get("widget_type") == "float_input" for node in nodes)
    assert not any(node.get("selector_id") in {"trip_min", "trip_max", "tour_min", "tour_max"} for node in nodes)


def test_build_export_payload_omits_prepared_only_pages() -> None:
    tmp_path = _workspace_tmp_dir("payload_prepared_only_page")
    config = _write_config(
        tmp_path,
        dashboard_pages=["raw_trip_demo"],
        export_html_lines=[
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )

    payload = build_export_payload([], config, summary_runs=[_full_summary_run()])

    assert payload["pages"] == []
    assert payload["states"]["Weighted||Percent"] == {}
