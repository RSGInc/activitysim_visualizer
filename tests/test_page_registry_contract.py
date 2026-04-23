from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard import DashboardState
from dashboard.export_protocols import validate_export_page
from dashboard.page_registry import (
    all_page_definitions,
    build_registered_export_pages,
    exportable_page_selectors,
    selector_definition_by_id,
)
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


def test_selector_registry_lookups_cover_registered_exportable_selectors() -> None:
    exportable_selectors = exportable_page_selectors()

    assert exportable_selectors
    for page_definition, selector_definition in exportable_selectors:
        looked_up = selector_definition_by_id(
            page_definition.page_id,
            selector_definition.selector_id,
        )
        assert looked_up == selector_definition


def test_registered_pages_keep_selector_ids_unique_per_page() -> None:
    for definition in all_page_definitions():
        selector_ids = [selector.selector_id for selector in definition.selectors]
        assert len(selector_ids) == len(set(selector_ids))
