from __future__ import annotations

import json
from pathlib import Path
import sys

import panel as pn
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.export.selector_states import (
    resolve_export_section_states,
    selector_options as _selector_options,
    selector_values_for_current_state,
    scoped_widget_values,
)
from dashboard.export.page_serializer import _refresh_page_part_view
from dashboard.export.runtime_assets import build_export_html_shell, load_export_runtime_js
from dashboard.export.serializer import serialize_viewable
from dashboard.export.types import EXPORT_SCHEMA_VERSION
from dashboard.page_definitions import DashboardPageDefinition
from test_export_html import _full_summary_run, _write_config
from dashboard.export.html import build_export_html_document


FIXTURE_DIR = Path(__file__).with_name("fixtures")
REQUIRED_TOP_LEVEL_FIELDS = {
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
}


def test_explicit_selector_enumeration_uses_resolved_display_values() -> None:
    widget = pn.widgets.Select(
        options=["All Person Types", "worker"],
        value="All Person Types",
    )
    metadata = {
        "request_mode": "explicit",
        "requested_values": ["all", "worker"],
        "resolved_values": ["All Person Types", "worker"],
    }

    assert selector_values_for_current_state(
        selector_id="person_type",
        widget=widget,
        selector_metadata=metadata,
    ) == ["All Person Types", "worker"]


def test_dependent_selector_enumeration_uses_only_current_parent_options() -> None:
    widget = pn.widgets.Select(
        options=["All", "Alpha County", "Regional MPO", "101", "102"],
        value="All",
    )
    metadata = {
        "request_mode": "all",
        "requested_values": [],
        "resolved_values": ["All", "Alpha County", "Regional MPO"],
        "parent_selector_id": "geography_level",
        "options_by_parent_value": {
            "All Geography Types": ["All"],
            "County": ["All", "Alpha County"],
            "MPO": ["All", "Regional MPO"],
        },
    }

    assert selector_values_for_current_state(
        selector_id="geography",
        widget=widget,
        selector_metadata=metadata,
        selected_values={"geography_level": "County"},
    ) == ["All", "Alpha County"]


def test_export_part_refresh_targets_only_the_current_registered_section() -> None:
    view = pn.Column()

    class ProbePage:
        def __init__(self) -> None:
            self.cleared = 0
            self.stale_sections: list[str] = []
            self.refresh_forces: list[bool] = []

        def clear_query_cache(self) -> None:
            self.cleared += 1

        def mark_section_stale(self, section_id: str) -> None:
            self.stale_sections.append(section_id)

        def refresh(self, force: bool = False) -> None:
            self.refresh_forces.append(force)

    page = ProbePage()
    part = type(
        "Part",
        (),
        {"part_id": "distance.distribution", "view_for": lambda self, page: view},
    )()

    assert (
        _refresh_page_part_view(
            page,
            part,
            page_id="mandatory_location_choice",
            context_label="during test",
        )
        is view
    )
    assert page.cleared == 1
    assert page.stale_sections == ["distance.distribution"]
    assert page.refresh_forces == [False]


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _assert_valid_runtime_fixture(payload: dict) -> None:
    # The implementation plan called this field `initial_state`, but the
    # repository's current contract uses `default_state`. This assertion locks in
    # the real payload shape rather than inventing a new API.
    assert REQUIRED_TOP_LEVEL_FIELDS <= set(payload)
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert isinstance(payload["pages"], list)
    assert isinstance(payload["states"], dict)
    assert isinstance(payload["default_state"], dict)
    assert isinstance(payload["page_export_support"], dict)


def test_runtime_contract_fixtures_match_expected_top_level_shape() -> None:
    for fixture_name in [
        "minimal_payload.json",
        "grouped_pages_payload.json",
        "selector_region_payload.json",
        "plot_payload.json",
    ]:
        _assert_valid_runtime_fixture(_load_fixture(fixture_name))


def test_malformed_runtime_fixture_is_missing_required_contract_fields() -> None:
    payload = _load_fixture("malformed_payload.json")

    assert "default_state" not in payload
    assert "states" not in payload
    assert REQUIRED_TOP_LEVEL_FIELDS - set(payload)


def test_duplicate_region_fixture_contains_duplicate_region_ids() -> None:
    payload = _load_fixture("duplicate_region_id_payload.json")
    children = payload["states"]["Weighted||Percent"]["trip_mode"]["content"]["children"]

    assert [child["region_id"] for child in children if child["kind"] == "region"] == [
        "shared_region",
        "shared_region",
    ]


