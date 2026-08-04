from __future__ import annotations

import ast
from pathlib import Path
import sys

import panel as pn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.app import build_dashboard
from dashboard.calculation_notes import (
    CALCULATION_NOTE_STYLESHEET,
    CalculationNote,
    calculation_note,
    get_calculation_note,
    load_calculation_notes,
    render_calculation_note_html,
)
from dashboard.export.html import build_export_html_document
from dashboard.export.serializer import serialize_viewable
from dashboard.page_base import DashboardPage, RegisteredPageSection
from test_export_html import _full_summary_run, _write_config


def test_calculation_note_registry_covers_every_plot_and_table_note_reference() -> None:
    notes = load_calculation_notes()
    page_root = Path("dashboard/pages")
    referenced_note_ids: set[str] = set()
    note_call_count = 0

    for page_path in page_root.rglob("*.py"):
        tree = ast.parse(page_path.read_text(encoding="utf-8"), filename=str(page_path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in notes
            ):
                referenced_note_ids.add(node.value)
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else None
            )
            if function_name in {"noted_view", "noted_section", "section_note"}:
                note_call_count += 1

    assert note_call_count >= 80
    assert len(referenced_note_ids) >= 80
    for note_id in referenced_note_ids:
        note = notes[note_id]
        assert note.summary
        assert note.method_explanation
        assert note.method_text
        assert note.sources
    assert get_calculation_note("vmt.personal_auto").formula == (
        "trip distance × final trip weight ÷ vehicle occupancy"
    )


def test_calculation_note_renderer_escapes_configured_text() -> None:
    note = CalculationNote(
        note_id="test.note",
        label="How <this> works",
        summary="Uses A & B.",
        formula="A < B",
        details=(("Included", ("One <record>",)),),
        method_explanation="Generic grouping text that should stay internal.",
        method_text="Join <records> by their shared key.",
        sources=("source_one",),
        source_filters=("Only A & B.",),
    )

    rendered = render_calculation_note_html(note)

    assert rendered.startswith(
        "<div class='calculation-note-block' data-calculation-note-id='test.note'>"
    )
    assert "<p class='calculation-note-summary'>Uses A &amp; B.</p>" in rendered
    assert "How &lt;this&gt; works" in rendered
    assert "<code>A &lt; B</code>" in rendered
    assert "Join &lt;records&gt; by their shared key." in rendered
    assert "Generic grouping text" not in rendered
    assert "Only A &amp; B." in rendered
    assert "source_one" in rendered
    assert "Summary Tables Used:" in rendered
    assert "Prepared summaries used:" not in rendered
    assert "One &lt;record&gt;" not in rendered
    assert rendered.endswith("</details></div>")


def test_validation_notes_expose_comparison_and_error_formulas() -> None:
    regional = get_calculation_note("regional_validation.flows")
    facility = get_calculation_note("traffic.facility_summary")

    assert "difference = modeled - observed" in regional.formula
    assert (
        "RMSPE = sqrt(mean(((observed_i - modeled_i) / observed_i)^2)) * 100"
        in facility.formula
    )


def test_calculation_note_is_collapsed_html_pane_exported_without_conversion() -> None:
    pane = calculation_note("traffic.link_volume")

    assert isinstance(pane, pn.pane.HTML)
    assert "data-calculation-note-id='traffic.link_volume'" in pane.object
    assert "<summary>Notes</summary>" in pane.object
    assert " open" not in pane.object

    payload = serialize_viewable(pane, disable_widgets=False)
    assert payload["kind"] == "html"
    assert payload["html"] == pane.object
    assert "facility-type volume" in payload["html"]


def test_noted_section_associates_note_with_registered_visualization() -> None:
    page = DashboardPage.__new__(DashboardPage)
    page.name = "Test Page"
    visualization = pn.Column()
    page._registered_sections = {
        "test_section": RegisteredPageSection(
            section_id="test_section",
            container=visualization,
            selector_ids=(),
            export=True,
            export_data_mode="none",
            render=lambda: [],
        )
    }

    wrapper = page.noted_section("overview.demographics", visualization)

    assert wrapper.objects[0] is visualization
    assert wrapper._calculation_note_id == "overview.demographics"
    assert wrapper._calculation_note_section_id == "test_section"
    assert wrapper.objects[1]._calculation_note_target_id == id(visualization)


def test_noted_view_places_one_note_directly_below_one_visualization() -> None:
    page = DashboardPage.__new__(DashboardPage)
    visualization = pn.pane.Markdown("A plot or table")

    wrapper = page.noted_view("overview.person_type", visualization)

    assert wrapper.objects[0] is visualization
    assert wrapper._calculation_note_id == "overview.person_type"
    assert wrapper.objects[1]._calculation_note_target_id == id(visualization)


