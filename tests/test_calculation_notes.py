from __future__ import annotations

import ast
from pathlib import Path

import panel as pn

from dashboard.calculation_notes import (
    CalculationNote,
    calculation_note,
    get_calculation_note,
    load_calculation_notes,
    render_calculation_note_html,
)
from dashboard.export.serializer import serialize_viewable
from dashboard.page_base import DashboardPage, RegisteredPageSection


def test_calculation_note_registry_covers_every_registered_page_section() -> None:
    notes = load_calculation_notes()
    page_root = Path("dashboard/pages")
    referenced_note_ids: list[str] = []
    section_count = 0
    note_call_count = 0

    for page_path in page_root.rglob("*.py"):
        tree = ast.parse(page_path.read_text(encoding="utf-8"), filename=str(page_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else None
            )
            if function_name == "section":
                section_count += 1
            if function_name not in {"noted_section", "section_note"}:
                continue
            note_call_count += 1
            assert node.args and isinstance(node.args[0], ast.Constant), page_path
            referenced_note_ids.append(str(node.args[0].value))

    assert section_count == note_call_count == 53
    assert len(referenced_note_ids) == len(set(referenced_note_ids))
    assert set(notes) == set(referenced_note_ids)
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
    )

    rendered = render_calculation_note_html(note)

    assert rendered.startswith(
        "<div class='calculation-note-block' data-calculation-note-id='test.note'>"
    )
    assert "<p class='calculation-note-summary'>Uses A &amp; B.</p>" in rendered
    assert "How &lt;this&gt; works" in rendered
    assert "<code>A &lt; B</code>" in rendered
    assert "One &lt;record&gt;" in rendered
    assert rendered.endswith("</details></div>")


def test_calculation_note_is_collapsed_html_pane_exported_without_conversion() -> None:
    pane = calculation_note("traffic.link_volume")

    assert isinstance(pane, pn.pane.HTML)
    assert "data-calculation-note-id='traffic.link_volume'" in pane.object
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

    assert wrapper.objects[1] is visualization
    assert wrapper._calculation_note_id == "overview.demographics"
    assert wrapper._calculation_note_section_id == "test_section"
    assert wrapper.objects[0]._calculation_note_target_id == id(visualization)


def test_export_hides_note_wrapper_when_its_visualization_part_is_disabled() -> None:
    visualization = pn.Column(pn.pane.Markdown("A plot or table"))
    note_wrapper = pn.Column(
        calculation_note("overview.demographics"),
        visualization,
        css_classes=["calculation-note-section"],
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
    page = pn.Column(note, visualization, pn.pane.Markdown("Still visible"))

    payload = serialize_viewable(
        page,
        disable_widgets=False,
        hidden_view_ids={id(visualization)},
    )

    assert payload["child_count"] == 1
    assert payload["children"] == [{"kind": "html", "html": "<p>Still visible</p>"}]
