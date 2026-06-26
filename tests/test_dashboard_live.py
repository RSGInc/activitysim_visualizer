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
from dashboard.page_base import PAGE_SELECTOR_STYLESHEET
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages.skim_summaries.trip_skims import TripSkimsPage
from dashboard.pages.skim_summaries.tour_skims import TourSkimsPage
from dashboard.pages.trip_summaries.trip_mode import TripModePage
from dashboard.pages.validation.regional import (
    flow_heatmap,
    normalize_flow_matrix,
    wfh_rate_data,
)
from dashboard.pages.validation.traffic import (
    external_count_scatter_data,
    external_count_scatter_data_from_sources,
    external_count_fit_line_data,
    external_link_aggregate_data,
    external_volume_comparison_table,
)
from dashboard.pages.validation.vmt import (
    PERSONAL_AUTO_VMT_SUMMARY_ID,
    VMTValidationPage,
    personal_auto_vmt_chart_data,
    wide_tod_chart_data,
)
import dashboard.pages as dashboard_pages_package
from dashboard.page_registry import (
    _validate_page_definition,
    all_page_definitions,
    data_requirements_for_pages,
    default_page_definitions,
    enabled_prepared_data_mode,
    page_definition_by_id,
    resolve_page_definitions,
)
from dashboard.state import DashboardState
from processor.models import RunData
from processor.summarize.cache import SUMMARY_SPEC_BY_ID, create_summary_run


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
        assert len(set(definition.optional_summary_ids)) == len(
            definition.optional_summary_ids
        )
        assert all(
            summary_id in SUMMARY_SPEC_BY_ID
            for summary_id in definition.optional_summary_ids
        )


def test_page_registry_accepts_non_default_registered_summary_id() -> None:
    class ExternalAutoVmtDemoPage(DashboardPage):
        pass

    definition = DashboardPageDefinition(
        page_id="external_auto_vmt_demo",
        title="External Auto VMT Demo",
        page_cls=ExternalAutoVmtDemoPage,
        required_summary_ids=("external_auto_vmt_summary",),
        default_enabled=False,
    )

    _validate_page_definition(definition)
    requirements = data_requirements_for_pages([definition])

    assert requirements.required_summary_ids == ("external_auto_vmt_summary",)


def test_dashboard_state_reports_missing_non_default_summary_as_diagnostic() -> None:
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {"totals": pl.DataFrame({"population": [1.0]})},
            "unweighted": {"totals": pl.DataFrame({"population": [1.0]})},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=["weighted", "unweighted"],
    )

    selection = state.inspect_summary_table("external_auto_vmt_summary")

    assert selection.usable_runs == []
    assert [excluded.status for excluded in selection.excluded_runs] == ["missing"]
    assert selection.excluded_runs[0].source_id == "external_auto_vmt_summary"


