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

from _dashboard_expectations import (
    EXPECTED_DEFAULT_LEAF_PAGE_IDS,
    EXPECTED_DEFAULT_LEAF_PAGE_TITLES,
    EXPECTED_DEFAULT_PAGE_IDS,
    EXPECTED_DEFAULT_PAGE_TITLES,
)
from test_export_html import _full_summary_run, _write_config
from dashboard.app import build_dashboard
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages.skims import SkimSummariesPage
import dashboard.pages as dashboard_pages_package
from dashboard.page_registry import (
    all_page_definitions,
    data_requirements_for_pages,
    default_page_definitions,
    enabled_prepared_data_mode,
    page_definition_by_id,
    resolve_page_definitions,
)
from dashboard.state import DashboardState
from processor.models import RunData
from processor.summarize.cache import SUMMARY_SPEC_BY_ID


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

    assert [definition.page_id for definition in definitions] == EXPECTED_DEFAULT_LEAF_PAGE_IDS
    assert [definition.title for definition in definitions] == EXPECTED_DEFAULT_LEAF_PAGE_TITLES
    assert page_definition_by_id("daily_activity_pattern") is not None
    assert page_definition_by_id("daily_activity_pattern").title == "Daily Activity Pattern"
    assert page_definition_by_id("daily_activity_pattern").group_id == "daily_travel"
    assert not hasattr(page_definition_by_id("daily_activity_pattern"), "child_id")
    assert page_definition_by_id("trip_mode").page_cls is not None
    assert page_definition_by_id("raw_trip_demo") is not None
    assert page_definition_by_id("raw_trip_demo").default_enabled is False
    assert page_definition_by_id("raw_trip_demo").title == "Prepared Trip Demo"
    assert page_definition_by_id("raw_trip_demo").prepared_data_mode == "required"
    assert page_definition_by_id("raw_trip_demo").required_prepared_tables == ("trips",)