def test_invalid_selector_default_fixture_uses_default_not_in_options() -> None:
    payload = _load_fixture("invalid_selector_default_payload.json")
    selector = payload["pages"][0]["selectors"][0]

    assert selector["default_value"] not in selector["options"]


def test_invalid_grouped_default_fixture_uses_unknown_default_page_id() -> None:
    payload = _load_fixture("invalid_grouped_default_payload.json")
    grouped_page = payload["pages"][0]

    assert grouped_page["default_page_id"] == "trip_time"
    assert grouped_page["default_page_id"] not in [
        child["id"] for child in grouped_page["children"]
    ]


def test_unknown_region_selector_fixture_references_missing_leaf_page_selector() -> None:
    payload = _load_fixture("unknown_region_selector_payload.json")
    region = payload["states"]["Weighted||Percent"]["trip_mode"]["content"]
    selector_ids = {selector["id"] for selector in payload["pages"][0]["selectors"]}

    assert region["selector_ids"] == ["missing_selector"]
    assert not set(region["selector_ids"]) <= selector_ids


def test_runtime_asset_replaces_schema_placeholder() -> None:
    runtime_js = load_export_runtime_js()

    assert "__EXPORT_SCHEMA_VERSION__" not in runtime_js
    assert EXPORT_SCHEMA_VERSION in runtime_js


def test_html_shell_embeds_schema_version_payload_runtime_and_css() -> None:
    shell = build_export_html_shell(
        title="Contract Test",
        payload_json='{"schema_version":"%s"}' % EXPORT_SCHEMA_VERSION,
        plotly_js="window.Plotly = {};",
    )

    assert "<style>" in shell
    assert '<script id="activitysim-export-data" type="application/json">' in shell
    assert "window.Plotly = {};" in shell
    assert EXPORT_SCHEMA_VERSION in shell
    assert "__EXPORT_SCHEMA_VERSION__" not in shell


def test_runtime_asset_contains_explicit_context_action_and_region_helpers() -> None:
    runtime_js = load_export_runtime_js()

    assert "function createRuntimeContext(config)" in runtime_js
    assert "function createRuntimeActions(context)" in runtime_js
    assert "function makeButton(config)" in runtime_js
    assert "button.title = String(config.title);" in runtime_js
    assert "function buildRegionVariantKey(selectorValues)" in runtime_js
    assert "const PLOT_RESIZE_RETRY_DELAYS_MS = [60, 180, 320];" in runtime_js
    assert 'displayModeBar: "hover"' in runtime_js
    assert "scale: 2" in runtime_js
    assert 'name: "Download CSV"' in runtime_js
    assert 'title: "Download plot data as CSV"' in runtime_js
    assert "modeBarButtonsToAdd: [makePlotCsvDownloadButton(figure)]" in runtime_js


def test_runtime_asset_exposes_full_table_and_tab_titles_as_tooltips() -> None:
    runtime_js = load_export_runtime_js()

    assert "title: tab.full_title || tab.title" in runtime_js
    assert "(node.column_tooltips || {})[column] || column" in runtime_js


def test_runtime_asset_contains_collapsible_export_rail() -> None:
    runtime_js = load_export_runtime_js()

    assert "railCollapsed: false" in runtime_js
    assert 'rail.id = "export-rail"' in runtime_js
    assert '"aria-controls": "export-rail"' in runtime_js
    assert 'className: "export-layout" + (railCollapsed ? " rail-collapsed" : "")' in runtime_js
    assert 'railCollapsed ? "Show sidebar" : "Hide sidebar"' in runtime_js
    assert 'layout.classList.toggle("rail-collapsed", context.railCollapsed)' in runtime_js
    assert 'context.plotManager.scheduleResize();' in runtime_js


def test_runtime_asset_contains_plot_csv_export_helpers() -> None:
    runtime_js = load_export_runtime_js()

    assert "function csvEscape(value)" in runtime_js
    assert "function slugifyFilenameBase(value)" in runtime_js
    assert "function resolvePlotCsvFilename(figure)" in runtime_js
    assert "function buildTraceCsvRows(gd)" in runtime_js
    assert '"run_name"' in runtime_js
    assert '"x"' in runtime_js
    assert '"y"' in runtime_js
    assert '"trace_index"' not in runtime_js
    assert '"customdata"' not in runtime_js
    assert "trace.meta.run_name" in runtime_js
    assert '"-" + valueMode + ".csv"' in runtime_js
    assert 'return normalized || "plot-data";' in runtime_js


