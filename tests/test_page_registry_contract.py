from __future__ import annotations

from pathlib import Path
import sys

import panel as pn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard import DashboardState
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.export.protocols import validate_export_page
from dashboard.export.traversal import resolve_page_parts
from dashboard.page_registry import (
    all_page_definitions,
    build_registered_live_pages,
    build_registered_export_pages,
    page_definition_by_id,
)
from dashboard.pages.daily_travel._escorted_tours.contracts import (
    CORE_SUMMARY_IDS,
    OPTIONAL_SUMMARY_IDS,
)
from processor.summarize.cache_types import create_summary_run
from _dashboard_expectations import EXPECTED_DEFAULT_LEAF_PAGE_IDS
from test_export_html import _full_summary_run, _write_config


def _walk(viewable):
    yield viewable
    for child in getattr(viewable, "objects", []):
        yield from _walk(child)


def _assert_sections_render_outcomes(page, *, allow_no_runs: bool = False) -> None:
    for section in page.registered_sections:
        context = f"{page.page_id()}.{section.section_id}"
        nodes = list(_walk(section.container))
        cards = [node for node in nodes if isinstance(node, pn.Card)]
        plots = [node for node in nodes if isinstance(node, pn.pane.Plotly)]
        tables = [node for node in nodes if isinstance(node, pn.widgets.Tabulator)]
        no_run_messages = [
            node
            for node in nodes
            if isinstance(node, pn.pane.Markdown)
            and str(node.object) == "No runs loaded."
        ]
        assert cards or plots or tables or (allow_no_runs and no_run_messages), context
        assert all(plot.object.data for plot in plots), context
        assert all(tabs.objects for tabs in nodes if isinstance(tabs, pn.Tabs)), context


def _state_for_run(run, config) -> DashboardState:
    return DashboardState(
        summary_runs=[run],
        weighting_modes=config.weighting_modes,
        prepared_run_provider=DashboardPreparedRunProvider.unavailable(),
    )


def test_all_registered_export_pages_satisfy_export_protocol(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    pages = build_registered_export_pages(state, config)

    assert pages
    for page in pages:
        validate_export_page(page)


def test_registered_export_pages_expose_runtime_selectors_with_unique_ids(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )
    pages = build_registered_export_pages(state, config)

    assert pages
    assert any(page.registered_selectors for page in pages)
    for page in pages:
        selector_ids = [selector.selector_id for selector in page.registered_selectors]
        assert len(selector_ids) == len(set(selector_ids))


def test_all_registered_live_pages_build_views_and_runtime_contracts(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    pages = build_registered_live_pages(state, config)

    assert [page.page_id() for page in pages] == EXPECTED_DEFAULT_LEAF_PAGE_IDS
    for page in pages:
        assert page.view is not None
        selector_ids = [selector.selector_id for selector in page.registered_selectors]
        section_ids = [section.section_id for section in page.registered_sections]

        assert len(selector_ids) == len(set(selector_ids))
        assert len(section_ids) == len(set(section_ids))

        for section in page.registered_sections:
            assert page.section_view(section.section_id) is section.container
            assert set(section.selector_ids).issubset(selector_ids)

        page.refresh(force=True)


def test_representative_export_pages_keep_expected_runtime_sections(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )
    pages_by_id = {
        page.page_id(): page for page in build_registered_export_pages(state, config)
    }

    expected_sections = {
        "overview": [("overview_kpis", ()), ("overview_demographics", ())],
        "daily_activity_pattern": [("activity_pattern_body", ("person_type",))],
        "escorted_tours": [
            ("school_escort.body", ()),
            ("adult_escort.body", ()),
            ("direction.body", ("direction.value",)),
            ("distance.body", ("direction.value",)),
        ],
        "trip_mode": [("trip_summary_mode_body", ("tour_purpose", "hide_drive_alone"))],
        "mandatory_location_choice": [
            ("remote_work.body", ("geography_level", "geography")),
            ("distance.distribution", ("geography_level", "geography")),
            ("flows.body", ("geography_level", "geography")),
            ("geography_comparison.body", ("geography_level", "geography")),
        ],
    }

    for page_id, expected in expected_sections.items():
        page = pages_by_id[page_id]
        resolved_parts = resolve_page_parts(page, page_def=page.definition)

        assert [
            (part_def.part_id, tuple(part_def.selector_ids))
            for part_def, _ in resolved_parts
        ] == expected


def test_escorted_tours_declares_independent_addons_as_optional() -> None:
    definition = page_definition_by_id("escorted_tours")
    assert definition is not None
    assert definition.required_summary_ids == CORE_SUMMARY_IDS
    assert definition.optional_summary_ids == OPTIONAL_SUMMARY_IDS


def test_all_registered_page_sections_explain_no_run_sessions(tmp_path: Path) -> None:
    config = _write_config(tmp_path)

    for definition in all_page_definitions():
        state = DashboardState(
            summary_runs=[],
            weighting_modes=config.weighting_modes,
        )
        page = definition.page_cls(state, config)
        page.refresh(force=True)
        _assert_sections_render_outcomes(page, allow_no_runs=True)


def test_all_registered_page_selector_states_render_valid_outcomes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()

    for definition in all_page_definitions():
        page = definition.page_cls(_state_for_run(summary_run, config), config)
        page.refresh(force=True)
        _assert_sections_render_outcomes(page)

        for selector in page.registered_selectors:
            widget = selector.widget
            values = (
                [False, True]
                if isinstance(widget, pn.widgets.Checkbox)
                else list(getattr(widget, "options", []) or [])
            )
            for value in values:
                widget.value = value
                page.refresh(force=False)
                _assert_sections_render_outcomes(page)


def test_all_registered_pages_handle_each_missing_declared_summary(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    full_run = _full_summary_run()

    for definition in all_page_definitions():
        summary_ids = (
            *definition.required_summary_ids,
            *definition.optional_summary_ids,
        )
        for missing_summary_id in summary_ids:
            summaries_by_mode = {
                mode: {
                    summary_id: table
                    for summary_id, table in tables.items()
                    if summary_id != missing_summary_id
                }
                for mode, tables in full_run.summaries_by_mode.items()
            }
            summary_run = create_summary_run(
                label="Base",
                run_key="base",
                summaries_by_mode=summaries_by_mode,
                source_run_dir="C:/runs/base",
            )
            page = definition.page_cls(_state_for_run(summary_run, config), config)
            page.refresh(force=True)
            _assert_sections_render_outcomes(page)