def test_external_traffic_helpers_filter_period_and_facility_type() -> None:
    counts = [
        (
            "Run",
            pl.DataFrame(
                {
                    "id": [1, 2],
                    "FACTYPE": [3, 4],
                    "am_vol": [10.0, 20.0],
                    "day_vol": [100.0, 200.0],
                }
            ),
        )
    ]
    volumes = [
        (
            "Run",
            pl.DataFrame(
                {
                    "id": [1, 2],
                    "FACTYPE": [3, 4],
                    "am_vol": [11.0, 21.0],
                    "day_vol": [110.0, 210.0],
                }
            ),
        )
    ]
    links = [
        (
            "Run",
            pl.DataFrame(
                {
                    "id": [10, 11],
                    "From_Node": [100, 101],
                    "To_Node": [200, 201],
                    "FACTYPE": [3, 4],
                    "day_vol": [5.0, 15.0],
                }
            ),
        )
    ]

    scatter = external_count_scatter_data_from_sources(
        counts,
        volumes,
        volume_col="day_vol",
        facility_type="4",
    )
    aggregate = external_link_aggregate_data(
        links,
        volume_col="day_vol",
        facility_type="All",
    )

    assert scatter[0][1].to_dicts() == [
        {
            "id": 2,
            "facility_type": "4",
            "observed_volume": 200.0,
            "modeled_volume": 210.0,
        }
    ]
    assert aggregate[0][1].to_dicts() == [
        {"FACTYPE": "3", "volume": 5.0},
        {"FACTYPE": "4", "volume": 15.0},
    ]
    comparison = external_volume_comparison_table(
        counts,
        volumes,
        link_list=[
            (
                "Run",
                pl.DataFrame(
                    {
                        "id": [1, 2],
                        "From_Node": [100, 101],
                        "To_Node": [200, 201],
                    }
                ),
            )
        ],
        volume_col="day_vol",
        facility_type="4",
        top_n=10,
    )
    assert comparison[0][1].to_dicts() == [
        {
            "id": 2,
            "facility_type": "4",
            "From_Node": 101,
            "To_Node": 201,
            "Observed Link Volume": 200.0,
            "Modeled Link Volume": 210.0,
            "% Diff": "-4.76%",
            "RMSE": 10.0,
        }
    ]
    comparison_without_metadata = external_volume_comparison_table(
        counts,
        volumes,
        volume_col="day_vol",
        facility_type="4",
        top_n=10,
    )
    assert comparison_without_metadata[0][1].columns == [
        "id",
        "facility_type",
        "Observed Link Volume",
        "Modeled Link Volume",
        "% Diff",
        "RMSE",
    ]

    derived_scatter = external_count_scatter_data(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "id": [1, 2, 3],
                        "facility_type": ["3", "4", "4"],
                        "period": ["Day", "AM", "Day"],
                        "observed_volume": [100.0, 20.0, 300.0],
                        "modeled_volume": [110.0, 21.0, 310.0],
                    }
                ),
            )
        ],
        period="Day",
        facility_type="4",
    )
    assert derived_scatter[0][1].to_dicts() == [
        {
            "id": 3,
            "facility_type": "4",
            "period": "Day",
            "observed_volume": 300.0,
            "modeled_volume": 310.0,
        }
    ]


def test_external_count_fit_line_helper_builds_plot_data() -> None:
    fit_lines = external_count_fit_line_data(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "facility_type": ["All", "4"],
                        "period": ["Day", "Day"],
                        "slope": [2.0, 3.0],
                        "intercept": [5.0, 7.0],
                        "r_squared": [1.0, 0.9],
                        "n_locations": [3, 2],
                        "observed_min": [10.0, 20.0],
                        "observed_max": [30.0, 40.0],
                        "equation_label": ["y = 2.00x + 5.00", "y = 3.00x + 7.00"],
                        "r_squared_label": ["R^2 = 1.00", "R^2 = 0.90"],
                    }
                ),
            )
        ],
        period="Day",
        facility_type="4",
    )

    assert fit_lines[0][1].select("observed_volume", "modeled_volume").to_dicts() == [
        {"observed_volume": 20.0, "modeled_volume": 67.0},
        {"observed_volume": 40.0, "modeled_volume": 127.0},
    ]
    assert "y = 3.00x + 7.00" in fit_lines[0][1]["annotation"][0]


def test_external_vmt_helper_reshapes_wide_tod_table() -> None:
    data = [
        (
            "Run",
            pl.DataFrame(
                {
                    "TOD": ["AM", "Daily"],
                    "SOV": [10.0, 20.0],
                    "HOV2": [2.0, 4.0],
                    "Total": [12.0, 24.0],
                }
            ),
        )
    ]

    chart_data = wide_tod_chart_data(
        data,
        tod_col="TOD",
        value_columns=["SOV", "HOV2"],
    )

    assert chart_data[0][1].to_dicts() == [
        {"tod": "AM", "category": "SOV", "value": 10.0},
        {"tod": "AM", "category": "HOV2", "value": 2.0},
    ]