def test_runtime_asset_restores_export_selector_widgets_from_runtime_state() -> None:
    runtime_js = load_export_runtime_js()

    assert (
        "function resolveWidgetValue(node, context, leafPageId, effectiveOptions)"
        in runtime_js
    )
    assert "const pageSelectorState = getPageSelectorState(context.state, leafPageId);" in runtime_js
    assert "const effectiveOptions = resolveWidgetOptions(node, context, leafPageId);" in runtime_js
    assert "const effectiveValue = resolveWidgetValue(" in runtime_js
    assert 'node.widget_type === "checkbox"' in runtime_js
    assert 'node.widget_type === "float_input"' in runtime_js
    assert 'node.widget_type === "button"' in runtime_js
    assert 'checkbox.checked ? "True" : "False"' in runtime_js
    assert 'pageId === "vmt"' in runtime_js
    assert 'selectorId === "personal_auto_vmt_breakdown"' in runtime_js
    assert (
        'pageState.personal_auto_vmt_geography_type = "All Geography Types"'
        in runtime_js
    )
    assert "isVmtGeographyTypeUnavailable" in runtime_js
    assert "function resolveWidgetOptions(node, context, leafPageId)" in runtime_js
    assert "function selectorHasDependents(context, leafPageId, selectorId)" in runtime_js
    assert "selector.parent_selector_id !== selectorId" in runtime_js
    assert "pageState[selector.id] = dependentOptions[0]" in runtime_js


def test_runtime_asset_contains_sortable_export_table_helpers() -> None:
    runtime_js = load_export_runtime_js()

    assert "function parseSortableNumber(value)" in runtime_js
    assert "function compareCellValues(leftValue, rightValue)" in runtime_js
    assert "function toggleSort(column)" in runtime_js
    assert 'className: "export-table-sort"' in runtime_js
    assert 'className: "export-table-sort-indicator"' in runtime_js


