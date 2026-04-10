from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
import sys

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dashboard_expectations import EXPECTED_DEFAULT_PAGE_IDS, EXPECTED_DEFAULT_PAGE_TITLES
from test_export_html import _full_summary_run, _write_config
from dashboard.app import build_dashboard
from dashboard.data_access import DashboardRawRunProvider
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
import dashboard.pages as dashboard_pages_package
from dashboard.page_registry import (
    all_page_definitions,
    default_page_definitions,
    enabled_raw_data_mode,
    page_definition_by_id,
    resolve_page_definitions,
)
from dashboard.state import DashboardState
from runtime.models import RunData
from summarize.cache import SUMMARY_SPEC_BY_ID


def _raw_trip_run() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [2.0]}),
        per=pl.DataFrame({"person_id": [1], "household_id": [1], "finalweight": [3.0]}),
        tours=pl.DataFrame({"tour_id": [10], "finalweight": [4.0]}),
        trips=pl.DataFrame(
            {
                "trip_id": [100, 101, 102],
                "tour_id": [10, 10, 10],
                "trip_mode": ["DRIVEALONE", "WALK", "WALK"],
                "finalweight": [5.0, 2.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_page_registry_exposes_expected_default_definitions() -> None:
    definitions = default_page_definitions()

    assert [definition.page_id for definition in definitions] == EXPECTED_DEFAULT_PAGE_IDS
    assert [definition.title for definition in definitions] == EXPECTED_DEFAULT_PAGE_TITLES
    assert page_definition_by_id("tour_summary") is not None
    assert page_definition_by_id("tour_summary").title == "Tour Summary"
    assert [selector.selector_id for selector in page_definition_by_id("trip_mode").selectors] == [
        "tour_purpose",
        "tour_mode",
    ]
    assert page_definition_by_id("raw_trip_demo") is not None
    assert page_definition_by_id("raw_trip_demo").default_enabled is False
    assert page_definition_by_id("raw_trip_demo").raw_data_mode == "required"


def test_discovered_page_modules_export_page_definitions_without_legacy_build_api() -> None:
    discovered_modules = [
        importlib.import_module(f"{dashboard_pages_package.__name__}.{module_info.name}")
        for module_info in pkgutil.iter_modules(dashboard_pages_package.__path__)
        if not module_info.name.startswith("_")
    ]

    assert discovered_modules
    assert all(
        isinstance(getattr(module, "PAGE", None), DashboardPageDefinition)
        for module in discovered_modules
    )
    assert all(not hasattr(module, "build") for module in discovered_modules)


def test_page_registry_smoke_checks_ids_titles_and_selector_uniqueness() -> None:
    definitions = all_page_definitions()

    assert all(definition.page_id for definition in definitions)
    assert all(definition.title for definition in definitions)
    assert len({definition.page_id for definition in definitions}) == len(definitions)
    assert all(
        definition.required_summary_ids or definition.raw_data_mode != "none"
        for definition in definitions
    )

    for definition in definitions:
        selector_ids = [selector.selector_id for selector in definition.selectors]
        assert len(selector_ids) == len(set(selector_ids))
        assert definition.raw_data_mode in {"none", "optional", "required"}
        assert len(set(definition.required_summary_ids)) == len(
            definition.required_summary_ids
        )
        assert all(
            summary_id in SUMMARY_SPEC_BY_ID
            for summary_id in definition.required_summary_ids
        )


def test_resolve_page_definitions_defaults_to_default_pages_when_unconfigured(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)

    resolved_pages = resolve_page_definitions(config)

    assert [page.title for page in resolved_pages] == EXPECTED_DEFAULT_PAGE_TITLES


def test_resolve_page_definitions_respects_configured_page_order_and_subset(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["trip_mode", "overview", "destination"],
    )

    resolved_pages = resolve_page_definitions(config)

    assert [page.page_id for page in resolved_pages] == [
        "trip_mode",
        "overview",
        "destination",
    ]


def test_enabled_raw_data_mode_only_flips_on_for_pages_that_request_it(
    tmp_path: Path,
) -> None:
    summary_only_config = _write_config(tmp_path / "summary_only")
    raw_demo_config = _write_config(
        tmp_path / "raw_demo",
        dashboard_pages=["overview", "raw_trip_demo"],
    )

    assert enabled_raw_data_mode(summary_only_config) == "none"
    assert enabled_raw_data_mode(raw_demo_config) == "required"


def test_resolve_page_definitions_rejects_unknown_configured_page_ids(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=["overview", "unknown_page"])

    with pytest.raises(
        ValueError, match="Unsupported visualizer.dashboard_pages entries"
    ):
        resolve_page_definitions(config)


def test_resolve_page_definitions_rejects_duplicate_configured_page_ids(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="visualizer.dashboard_pages contains duplicate page id 'overview'",
    ):
        _write_config(tmp_path, dashboard_pages=["overview", "overview"])


def test_build_dashboard_uses_expected_default_page_order(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])

    assert [page.name for page in template._dashboard_pages] == EXPECTED_DEFAULT_PAGE_TITLES
    assert [page.page_id() for page in template._dashboard_pages] == EXPECTED_DEFAULT_PAGE_IDS


def test_build_dashboard_can_refresh_every_default_page_from_precomputed_summaries_only(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    tabs = template.main[0]
    pages = template._dashboard_pages
    state = template._dashboard_state

    for index, page in enumerate(pages):
        tabs.active = index
        assert page.view is not None
        assert state.page_state[page.name]["last_rendered_state"] == (
            state.weighting_key(),
            state.value_key(),
        )

    assert template._dashboard_pages[2].ptype_sel.options == ["Total", "worker"]
    assert template._dashboard_pages[3].hhsize_sel.options == ["Total", "2", "3", "4", "5"]
    assert template._dashboard_pages[4].purp_sel.options == ["All NM", "eatout", "social"]
    assert template._dashboard_pages[5].purp_sel.options == ["Total", "work"]
    assert template._dashboard_pages[6].purp_sel.options == ["Total", "work"]
    assert template._dashboard_pages[7].purp_sel.options == ["Total", "eatout", "social"]
    assert template._dashboard_pages[9].purp_sel.options == ["eatout", "social"]
    assert template._dashboard_pages[10].tmode_sel.options == ["All", "DRIVE", "WALK"]


def test_build_dashboard_keeps_raw_runs_out_of_summary_only_default_state(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard(
        [("Base", _raw_trip_run())],
        config,
        summary_runs=[_full_summary_run()],
    )

    assert template._dashboard_state.raw_run_availability == "not_requested"
    assert template._dashboard_state.get_raw_runs_if_loaded(weighted=True) is None


def test_build_dashboard_loads_raw_runs_when_demo_page_is_enabled(tmp_path: Path) -> None:
    config = _write_config(tmp_path, dashboard_pages=["raw_trip_demo"])
    template = build_dashboard([("Base", _raw_trip_run())], config)
    page = template._dashboard_pages[0]

    assert [page.page_id() for page in template._dashboard_pages] == ["raw_trip_demo"]
    assert template._dashboard_state.raw_run_availability == "loaded"
    assert any(isinstance(obj, pn.pane.Plotly) for obj in page.view.objects)


def test_build_dashboard_shows_unavailable_card_when_demo_page_has_no_raw_runs(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=["raw_trip_demo"])
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    page = template._dashboard_pages[0]

    assert template._dashboard_state.raw_run_availability == "unavailable"
    assert any(getattr(obj, "title", "") == "Data Not Available" for obj in page.view.objects)


def test_dashboard_state_exposes_summary_first_accessors(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    totals = state.get_summary_table_set("totals", "weighted")

    assert totals is not None
    assert state.has_summary_table_set("totals", "weighted") is True
    assert state.has_summary_table_set("missing_summary", "weighted") is False
    assert totals[0][0] == "Base"
    assert totals[0][1]["population"][0] == 100.0
    assert state.get_raw_runs_if_loaded(weighted=True) is None
    assert state.raw_run_availability == "not_requested"


def test_dashboard_state_raw_run_provider_supports_loaded_and_unavailable_modes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw_run = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame({"finalweight": [2.0]}),
        per=pl.DataFrame({"finalweight": [3.0]}),
        tours=pl.DataFrame({"finalweight": [4.0]}),
        trips=pl.DataFrame({"finalweight": [5.0]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )
    loaded_state = DashboardState(
        weighting_modes=config.weighting_modes,
        raw_run_provider=DashboardRawRunProvider.loaded([("Base", raw_run)]),
    )
    unavailable_state = DashboardState(
        weighting_modes=config.weighting_modes,
        raw_run_provider=DashboardRawRunProvider.unavailable(),
    )

    weighted_runs = loaded_state.get_raw_runs_if_loaded(weighted=True)
    unweighted_runs = loaded_state.get_raw_runs_if_loaded(weighted=False)

    assert loaded_state.raw_run_availability == "loaded"
    assert weighted_runs is not None
    assert weighted_runs[0][0] == "Base"
    assert weighted_runs[0][1].hh["finalweight"][0] == 2.0
    assert unweighted_runs is not None
    assert unweighted_runs[0][1].hh["finalweight"][0] == 1.0
    assert unavailable_state.raw_run_availability == "unavailable"
    assert unavailable_state.get_raw_runs_if_loaded(weighted=True) is None


def test_build_dashboard_switches_tabs_and_refreshes_only_the_active_page(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    state = template._dashboard_state
    pages = template._dashboard_pages
    tabs = template.main[0]

    assert state.active_tab == 0
    assert state.page_state["Overview"]["last_rendered_state"] == ("weighted", "percent")
    assert state.page_state["Tour Summary"].get("last_rendered_state") is None

    tabs.active = 2

    assert state.active_tab == 2
    assert state.page_state["Overview"]["last_rendered_state"] == ("weighted", "percent")
    assert state.page_state["Tour Summary"]["last_rendered_state"] == (
        "weighted",
        "percent",
    )
    assert all(
        state.page_state[page.name].get("last_rendered_state") is None
        for page in pages[3:]
    )

    state.weight_mode = "Unweighted"

    assert state.page_state["Overview"]["last_rendered_state"] is None
    assert state.page_state["Tour Summary"]["last_rendered_state"] == (
        "unweighted",
        "percent",
    )
    assert all(
        state.page_state[page.name].get("last_rendered_state") is None
        for page in pages[3:]
    )

    state.value_mode = "Count"

    assert state.page_state["Tour Summary"]["last_rendered_state"] == (
        "unweighted",
        "count",
    )
    assert all(
        state.page_state[page.name].get("last_rendered_state") is None
        for page in [pages[0], pages[1], *pages[3:]]
    )


def test_build_dashboard_preserves_widget_state_across_tab_switches(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    tabs = template.main[0]
    tour_summary_page = template._dashboard_pages[2]

    tabs.active = 2
    assert tour_summary_page.ptype_sel.options == ["Total", "worker"]

    tour_summary_page.ptype_sel.value = "worker"
    tabs.active = 0
    tabs.active = 2

    assert tour_summary_page.ptype_sel.value == "worker"


def test_dashboard_page_cache_helpers_reuse_summary_and_filtered_view_results(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()
    probe_summary_run = type(summary_run)(
        label=summary_run.label,
        run_key=summary_run.run_key,
        summaries_by_mode={
            "weighted": {**summary_run.summaries_by_mode["weighted"], "probe_summary": pl.DataFrame({"value": ["summary"]})},
            "unweighted": {**summary_run.summaries_by_mode["unweighted"], "probe_summary": pl.DataFrame({"value": ["summary"]})},
        },
        source_run_dir=summary_run.source_run_dir,
        manifest=summary_run.manifest,
    )
    state = DashboardState(
        summary_runs=[probe_summary_run],
        weighting_modes=config.weighting_modes,
    )
    call_counts = {"filtered_view": 0}

    class CacheProbePage(DashboardPage):
        def __init__(self) -> None:
            super().__init__("Cache Probe", state, config)
            self.view = pn.Column()

        def _filtered_view_factory(self) -> dict[str, str]:
            call_counts["filtered_view"] += 1
            return {"kind": "filtered_view"}

        def _refresh(self) -> None:
            self.summary_value = self.require_summary("probe_summary")
            self.filtered_view_value = self.get_filtered_view(
                "probe_view",
                "default",
                factory=self._filtered_view_factory,
            )

    page = CacheProbePage()

    page.refresh(force=True)
    page.refresh(force=True)
    page.mark_stale()
    page.refresh_if_needed()

    assert call_counts == {"filtered_view": 1}
    assert page.summary_value[0][1]["value"][0] == "summary"
    assert page.filtered_view_value == {"kind": "filtered_view"}
    assert state.cache_stats["filtered_view"] == {"hits": 2, "misses": 1}