def test_personal_auto_vmt_helper_aggregates_time_period_with_filters() -> None:
    data = [
        (
            "Run",
            pl.DataFrame(
                {
                    "geography_type": ["all_geographies"] * 4,
                    "geography_id": ["all_geographies"] * 4,
                    "income_segment": ["low", "low", "high", "low"],
                    "household_size": ["1", "2", "1", "1"],
                    "time_period": ["AM", "PM", "AM", "EA"],
                    "auto_vmt": [10.0, 5.0, 99.0, 3.0],
                    "trip_count": [2.0, 1.0, 9.0, 1.0],
                }
            ),
        )
    ]

    chart_data = personal_auto_vmt_chart_data(
        data,
        breakdown="Time Period",
        geography_type="all_geographies",
        geography_id="all_geographies",
        time_period="All",
        income_segment="low",
        household_size="All",
    )

    assert chart_data[0][1].to_dicts() == [
        {"category": "EA", "auto_vmt": 3.0, "trip_count": 1.0},
        {"category": "AM", "auto_vmt": 10.0, "trip_count": 2.0},
        {"category": "PM", "auto_vmt": 5.0, "trip_count": 1.0},
    ]


def test_personal_auto_vmt_helper_ignores_active_breakdown_selector() -> None:
    data = [
        (
            "Run",
            pl.DataFrame(
                {
                    "geography_type": ["all_geographies"] * 3,
                    "geography_id": ["all_geographies"] * 3,
                    "income_segment": ["low", "high", "low"],
                    "household_size": ["1", "1", "2"],
                    "time_period": ["AM", "AM", "PM"],
                    "auto_vmt": [10.0, 20.0, 30.0],
                    "trip_count": [1.0, 2.0, 3.0],
                }
            ),
        )
    ]

    chart_data = personal_auto_vmt_chart_data(
        data,
        breakdown="Income Segment",
        geography_type="all_geographies",
        geography_id="all_geographies",
        time_period="AM",
        income_segment="low",
        household_size="All",
    )

    assert chart_data[0][1].to_dicts() == [
        {"category": "high", "auto_vmt": 20.0, "trip_count": 2.0},
        {"category": "low", "auto_vmt": 10.0, "trip_count": 1.0},
    ]


def test_personal_auto_vmt_helper_caps_home_geography_breakdown() -> None:
    data = [
        (
            "Run",
            pl.DataFrame(
                {
                    "geography_type": ["home_taz"] * 30,
                    "geography_id": [str(value) for value in range(30)],
                    "income_segment": ["all_income_segments"] * 30,
                    "household_size": ["all_household_sizes"] * 30,
                    "time_period": ["Daily"] * 30,
                    "auto_vmt": [float(value) for value in range(30)],
                    "trip_count": [1.0] * 30,
                }
            ),
        )
    ]

    chart_data = personal_auto_vmt_chart_data(
        data,
        breakdown="Home Geography",
        geography_type="home_taz",
        geography_id="All",
        time_period="Daily",
        income_segment="All",
        household_size="All",
    )

    rows = chart_data[0][1].to_dicts()
    assert len(rows) == 25
    assert rows[0] == {"category": "29", "auto_vmt": 29.0, "trip_count": 1.0}
    assert rows[-1] == {"category": "5", "auto_vmt": 5.0, "trip_count": 1.0}