def test_all_built_dashboard_notes_follow_their_visualization(tmp_path: Path) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    visited: set[int] = set()

    def assert_note_order(container: pn.viewable.Viewable) -> None:
        if id(container) in visited:
            return
        visited.add(id(container))
        children = list(getattr(container, "objects", []) or [])
        positions = {id(child): index for index, child in enumerate(children)}
        for index, child in enumerate(children):
            target_id = getattr(child, "_calculation_note_target_id", None)
            if target_id == id(container):
                assert index == len(children) - 1
            elif target_id is not None:
                assert target_id in positions
                assert positions[target_id] < index
            if isinstance(child, pn.viewable.Viewable):
                assert_note_order(child)

    for page in template._dashboard_pages:
        assert_note_order(page.view)

    overview_page = next(
        page for page in template._dashboard_pages if page.page_id() == "overview"
    )
    kpi_wrapper, comparison_heading, comparison_wrapper = (
        overview_page._kpi_section.objects
    )
    assert kpi_wrapper._calculation_note_id == "overview.kpis"
    assert kpi_wrapper.objects[1]._calculation_note_target_id == id(
        kpi_wrapper.objects[0]
    )
    assert comparison_heading.object == "### Percent Difference vs Base Run"
    assert comparison_wrapper._calculation_note_id == "overview.percent_difference"


def test_note_summary_and_specific_method_are_both_inside_collapsible_control() -> None:
    rendered = render_calculation_note_html(get_calculation_note("overview.person_type"))

    assert "This plot sums person weights by person type." in rendered
    assert rendered.index("<details") < rendered.index("This plot sums person weights")
    assert rendered.index("This plot sums person weights") < rendered.index(
        "</details>"
    )
    assert "<summary>Notes</summary>" in rendered
    assert "<strong>Method:</strong>" in rendered
    assert ".calculation-note-summary" in CALCULATION_NOTE_STYLESHEET
    assert "color: inherit;" in CALCULATION_NOTE_STYLESHEET
    assert ".calculation-note-content .calculation-note-formula" in (
        CALCULATION_NOTE_STYLESHEET
    )
    assert "margin-top: 8px;" in CALCULATION_NOTE_STYLESHEET


def test_complex_note_uses_visualization_specific_method_text() -> None:
    rendered = render_calculation_note_html(get_calculation_note("vmt.personal_auto"))

    assert "<strong>Method:</strong>" in rendered
    assert "shared-ride passenger records" in rendered
    assert "calculates VMT at the trip or network-link level" not in rendered


def test_calculation_notes_can_be_disabled_for_page_views() -> None:
    page = DashboardPage.__new__(DashboardPage)
    page.config = type("Config", (), {"include_notes": False})()
    visualization = pn.pane.Markdown("A plot or table")

    assert page.noted_view("overview.person_type", visualization) is visualization


def test_include_notes_config_defaults_on_and_can_disable_export(
    tmp_path: Path,
) -> None:
    default_config = _write_config(tmp_path / "default", dashboard_pages=["overview"])
    disabled_config = _write_config(
        tmp_path / "disabled",
        dashboard_pages=["overview"],
        extra_lines=["dashboard:", "  include_notes: false"],
    )

    assert default_config.include_notes is True
    assert disabled_config.include_notes is False

    html = build_export_html_document(
        [], disabled_config, summary_runs=[_full_summary_run()]
    )
    assert "data-calculation-note-id" not in html


def test_export_hides_note_wrapper_when_its_visualization_part_is_disabled() -> None:
    visualization = pn.Column(pn.pane.Markdown("A plot or table"))
    note_wrapper = pn.Column(
        visualization,
        calculation_note("overview.demographics"),
        css_classes=["calculation-note-view"],
    )
    page = pn.Column(note_wrapper, pn.pane.Markdown("Still visible"))

    payload = serialize_viewable(
        page,
        disable_widgets=False,
        hidden_view_ids={id(visualization)},
    )

    assert payload["child_count"] == 1
    assert payload["children"] == [{"kind": "html", "html": "<p>Still visible</p>"}]


def test_export_hides_adjacent_note_when_its_visualization_part_is_disabled() -> None:
    visualization = pn.Column(pn.pane.Markdown("A plot or table"))
    note = calculation_note("trip_skims.summary_table")
    note._calculation_note_target_id = id(visualization)
    page = pn.Column(visualization, note, pn.pane.Markdown("Still visible"))

    payload = serialize_viewable(
        page,
        disable_widgets=False,
        hidden_view_ids={id(visualization)},
    )

    assert payload["child_count"] == 1
    assert payload["children"] == [{"kind": "html", "html": "<p>Still visible</p>"}]
