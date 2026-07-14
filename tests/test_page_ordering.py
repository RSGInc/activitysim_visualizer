from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dashboard_expectations import EXPECTED_DEFAULT_LEAF_PAGE_IDS
from dashboard.page_registry import (
    resolve_export_page_definitions,
    resolve_live_page_definitions,
)
from test_export_html import _write_config


def test_live_and_export_page_resolution_share_default_order(tmp_path: Path) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)

    live_pages = resolve_live_page_definitions(config)
    export_pages = resolve_export_page_definitions(config)

    assert [page.page_id for page in live_pages] == EXPECTED_DEFAULT_LEAF_PAGE_IDS
    assert [page.page_id for page in export_pages] == EXPECTED_DEFAULT_LEAF_PAGE_IDS


def test_export_page_order_keeps_live_order_for_selected_export_pages(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview", "trip_summaries"],
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose: all",
            "  overview: {}",
        ],
    )

    live_pages = resolve_live_page_definitions(config)
    export_pages = resolve_export_page_definitions(config)

    assert [page.page_id for page in live_pages] == [
        "overview",
        "trip_stop_purpose",
        "trip_mode",
        "trip_stop_time",
        "trip_stop_distance",
    ]
    assert [page.page_id for page in export_pages] == ["overview", "trip_mode"]


def test_export_page_order_inherits_live_page_order_when_export_pages_are_unset(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["trip_summaries", "overview"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
        ],
    )

    export_pages = resolve_export_page_definitions(config)

    assert [page.page_id for page in export_pages] == [
        "trip_stop_purpose",
        "trip_mode",
        "trip_stop_time",
        "trip_stop_distance",
        "overview",
    ]


def test_export_pages_select_a_subset_without_changing_live_pages(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview", "trip_summaries"],
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode: {}",
        ],
    )

    assert [page.page_id for page in resolve_live_page_definitions(config)] == [
        "overview",
        "trip_stop_purpose",
        "trip_mode",
        "trip_stop_time",
        "trip_stop_distance",
    ]
    assert [page.page_id for page in resolve_export_page_definitions(config)] == [
        "trip_mode"
    ]