def test_vmt_page_registers_personal_auto_vmt_and_renders_missing_card(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {"totals": pl.DataFrame({"population": [1.0]})},
            "unweighted": {"totals": pl.DataFrame({"population": [1.0]})},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = VMTValidationPage(state, config)
    page.refresh(force=True)

    assert PERSONAL_AUTO_VMT_SUMMARY_ID in page.required_summary_ids
    assert page._personal_vmt_body.objects


def test_vmt_page_disables_active_personal_auto_vmt_filter_selector(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    personal_vmt = pl.DataFrame(
        {
            "geography_type": ["all_geographies", "all_geographies"],
            "geography_id": ["all_geographies", "all_geographies"],
            "income_segment": ["low", "high"],
            "household_size": ["1", "2"],
            "time_period": ["AM", "PM"],
            "auto_vmt": [10.0, 20.0],
            "trip_count": [1.0, 2.0],
            "distance_source": ["skim_auto_distance", "skim_auto_distance"],
            "time_period_source": ["trip_period", "trip_period"],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {PERSONAL_AUTO_VMT_SUMMARY_ID: personal_vmt},
            "unweighted": {PERSONAL_AUTO_VMT_SUMMARY_ID: personal_vmt},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = VMTValidationPage(state, config)
    page.refresh(force=True)

    assert page.personal_vmt_time_period_sel.disabled is True
    assert page.personal_vmt_income_segment_sel.disabled is False
    assert page.personal_vmt_household_size_sel.disabled is False

    page.personal_vmt_breakdown_sel.value = "Income Segment"
    page.refresh(force=True)

    assert page.personal_vmt_time_period_sel.disabled is False
    assert page.personal_vmt_income_segment_sel.disabled is True
    assert page.personal_vmt_income_segment_sel.value == "All"
    assert page.personal_vmt_household_size_sel.disabled is False


def test_regional_helpers_rename_blank_origin_and_compute_wfh_rate() -> None:
    matrix = pl.DataFrame(
        {
            "": ["A", "Total"],
            "A": [1.0, 2.0],
            "Total": [3.0, 4.0],
        }
    )
    wfh = [
        (
            "Run",
            pl.DataFrame(
                {
                    "District": ["A", "Total"],
                    "Workers": [10.0, 20.0],
                    "WFH": [2.0, 5.0],
                }
            ),
        )
    ]

    normalized = normalize_flow_matrix(matrix, include_totals=False)
    wfh_chart = wfh_rate_data(wfh)

    assert normalized.to_dicts() == [{"Origin": "A", "A": 1.0}]
    assert wfh_chart[0][1].to_dicts() == [
        {"District": "A", "Workers": 10.0, "WFH": 2.0, "wfh_rate": 20.0}
    ]


def test_regional_flow_heatmap_labels_cells_with_matrix_values() -> None:
    matrix = pl.DataFrame(
        {
            "": ["A", "B"],
            "A": [1200.0, 30.0],
            "B": [45.0, 6789.0],
        }
    )

    heatmap = flow_heatmap(
        [("Run", matrix)],
        include_totals=False,
        title="District flows",
    )
    plot = heatmap.objects[0][0]
    trace = plot.object.data[0]

    assert trace.text == (["1,200", "45"], ["30", "6,789"])
    assert trace.texttemplate == "%{text}"


def test_resolve_page_definitions_defaults_to_default_pages_when_unconfigured(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)

    resolved_pages = resolve_page_definitions(config)

    assert [page.title for page in resolved_pages] == EXPECTED_DEFAULT_LEAF_PAGE_TITLES


def test_page_selectors_render_with_widget_label_instead_of_duplicate_markdown(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    page = TripModePage(state, config)

    selector_row = page.view.objects[1]
    assert isinstance(selector_row, pn.Row)
    assert selector_row.objects == [page.tour_purpose_sel]
    assert page.tour_purpose_sel.name == "Tour Purpose"
    assert "page-selector-widget" in page.tour_purpose_sel.css_classes
    assert PAGE_SELECTOR_STYLESHEET in page.tour_purpose_sel.stylesheets


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


def test_enabled_prepared_data_mode_tracks_optional_and_required_page_sets(
    tmp_path: Path,
) -> None:
    summary_only_config = _write_config(tmp_path / "summary_only")
    raw_demo_config = _write_config(
        tmp_path / "raw_demo",
        dashboard_pages=["overview", "raw_trip_demo"],
    )

    assert enabled_prepared_data_mode(summary_only_config) == "optional"
    assert enabled_prepared_data_mode(raw_demo_config) == "required"


def test_data_requirements_for_pages_aggregates_summary_and_prepared_dependencies() -> None:
    overview = page_definition_by_id("overview")
    raw_trip_demo = page_definition_by_id("raw_trip_demo")

    requirements = data_requirements_for_pages([overview, raw_trip_demo])

    assert requirements.prepared_data_mode == "required"
    assert requirements.required_prepared_tables == ("trips",)
    assert requirements.required_summary_ids == overview.required_summary_ids


def test_data_requirements_for_pages_tracks_optional_summary_dependencies() -> None:
    vmt = page_definition_by_id("vmt")
    regional = page_definition_by_id("regional_validation")

    requirements = data_requirements_for_pages([vmt, regional])

    assert PERSONAL_AUTO_VMT_SUMMARY_ID in requirements.required_summary_ids
    assert "commercial_vmt_totals" in requirements.required_summary_ids
    assert "external_auto_vmt_summary" in requirements.optional_summary_ids
    assert "external_county_flows" in requirements.optional_summary_ids
    assert "external_auto_vmt_summary" in requirements.summary_ids_for_pruning


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
    assert state.page_state["Overview"]["last_rendered_state"] == state.global_state_key()

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


def test_build_dashboard_loads_prepared_runs_for_optional_default_pages_when_available(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard(
        [("Base", _raw_trip_run())],
        config,
        summary_runs=[_full_summary_run()],
    )

    assert template._dashboard_state.prepared_run_availability == "loaded"
    weighted_runs = template._dashboard_state.get_prepared_runs_if_loaded(weighted=True)

    assert weighted_runs is not None
    assert weighted_runs[0][0] == "Base"


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
    assert state.page_state["Overview"]["last_rendered_state"] == state.global_state_key()
    assert state.page_state["Daily Activity Pattern"].get("last_rendered_state") is None

    tabs.active = 1

    assert state.active_tab == 1
    assert state.page_state["Overview"]["last_rendered_state"] == state.global_state_key()
    assert (
        state.page_state["Daily Activity Pattern"]["last_rendered_state"]
        == state.global_state_key()
    )
    assert state.page_state["Tour Purpose"].get("last_rendered_state") is None

    state.weight_mode = "Unweighted"

    assert state.page_state["Overview"]["last_rendered_state"] is None
    assert (
        state.page_state["Daily Activity Pattern"]["last_rendered_state"]
        == state.global_state_key()
    )
    assert state.page_state["Tour Purpose"].get("last_rendered_state") is None

    state.value_mode = "Count"

    assert (
        state.page_state["Daily Activity Pattern"]["last_rendered_state"]
        == state.global_state_key()
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
    assert daily_activity_pattern_page.person_type_sel.options == [
        "All Person Types",
        "worker",
    ]

    daily_activity_pattern_page.person_type_sel.value = "worker"
    tabs.active = 0
    tabs.active = 1

    assert daily_activity_pattern_page.person_type_sel.value == "worker"


def test_build_dashboard_preserves_individual_choices_person_type_across_tab_switches(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()
    worker_summary_run = type(summary_run)(
        label=summary_run.label,
        run_key=summary_run.run_key,
        summaries_by_mode={
            mode: {
                **summary_run.summaries_by_mode[mode],
                "license_holding_status_distribution": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "license_holding_status": ["has_license", "has_license"],
                        "person_count": [80.0, 40.0],
                        "pct": [0.8, 1.0],
                    }
                ),
                "bicycle_comfort_level_distribution": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "bicycle_comfort_level": ["InterestedButConcerned", "StrongAndFearless"],
                        "person_count": [50.0, 20.0],
                        "pct": [0.5, 0.5],
                    }
                ),
                "transit_pass_ownership_by_person_type": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "transit_pass_ownership_status": ["no_pass", "has_pass"],
                        "person_count": [70.0, 15.0],
                        "pct": [0.7, 0.375],
                    }
                ),
                "transit_subsidy_by_person_type": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "transit_subsidy_status": ["none", "full"],
                        "person_count": [65.0, 10.0],
                        "pct": [0.65, 0.25],
                    }
                ),
            }
            for mode in summary_run.summaries_by_mode
        },
        source_run_dir=summary_run.source_run_dir,
        manifest=summary_run.manifest,
    )
    template = build_dashboard([], config, summary_runs=[worker_summary_run])
    top_tabs = template.main[0]
    long_term_choices_index = next(
        index
        for index, page in enumerate(template._dashboard_pages)
        if page.page_id() == "long_term_choices"
    )
    long_term_choices_page = template._dashboard_pages[long_term_choices_index]
    individual_choices_index = next(
        index
        for index, page in enumerate(long_term_choices_page.pages)
        if page.page_id() == "individual_choices"
    )
    individual_choices_page = long_term_choices_page.pages[individual_choices_index]

    top_tabs.active = long_term_choices_index
    long_term_choices_page.view.active = individual_choices_index
    assert individual_choices_page.person_type_sel.options == [
        "All Person Types",
        "worker",
    ]

    individual_choices_page.person_type_sel.value = "worker"
    top_tabs.active = 0
    top_tabs.active = long_term_choices_index
    long_term_choices_page.view.active = individual_choices_index

    assert individual_choices_page.person_type_sel.value == "worker"


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


