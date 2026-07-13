from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard import DashboardState
from dashboard.export.protocols import validate_export_page
from dashboard.export.traversal import resolve_page_parts
from dashboard.page_registry import (
    build_registered_live_pages,
    build_registered_export_pages,
)
from _dashboard_expectations import EXPECTED_DEFAULT_LEAF_PAGE_IDS
from test_export_html import _full_summary_run, _write_config


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
            ("escorted_tours_static_body", ()),
            ("escorted_tours_directional_body", ("direction",)),
        ],
        "trip_mode": [
            ("trip_summary_mode_body", ("tour_purpose", "hide_drive_alone"))
        ],
        "mandatory_location_choice": [
            ("remote_work", ("geography_level", "geography")),
            ("distance_distribution", ("geography_level", "geography")),
            ("worker_geography", ("geography_level", "geography")),
            ("mandatory_distance_table", ("geography_level", "geography")),
        ],
    }

    for page_id, expected in expected_sections.items():
        page = pages_by_id[page_id]
        resolved_parts = resolve_page_parts(page, page_def=page.definition)

        assert [
            (part_def.part_id, tuple(part_def.selector_ids))
            for part_def, _ in resolved_parts
        ] == expected