def test_discovered_page_modules_export_page_definitions_without_legacy_build_api() -> None:
    discovered_modules = []
    for module_info in pkgutil.iter_modules(dashboard_pages_package.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{dashboard_pages_package.__name__}.{module_info.name}")
        discovered_modules.append(module)
        if module_info.ispkg:
            discovered_modules.extend(
                importlib.import_module(f"{module.__name__}.{child_info.name}")
                for child_info in pkgutil.iter_modules(module.__path__)
                if not child_info.name.startswith("_")
            )

    assert discovered_modules
    assert any(hasattr(module, "GROUP") for module in discovered_modules)
    assert all(
        isinstance(getattr(module, "PAGE", None), DashboardPageDefinition)
        or hasattr(module, "GROUP")
        for module in discovered_modules
    )
    assert all(not hasattr(module, "build") for module in discovered_modules)


def test_page_registry_smoke_checks_ids_titles_and_selector_uniqueness() -> None:
    definitions = all_page_definitions()

    assert all(definition.page_id for definition in definitions)
    assert all(definition.title for definition in definitions)
    assert len({definition.page_id for definition in definitions}) == len(definitions)
    assert all(definition.page_cls is not None for definition in definitions)

    for definition in definitions:
        selector_ids = [selector.selector_id for selector in definition.selectors]
        assert len(selector_ids) == len(set(selector_ids))
        assert definition.prepared_data_mode in {"none", "optional", "required"}
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

    assert [page.title for page in resolved_pages] == EXPECTED_DEFAULT_LEAF_PAGE_TITLES


def test_resolve_page_definitions_respects_configured_page_order_and_subset(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["trip_mode", "overview", "joint_travel"],
    )

    resolved_pages = resolve_page_definitions(config)

    assert [page.page_id for page in resolved_pages] == [
        "trip_mode",
        "overview",
        "joint_travel",
    ]


def test_resolve_page_definitions_supports_nested_group_child_selection(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=[
            "overview",
            {"tour_summaries": ["tour_purpose", "tour_mode"]},
            "joint_travel",
        ],
    )

    resolved_pages = resolve_page_definitions(config)

    assert [page.page_id for page in resolved_pages] == [
        "overview",
        "tour_purpose",
        "tour_mode",
        "joint_travel",
    ]


def test_enabled_prepared_data_mode_only_flips_on_for_pages_that_request_it(
    tmp_path: Path,
) -> None:
    summary_only_config = _write_config(tmp_path / "summary_only")
    raw_demo_config = _write_config(
        tmp_path / "raw_demo",
        dashboard_pages=["overview", "raw_trip_demo"],
    )

    assert enabled_prepared_data_mode(summary_only_config) == "none"
    assert enabled_prepared_data_mode(raw_demo_config) == "required"


def test_data_requirements_for_pages_aggregates_summary_and_prepared_dependencies() -> None:
    overview = page_definition_by_id("overview")
    raw_trip_demo = page_definition_by_id("raw_trip_demo")

    requirements = data_requirements_for_pages([overview, raw_trip_demo])

    assert requirements.prepared_data_mode == "required"
    assert requirements.required_prepared_tables == ("trips",)
    assert requirements.required_summary_ids == overview.required_summary_ids


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
    assert [page.page_id() for page in template._dashboard_leaf_pages] == EXPECTED_DEFAULT_LEAF_PAGE_IDS


def test_build_dashboard_sidebar_uses_shared_run_legend_markup(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    legend_item = template.sidebar[1]

    assert isinstance(legend_item, pn.pane.HTML)
    assert 'class="run-legend-item"' in legend_item.object
    assert 'data-run-label="Base"' in legend_item.object
    assert 'data-run-color="#1f77b4"' in legend_item.object


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
    assert state.page_state["Overview"]["last_rendered_state"] == (
        state.weighting_key(),
        state.value_key(),
    )

    leaf_pages = {page.page_id(): page for page in template._dashboard_leaf_pages}
    assert [
        selector.selector_id
        for selector in leaf_pages["trip_stop_distance"].registered_selectors
    ] == [
        "tour_purpose",
    ]
    assert leaf_pages["daily_activity_pattern"].person_type_sel.options == [
        "Total",
        "worker",
    ]
    assert leaf_pages["joint_travel"].hhsize_sel.options == ["All", "2", "3"]
    assert leaf_pages["tour_time"].purpose_sel.options == ["Total", "work"]
    assert leaf_pages["tour_mode"].purpose_sel.options == ["Total", "work"]
    assert leaf_pages["tour_stop_frequency"].purpose_sel.options == [
        "All",
        "eatout",
        "social",
    ]
    assert leaf_pages["trip_stop_time"].tour_purpose_sel.options == [
        "Total",
        "eatout",
        "social",
    ]
    assert leaf_pages["trip_mode"].tour_purpose_sel.options == ["All", "eatout", "social"]


def test_build_dashboard_keeps_prepared_runs_out_of_summary_only_default_state(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard(
        [("Base", _raw_trip_run())],
        config,
        summary_runs=[_full_summary_run()],
    )

    assert template._dashboard_state.prepared_run_availability == "not_requested"
    assert template._dashboard_state.get_prepared_runs_if_loaded(weighted=True) is None


def test_build_dashboard_loads_prepared_runs_when_demo_page_is_enabled(tmp_path: Path) -> None:
    config = _write_config(tmp_path, dashboard_pages=["raw_trip_demo"])
    template = build_dashboard([("Base", _raw_trip_run())], config)
    page = template._dashboard_pages[0]

    assert [page.page_id() for page in template._dashboard_pages] == ["raw_trip_demo"]
    assert template._dashboard_state.prepared_run_availability == "loaded"
    assert any(isinstance(obj, pn.pane.Plotly) for obj in page.view.objects)


def test_build_dashboard_shows_unavailable_card_when_demo_page_has_no_prepared_runs(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=["raw_trip_demo"])
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    page = template._dashboard_pages[0]

    assert template._dashboard_state.prepared_run_availability == "unavailable"
    assert any(getattr(obj, "title", "") == "Data Not Available" for obj in page.view.objects)


def test_dashboard_state_exposes_summary_first_accessors(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    totals = state.get_summary_table_set("population_totals", "weighted")

    assert totals is not None
    assert state.has_summary_table_set("population_totals", "weighted") is True
    assert state.has_summary_table_set("missing_summary", "weighted") is False
    assert totals[0][0] == "Base"
    assert totals[0][1]["person_count"][0] == 100.0
    assert state.get_prepared_runs_if_loaded(weighted=True) is None
    assert state.prepared_run_availability == "not_requested"


def test_dashboard_state_prepared_run_provider_supports_loaded_and_unavailable_modes(
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
        prepared_run_provider=DashboardPreparedRunProvider.loaded([("Base", raw_run)]),
    )
    unavailable_state = DashboardState(
        weighting_modes=config.weighting_modes,
        prepared_run_provider=DashboardPreparedRunProvider.unavailable(),
    )

    weighted_runs = loaded_state.get_prepared_runs_if_loaded(weighted=True)
    unweighted_runs = loaded_state.get_prepared_runs_if_loaded(weighted=False)

    assert loaded_state.prepared_run_availability == "loaded"
    assert weighted_runs is not None
    assert weighted_runs[0][0] == "Base"
    assert weighted_runs[0][1].hh["finalweight"][0] == 2.0
    assert unweighted_runs is not None
    assert unweighted_runs[0][1].hh["finalweight"][0] == 1.0
    assert unavailable_state.prepared_run_availability == "unavailable"
    assert unavailable_state.get_prepared_runs_if_loaded(weighted=True) is None


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
    assert state.page_state["Daily Activity Pattern"].get("last_rendered_state") is None

    tabs.active = 1

    assert state.active_tab == 1
    assert state.page_state["Overview"]["last_rendered_state"] == ("weighted", "percent")
    assert state.page_state["Daily Activity Pattern"]["last_rendered_state"] == (
        "weighted",
        "percent",
    )
    assert state.page_state["Tour Purpose"].get("last_rendered_state") is None

    state.weight_mode = "Unweighted"

    assert state.page_state["Overview"]["last_rendered_state"] is None
    assert state.page_state["Daily Activity Pattern"]["last_rendered_state"] == (
        "unweighted",
        "percent",
    )
    assert state.page_state["Tour Purpose"].get("last_rendered_state") is None

    state.value_mode = "Count"

    assert state.page_state["Daily Activity Pattern"]["last_rendered_state"] == (
        "unweighted",
        "count",
    )
    assert state.page_state["Overview"].get("last_rendered_state") is None
    assert state.page_state["Mandatory Location Choice"].get("last_rendered_state") is None
    assert state.page_state["Tour Purpose"].get("last_rendered_state") is None


def test_build_dashboard_preserves_widget_state_across_tab_switches(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    tabs = template.main[0]
    daily_activity_pattern_page = next(
        page
        for page in template._dashboard_leaf_pages
        if page.page_id() == "daily_activity_pattern"
    )

    tabs.active = 1
    assert daily_activity_pattern_page.person_type_sel.options == ["Total", "worker"]

    daily_activity_pattern_page.person_type_sel.value = "worker"
    tabs.active = 0
    tabs.active = 1

    assert daily_activity_pattern_page.person_type_sel.value == "worker"


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


def test_skims_page_renders_component_selector_and_independent_sections(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()
    skim_summary_run = type(summary_run)(
        label=summary_run.label,
        run_key=summary_run.run_key,
        summaries_by_mode={
            "weighted": {
                **summary_run.summaries_by_mode["weighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(
                    {
                        "trip_mode": ["DRIVE", "WALK"],
                        "component": ["skim_time", "skim_time"],
                        "n_total": [6.0, 2.0],
                        "n_valid": [3.0, 2.0],
                        "mean": [6.67, 5.0],
                        "std": [4.71, 0.0],
                        "min": [0.0, 5.0],
                        "max": [10.0, 5.0],
                        "median": [10.0, 5.0],
                        "mode": [10.0, 5.0],
                        "zero_share": [0.33, 0.0],
                        "missing_share": [0.5, 0.0],
                    }
                ),
                "skimjoin_trip_component_ecdf": pl.DataFrame(
                    {
                        "trip_mode": ["DRIVE", "DRIVE", "WALK", "WALK"],
                        "component": ["skim_time", "skim_time", "skim_time", "skim_time"],
                        "percentile": [0.0, 1.0, 0.0, 1.0],
                        "value": [0.0, 10.0, 5.0, 5.0],
                        "n_valid": [3.0, 3.0, 2.0, 2.0],
                    }
                ),
                "skimjoin_tour_component_stats": pl.DataFrame(
                    {
                        "tour_mode": ["DRIVE", "WALK"],
                        "component": ["skim_time", "skim_time"],
                        "n_total": [6.0, 2.0],
                        "n_valid": [3.0, 2.0],
                        "mean": [6.67, 5.0],
                        "std": [4.71, 0.0],
                        "min": [0.0, 5.0],
                        "max": [10.0, 5.0],
                        "median": [10.0, 5.0],
                        "mode": [10.0, 5.0],
                        "zero_share": [0.33, 0.0],
                        "missing_share": [0.5, 0.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": ["DRIVE", "DRIVE", "WALK", "WALK"],
                        "component": ["skim_time", "skim_time", "skim_time", "skim_time"],
                        "percentile": [0.0, 1.0, 0.0, 1.0],
                        "value": [0.0, 10.0, 5.0, 5.0],
                        "n_valid": [3.0, 3.0, 2.0, 2.0],
                    }
                ),
            },
            "unweighted": {
                **summary_run.summaries_by_mode["unweighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(
                    {
                        "trip_mode": ["DRIVE"],
                        "component": ["skim_time"],
                        "n_total": [3.0],
                        "n_valid": [2.0],
                        "mean": [5.0],
                        "std": [5.0],
                        "min": [0.0],
                        "max": [10.0],
                        "median": [0.0],
                        "mode": [0.0],
                        "zero_share": [0.5],
                        "missing_share": [1.0 / 3.0],
                    }
                ),
                "skimjoin_trip_component_ecdf": pl.DataFrame(
                    {
                        "trip_mode": ["DRIVE", "DRIVE"],
                        "component": ["skim_time", "skim_time"],
                        "percentile": [0.0, 1.0],
                        "value": [0.0, 10.0],
                        "n_valid": [2.0, 2.0],
                    }
                ),
                "skimjoin_tour_component_stats": pl.DataFrame(
                    {
                        "tour_mode": ["DRIVE"],
                        "component": ["skim_time"],
                        "n_total": [3.0],
                        "n_valid": [2.0],
                        "mean": [5.0],
                        "std": [5.0],
                        "min": [0.0],
                        "max": [10.0],
                        "median": [0.0],
                        "mode": [0.0],
                        "zero_share": [0.5],
                        "missing_share": [1.0 / 3.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": ["DRIVE", "DRIVE"],
                        "component": ["skim_time", "skim_time"],
                        "percentile": [0.0, 1.0],
                        "value": [0.0, 10.0],
                        "n_valid": [2.0, 2.0],
                    }
                ),
            },
        },
        source_run_dir=summary_run.source_run_dir,
        manifest=summary_run.manifest,
    )
    state = DashboardState(
        summary_runs=[skim_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = SkimSummariesPage(state, config)
    page.refresh(force=True)

    assert page.component_sel.options == ["skim_time"]
    assert list(page.trip_mode_sel.options) == ["DRIVE", "WALK"]
    assert list(page.tour_mode_sel.options) == ["DRIVE", "WALK"]
    assert len(page._trip_section.objects) == 3
    assert len(page._trip_distribution_section.objects) == 2
    assert len(page._tour_section.objects) == 3
    assert len(page._tour_distribution_section.objects) == 2

    page.trip_mode_sel.value = "WALK"
    assert len(page._trip_section.objects) == 3
    assert len(page._trip_distribution_section.objects) == 2
    assert len(page._tour_section.objects) == 3
    assert len(page._tour_distribution_section.objects) == 2


def test_skims_page_mode_selectors_exclude_component_modes_with_no_valid_observations(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()
    skim_summary_run = type(summary_run)(
        label=summary_run.label,
        run_key=summary_run.run_key,
        summaries_by_mode={
            "weighted": {
                **summary_run.summaries_by_mode["weighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(
                    {
                        "trip_mode": ["SOV", "WALK", "HOV2"],
                        "component": [
                            "skim_auto_time",
                            "skim_auto_time",
                            "skim_walk_distance",
                        ],
                        "n_total": [10.0, 5.0, 3.0],
                        "n_valid": [10.0, 0.0, 3.0],
                        "mean": [12.0, None, 1.5],
                        "std": [2.0, None, 0.2],
                        "min": [8.0, None, 1.2],
                        "max": [16.0, None, 1.8],
                        "median": [12.0, None, 1.5],
                        "mode": [12.0, None, 1.2],
                        "zero_share": [0.0, None, 0.0],
                        "missing_share": [0.0, 1.0, 0.0],
                    }
                ),
                "skimjoin_trip_component_ecdf": pl.DataFrame(
                    {
                        "trip_mode": ["SOV", "SOV", "HOV2", "HOV2"],
                        "component": [
                            "skim_auto_time",
                            "skim_auto_time",
                            "skim_walk_distance",
                            "skim_walk_distance",
                        ],
                        "percentile": [0.0, 1.0, 0.0, 1.0],
                        "value": [8.0, 16.0, 1.2, 1.8],
                        "n_valid": [10.0, 10.0, 3.0, 3.0],
                    }
                ),
                "skimjoin_tour_component_stats": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "WALK", "HOV2"],
                        "component": [
                            "skim_auto_time",
                            "skim_auto_time",
                            "skim_walk_distance",
                        ],
                        "n_total": [10.0, 5.0, 3.0],
                        "n_valid": [10.0, 0.0, 3.0],
                        "mean": [12.0, None, 1.5],
                        "std": [2.0, None, 0.2],
                        "min": [8.0, None, 1.2],
                        "max": [16.0, None, 1.8],
                        "median": [12.0, None, 1.5],
                        "mode": [12.0, None, 1.2],
                        "zero_share": [0.0, None, 0.0],
                        "missing_share": [0.0, 1.0, 0.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "SOV", "HOV2", "HOV2"],
                        "component": [
                            "skim_auto_time",
                            "skim_auto_time",
                            "skim_walk_distance",
                            "skim_walk_distance",
                        ],
                        "percentile": [0.0, 1.0, 0.0, 1.0],
                        "value": [8.0, 16.0, 1.2, 1.8],
                        "n_valid": [10.0, 10.0, 3.0, 3.0],
                    }
                ),
            },
            "unweighted": {
                **summary_run.summaries_by_mode["unweighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(),
                "skimjoin_trip_component_ecdf": pl.DataFrame(),
                "skimjoin_tour_component_stats": pl.DataFrame(),
                "skimjoin_tour_component_ecdf": pl.DataFrame(),
            },
        },
        source_run_dir=summary_run.source_run_dir,
        manifest=summary_run.manifest,
    )
    state = DashboardState(
        summary_runs=[skim_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = SkimSummariesPage(state, config)
    page.refresh(force=True)

    assert page.component_sel.options == ["skim_auto_time", "skim_walk_distance"]
    assert list(page.trip_mode_sel.options) == ["SOV"]
    assert list(page.tour_mode_sel.options) == ["SOV"]

    page.component_sel.value = "skim_walk_distance"

    assert list(page.trip_mode_sel.options) == ["HOV2"]
    assert list(page.tour_mode_sel.options) == ["HOV2"]


def test_skims_page_renders_disaggregated_distribution_plots_when_prepared_runs_are_loaded(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()
    skim_summary_run = type(summary_run)(
        label=summary_run.label,
        run_key=summary_run.run_key,
        summaries_by_mode={
            "weighted": {
                **summary_run.summaries_by_mode["weighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(
                    {
                        "trip_mode": ["SOV"],
                        "component": ["skim_auto_time"],
                        "n_total": [100.0],
                        "n_valid": [100.0],
                        "mean": [13.88],
                        "std": [18.71],
                        "min": [10.0],
                        "max": [200.0],
                        "median": [12.0],
                        "mode": [10.0],
                        "zero_share": [0.0],
                        "missing_share": [0.0],
                    }
                ),
                "skimjoin_trip_component_ecdf": pl.DataFrame(
                    {
                        "trip_mode": ["SOV", "SOV", "SOV"],
                        "component": ["skim_auto_time", "skim_auto_time", "skim_auto_time"],
                        "percentile": [0.0, 0.99, 1.0],
                        "value": [10.0, 14.0, 200.0],
                        "n_valid": [100.0, 100.0, 100.0],
                    }
                ),
                "skimjoin_tour_component_stats": pl.DataFrame(
                    {
                        "tour_mode": ["SOV"],
                        "component": ["skim_auto_time"],
                        "n_total": [100.0],
                        "n_valid": [100.0],
                        "mean": [13.88],
                        "std": [18.71],
                        "min": [10.0],
                        "max": [200.0],
                        "median": [12.0],
                        "mode": [10.0],
                        "zero_share": [0.0],
                        "missing_share": [0.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "SOV", "SOV"],
                        "component": ["skim_auto_time", "skim_auto_time", "skim_auto_time"],
                        "percentile": [0.0, 0.99, 1.0],
                        "value": [10.0, 14.0, 200.0],
                        "n_valid": [100.0, 100.0, 100.0],
                    }
                ),
            },
            "unweighted": {
                **summary_run.summaries_by_mode["unweighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(),
                "skimjoin_trip_component_ecdf": pl.DataFrame(),
                "skimjoin_tour_component_stats": pl.DataFrame(),
                "skimjoin_tour_component_ecdf": pl.DataFrame(),
            },
        },
        source_run_dir=summary_run.source_run_dir,
        manifest=summary_run.manifest,
    )
    prepared_run = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_mode": ["SOV", "SOV", "SOV", "SOV"],
                "skim_auto_time": [10.0, 12.0, 14.0, 200.0],
                "finalweight": [33.0, 33.0, 33.0, 1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_mode": ["SOV", "SOV", "SOV", "SOV"],
                "skim_auto_time": [10.0, 12.0, 14.0, 200.0],
                "finalweight": [33.0, 33.0, 33.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )
    state = DashboardState(
        summary_runs=[skim_summary_run],
        weighting_modes=config.weighting_modes,
        prepared_run_provider=DashboardPreparedRunProvider.loaded(
            [("Base", prepared_run)]
        ),
    )

    page = SkimSummariesPage(state, config)
    page.refresh(force=True)

    assert isinstance(page._trip_distribution_section.objects[-1], pn.pane.Plotly)
    assert isinstance(page._tour_distribution_section.objects[-1], pn.pane.Plotly)
    assert tuple(page._trip_distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert tuple(page._tour_distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert page._trip_distribution_section.objects[-1].object.layout.title.text == "Trip Distribution - skim_auto_time / SOV"
    assert page._tour_distribution_section.objects[-1].object.layout.title.text == "Tour Distribution - skim_auto_time / SOV"

    page.trip_min_sel.value = 11.0
    page.trip_max_sel.value = 13.0
    page.tour_min_sel.value = 11.0
    page.tour_max_sel.value = 13.0

    assert tuple(page._trip_distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (11.0, 13.0)
    )
    assert tuple(page._tour_distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (11.0, 13.0)
    )

    page.trip_reset_btn.clicks = page.trip_reset_btn.clicks + 1
    page.tour_reset_btn.clicks = page.tour_reset_btn.clicks + 1

    assert tuple(page._trip_distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert tuple(page._tour_distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