def test_skim_pages_render_selector_controls_and_independent_sections(
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
                        "trip_mode": ["SOV", "WALK"],
                        "component": ["skim_auto_time", "skim_walk_distance"],
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
                        "trip_mode": ["SOV", "SOV", "WALK", "WALK"],
                        "component": [
                            "skim_auto_time",
                            "skim_auto_time",
                            "skim_walk_distance",
                            "skim_walk_distance",
                        ],
                        "percentile": [0.0, 1.0, 0.0, 1.0],
                        "value": [0.0, 10.0, 5.0, 5.0],
                        "n_valid": [3.0, 3.0, 2.0, 2.0],
                    }
                ),
                "skimjoin_tour_component_stats": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "SOV", "WALK", "WALK"],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_walk_distance_outbound",
                            "skim_walk_distance_inbound",
                        ],
                        "n_total": [6.0, 6.0, 2.0, 2.0],
                        "n_valid": [3.0, 3.0, 2.0, 2.0],
                        "mean": [6.67, 6.67, 5.0, 5.0],
                        "std": [4.71, 4.71, 0.0, 0.0],
                        "min": [0.0, 0.0, 5.0, 5.0],
                        "max": [10.0, 10.0, 5.0, 5.0],
                        "median": [10.0, 10.0, 5.0, 5.0],
                        "mode": [10.0, 10.0, 5.0, 5.0],
                        "zero_share": [0.33, 0.33, 0.0, 0.0],
                        "missing_share": [0.5, 0.5, 0.0, 0.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": [
                            "SOV",
                            "SOV",
                            "SOV",
                            "SOV",
                            "WALK",
                            "WALK",
                            "WALK",
                            "WALK",
                        ],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_auto_time_inbound",
                            "skim_walk_distance_outbound",
                            "skim_walk_distance_outbound",
                            "skim_walk_distance_inbound",
                            "skim_walk_distance_inbound",
                        ],
                        "percentile": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
                        "value": [0.0, 10.0, 0.0, 10.0, 5.0, 5.0, 5.0, 5.0],
                        "n_valid": [3.0, 3.0, 3.0, 3.0, 2.0, 2.0, 2.0, 2.0],
                    }
                ),
            },
            "unweighted": {
                **summary_run.summaries_by_mode["unweighted"],
                "skimjoin_trip_component_stats": pl.DataFrame(
                    {
                        "trip_mode": ["SOV"],
                        "component": ["skim_auto_time"],
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
                        "trip_mode": ["SOV", "SOV"],
                        "component": ["skim_auto_time", "skim_auto_time"],
                        "percentile": [0.0, 1.0],
                        "value": [0.0, 10.0],
                        "n_valid": [2.0, 2.0],
                    }
                ),
                "skimjoin_tour_component_stats": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "SOV"],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                        ],
                        "n_total": [3.0, 3.0],
                        "n_valid": [2.0, 2.0],
                        "mean": [5.0, 5.0],
                        "std": [5.0, 5.0],
                        "min": [0.0, 0.0],
                        "max": [10.0, 10.0],
                        "median": [0.0, 0.0],
                        "mode": [0.0, 0.0],
                        "zero_share": [0.5, 0.5],
                        "missing_share": [1.0 / 3.0, 1.0 / 3.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "SOV", "SOV", "SOV"],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_auto_time_inbound",
                        ],
                        "percentile": [0.0, 1.0, 0.0, 1.0],
                        "value": [0.0, 10.0, 0.0, 10.0],
                        "n_valid": [2.0, 2.0, 2.0, 2.0],
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

    trip_page = TripSkimsPage(state, config)
    trip_page.refresh(force=True)

    assert trip_page.trip_component_sel.options == [
        "skim_auto_time",
        "skim_walk_distance",
    ]
    assert list(trip_page.trip_mode_sel.options) == ["All Modes", "SOV"]
    assert len(trip_page._summary_section.objects) == 1
    assert len(trip_page._distribution_section.objects) == 2

    trip_page.trip_component_sel.value = "skim_walk_distance"

    assert list(trip_page.trip_mode_sel.options) == ["All Modes", "WALK"]
    assert len(trip_page._summary_section.objects) == 1
    assert len(trip_page._distribution_section.objects) == 2

    tour_page = TourSkimsPage(state, config)
    tour_page.refresh(force=True)

    assert tour_page.tour_component_sel.options == [
        "skim_auto_time",
        "skim_walk_distance",
    ]
    assert list(tour_page.tour_direction_sel.options) == ["Outbound", "Inbound"]
    assert list(tour_page.tour_mode_sel.options) == ["All Modes", "SOV"]
    assert len(tour_page._summary_section.objects) == 1
    assert len(tour_page._distribution_section.objects) == 4

    tour_page.tour_component_sel.value = "skim_walk_distance"

    assert list(tour_page.tour_mode_sel.options) == ["All Modes", "WALK"]
    assert len(tour_page._summary_section.objects) == 1
    assert len(tour_page._distribution_section.objects) == 4