def test_generated_export_html_contains_no_raw_nan_or_infinity(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  overview: {}",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    start_token = '<script id="activitysim-export-data" type="application/json">'
    start = html.index(start_token) + len(start_token)
    end = html.index("</script>", start)
    payload_json = html[start:end]

    assert "NaN" not in payload_json
    assert "Infinity" not in payload_json


def test_scoped_widget_values_restores_original_values_after_success() -> None:
    widgets = {
        "tour_purpose": pn.widgets.Select(
            name="Tour Purpose",
            options=["All", "eatout"],
            value="All",
        ),
        "tour_mode": pn.widgets.Select(
            name="Tour Mode",
            options=["Drive", "Walk"],
            value="Drive",
        ),
    }

    with scoped_widget_values(
        widgets,
        {"tour_purpose": "eatout", "tour_mode": "Walk"},
    ):
        assert widgets["tour_purpose"].value == "eatout"
        assert widgets["tour_mode"].value == "Walk"

    assert widgets["tour_purpose"].value == "All"
    assert widgets["tour_mode"].value == "Drive"


def test_scoped_widget_values_restores_original_values_after_exception() -> None:
    widgets = {
        "tour_purpose": pn.widgets.Select(
            name="Tour Purpose",
            options=["All", "eatout"],
            value="All",
        ),
        "missing_safe": None,
    }

    with pytest.raises(RuntimeError, match="boom"):
        with scoped_widget_values(
            widgets,
            {"tour_purpose": "eatout", "missing_safe": "ignored"},
        ):
            assert widgets["tour_purpose"].value == "eatout"
            raise RuntimeError("boom")

    assert widgets["tour_purpose"].value == "All"


def _selector_meta(
    values: list[str],
    *,
    default_value: str,
    request_mode: str = "all",
) -> dict:
    return {
        "id": "selector",
        "label": "Selector",
        "available": True,
        "request_mode": request_mode,
        "requested_values": [],
        "resolved_values": values,
        "default_value": default_value,
        "options": values,
        "export_enabled": len(values) > 1,
    }


class _ExportPartProbe:
    part_id = "probe_region"


def test_checkbox_selector_exports_string_options_and_sets_boolean_values() -> None:
    checkbox = pn.widgets.Checkbox(name="Include Totals", value=False)

    assert _selector_options(checkbox) == ["False", "True"]
    node = serialize_viewable(
        checkbox,
        disable_widgets=False,
        widget_metadata={
            id(checkbox): (
                "include_totals",
                {
                    "label": "Include Totals",
                    "export_enabled": True,
                    "resolved_values": ["False", "True"],
                },
            )
        },
    )
    assert node["widget_type"] == "checkbox"
    assert node["value"] == "False"
    assert node["options"] == ["False", "True"]
    assert node["selector_id"] == "include_totals"
    assert node["export_enabled"] is True
    with scoped_widget_values({"include_totals": checkbox}, {"include_totals": "True"}):
        assert checkbox.value is True

    assert checkbox.value is False


def test_export_section_state_resolver_discovers_dependent_child_options() -> None:
    class ProbePage:
        def __init__(self) -> None:
            self.parent = pn.widgets.Select(options=["A", "B"], value="A")
            self.child = pn.widgets.Select(options=["a1", "a2"], value="a1")

        def sync_controls(self) -> None:
            self.child.options = (
                ["a1", "a2"] if self.parent.value == "A" else ["b1"]
            )
            if self.child.value not in self.child.options:
                self.child.value = self.child.options[0]

    page = ProbePage()

    states, aliases = resolve_export_section_states(
        page,
        page_def=DashboardPageDefinition(page_id="probe", title="Probe"),
        part_def=_ExportPartProbe(),
        active_selector_ids=["parent", "child"],
        selector_widgets={"parent": page.parent, "child": page.child},
        selector_metadata_by_id={
            "parent": _selector_meta(["A", "B"], default_value="A"),
            "child": _selector_meta(["a1", "a2"], default_value="a1"),
        },
    )

    assert states == [
        {"parent": "A", "child": "a1"},
        {"parent": "A", "child": "a2"},
        {"parent": "B", "child": "b1"},
    ]
    assert aliases == {}


def test_export_section_state_resolver_collapses_disabled_selector_values() -> None:
    class ProbePage:
        def __init__(self) -> None:
            self.mode = pn.widgets.Select(options=["By Segment", "Filtered"], value="By Segment")
            self.segment = pn.widgets.Select(options=["All", "Low", "High"], value="All")

        def sync_controls(self) -> None:
            self.segment.disabled = self.mode.value == "By Segment"
            if self.segment.disabled:
                self.segment.value = "All"

    page = ProbePage()

    states, aliases = resolve_export_section_states(
        page,
        page_def=DashboardPageDefinition(page_id="probe", title="Probe"),
        part_def=_ExportPartProbe(),
        active_selector_ids=["mode", "segment"],
        selector_widgets={"mode": page.mode, "segment": page.segment},
        selector_metadata_by_id={
            "mode": _selector_meta(["By Segment", "Filtered"], default_value="By Segment"),
            "segment": _selector_meta(["All", "Low", "High"], default_value="All"),
        },
    )

    assert states == [
        {"mode": "By Segment", "segment": "All"},
        {"mode": "Filtered", "segment": "All"},
        {"mode": "Filtered", "segment": "Low"},
        {"mode": "Filtered", "segment": "High"},
    ]
    assert aliases['["By Segment","Low"]'] == '["By Segment","All"]'
    assert aliases['["By Segment","High"]'] == '["By Segment","All"]'


def test_export_section_state_resolver_aliases_canonical_mapped_values() -> None:
    class ProbePage:
        def __init__(self) -> None:
            self.parent = pn.widgets.Select(options=["A", "B"], value="A")
            self.child = pn.widgets.Select(options=["All", "a1", "b1"], value="All")

        def sync_controls(self) -> None:
            self.child.options = ["All", "a1", "b1"]

        def export_canonical_selector_value(
            self,
            section_id: str,
            selector_id: str,
            value: str,
            selected_values: dict[str, str],
        ) -> str:
            if selector_id != "child":
                return value
            valid_by_parent = {"A": {"All", "a1"}, "B": {"All", "b1"}}
            if value in valid_by_parent[selected_values["parent"]]:
                return value
            return "All"

    page = ProbePage()

    states, aliases = resolve_export_section_states(
        page,
        page_def=DashboardPageDefinition(page_id="probe", title="Probe"),
        part_def=_ExportPartProbe(),
        active_selector_ids=["parent", "child"],
        selector_widgets={"parent": page.parent, "child": page.child},
        selector_metadata_by_id={
            "parent": _selector_meta(["A", "B"], default_value="A"),
            "child": _selector_meta(["All", "a1", "b1"], default_value="All"),
        },
    )

    assert states == [
        {"parent": "A", "child": "All"},
        {"parent": "A", "child": "a1"},
        {"parent": "B", "child": "All"},
        {"parent": "B", "child": "b1"},
    ]
    assert aliases == {
        '["A","b1"]': '["A","All"]',
        '["B","a1"]': '["B","All"]',
    }