def test_skim_pages_mode_selectors_exclude_component_modes_with_no_valid_observations(
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
                        "tour_mode": ["SOV", "SOV", "WALK", "WALK", "HOV2", "HOV2"],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_walk_distance_outbound",
                            "skim_walk_distance_inbound",
                        ],
                        "n_total": [10.0, 10.0, 5.0, 5.0, 3.0, 3.0],
                        "n_valid": [10.0, 10.0, 0.0, 0.0, 3.0, 3.0],
                        "mean": [12.0, 12.0, None, None, 1.5, 1.5],
                        "std": [2.0, 2.0, None, None, 0.2, 0.2],
                        "min": [8.0, 8.0, None, None, 1.2, 1.2],
                        "max": [16.0, 16.0, None, None, 1.8, 1.8],
                        "median": [12.0, 12.0, None, None, 1.5, 1.5],
                        "mode": [12.0, 12.0, None, None, 1.2, 1.2],
                        "zero_share": [0.0, 0.0, None, None, 0.0, 0.0],
                        "missing_share": [0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": [
                            "SOV",
                            "SOV",
                            "SOV",
                            "SOV",
                            "HOV2",
                            "HOV2",
                            "HOV2",
                            "HOV2",
                        ],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_auto_time_inbound",
                            "skim_walk_distance_outbound",
                            "skim_walk_distance_outbound",
                            "skim_walk_distance_inbound",
                            "skim_walk_distance_inbound",
                        ],
                        "percentile": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
                        "value": [8.0, 16.0, 8.0, 16.0, 1.2, 1.8, 1.2, 1.8],
                        "n_valid": [10.0, 10.0, 10.0, 10.0, 3.0, 3.0, 3.0, 3.0],
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

    trip_page = TripSkimsPage(state, config)
    trip_page.refresh(force=True)

    assert trip_page.trip_component_sel.options == [
        "skim_auto_time",
        "skim_walk_distance",
    ]
    assert list(trip_page.trip_mode_sel.options) == ["All Modes", "SOV"]

    trip_page.trip_component_sel.value = "skim_walk_distance"

    assert list(trip_page.trip_mode_sel.options) == ["All Modes", "HOV2"]

    tour_page = TourSkimsPage(state, config)
    tour_page.refresh(force=True)

    assert tour_page.tour_component_sel.options == [
        "skim_auto_time",
        "skim_walk_distance",
    ]
    assert list(tour_page.tour_mode_sel.options) == ["All Modes", "SOV"]

    tour_page.tour_component_sel.value = "skim_walk_distance"

    assert list(tour_page.tour_mode_sel.options) == ["All Modes", "HOV2"]


def test_skim_pages_render_disaggregated_distribution_plots_when_prepared_runs_are_loaded(
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
                        "tour_mode": ["SOV", "SOV"],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                        ],
                        "n_total": [100.0, 100.0],
                        "n_valid": [100.0, 100.0],
                        "mean": [13.88, 13.88],
                        "std": [18.71, 18.71],
                        "min": [10.0, 10.0],
                        "max": [200.0, 200.0],
                        "median": [12.0, 12.0],
                        "mode": [10.0, 10.0],
                        "zero_share": [0.0, 0.0],
                        "missing_share": [0.0, 0.0],
                    }
                ),
                "skimjoin_tour_component_ecdf": pl.DataFrame(
                    {
                        "tour_mode": ["SOV", "SOV", "SOV", "SOV", "SOV", "SOV"],
                        "component": [
                            "skim_auto_time_outbound",
                            "skim_auto_time_outbound",
                            "skim_auto_time_outbound",
                            "skim_auto_time_inbound",
                            "skim_auto_time_inbound",
                            "skim_auto_time_inbound",
                        ],
                        "percentile": [0.0, 0.99, 1.0, 0.0, 0.99, 1.0],
                        "value": [10.0, 14.0, 200.0, 10.0, 14.0, 200.0],
                        "n_valid": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
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
                "skim_auto_time_outbound": [10.0, 12.0, 14.0, 200.0],
                "skim_auto_time_inbound": [10.0, 12.0, 14.0, 200.0],
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

    trip_page = TripSkimsPage(state, config)
    trip_page.refresh(force=True)

    assert isinstance(trip_page._distribution_section.objects[-1], pn.pane.Plotly)
    assert tuple(trip_page._distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert trip_page._distribution_section.objects[-1].object.layout.title.text == (
        "Trip Distribution - skim_auto_time / All Modes"
    )

    trip_page.trip_min_sel.value = 11.0
    trip_page.trip_max_sel.value = 13.0

    assert tuple(trip_page._distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (11.0, 13.0)
    )

    trip_page.trip_reset_btn.clicks = trip_page.trip_reset_btn.clicks + 1

    assert tuple(trip_page._distribution_section.objects[-1].object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )

    tour_page = TourSkimsPage(state, config)
    tour_page.refresh(force=True)

    outbound_plot = tour_page._distribution_section.objects[1]
    inbound_plot = tour_page._distribution_section.objects[3]

    assert isinstance(outbound_plot, pn.pane.Plotly)
    assert isinstance(inbound_plot, pn.pane.Plotly)
    assert tuple(outbound_plot.object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert tuple(inbound_plot.object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert outbound_plot.object.layout.title.text == (
        "Outbound Tour Distribution - skim_auto_time_outbound / All Modes"
    )
    assert inbound_plot.object.layout.title.text == (
        "Inbound Tour Distribution - skim_auto_time_inbound / All Modes"
    )

    tour_page.outbound_min_sel.value = 11.0
    tour_page.outbound_max_sel.value = 13.0
    tour_page.inbound_min_sel.value = 11.0
    tour_page.inbound_max_sel.value = 13.0

    outbound_plot = tour_page._distribution_section.objects[1]
    inbound_plot = tour_page._distribution_section.objects[3]
    assert tuple(outbound_plot.object.layout.xaxis.range) == pytest.approx(
        (11.0, 13.0)
    )
    assert tuple(inbound_plot.object.layout.xaxis.range) == pytest.approx(
        (11.0, 13.0)
    )

    tour_page.outbound_reset_btn.clicks = tour_page.outbound_reset_btn.clicks + 1
    tour_page.inbound_reset_btn.clicks = tour_page.inbound_reset_btn.clicks + 1

    outbound_plot = tour_page._distribution_section.objects[1]
    inbound_plot = tour_page._distribution_section.objects[3]
    assert tuple(outbound_plot.object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert tuple(inbound_plot.object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
