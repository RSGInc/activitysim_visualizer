from __future__ import annotations

import importlib
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
from dashboard.export.selector_states import resolve_export_section_states
from dashboard.page_base import DashboardPage
from dashboard.page_base import PAGE_SELECTOR_STYLESHEET
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages.skim_summaries.trip_skims import TripSkimsPage
from dashboard.pages.skim_summaries.tour_skims import TourSkimsPage
from dashboard.pages.long_term_choices.mandatory_location_choice import (
    MandatoryLocationChoicePage,
)
from dashboard.pages.tour_summaries.tour_distance import TourDistancePage
from dashboard.pages.trip_summaries.trip_mode import TripModePage
from dashboard.pages.validation.regional import (
    RegionalValidationPage,
    flow_comparison_data,
    flow_heatmap,
    normalize_flow_matrix,
)
from dashboard.pages.validation.traffic import (
    demo_count_scatter_data,
    demo_count_scatter_data_from_sources,
    demo_facility_comparison_table,
    demo_count_fit_line_data,
    demo_link_aggregate_data,
    demo_volume_comparison_table,
)
from dashboard.pages.validation.vmt import (
    NON_MOTORIZED_VMT_SUMMARY_ID,
    PERSONAL_AUTO_VMT_SUMMARY_ID,
    VMTValidationPage,
    demo_commercial_filter_options,
    demo_commercial_vehicle_chart_data,
    external_travel_chart_data,
    external_travel_filter_options,
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
    resolve_live_page_definitions,
)
from dashboard.state import DashboardState
from processor.models import RunData
from processor.summarize.cache_types import create_summary_run
from processor.summarize.catalog import SUMMARY_BY_ID


def _collect_tabulators(viewable) -> list[pn.widgets.Tabulator]:
    tables: list[pn.widgets.Tabulator] = []
    if isinstance(viewable, pn.widgets.Tabulator):
        return [viewable]
    for child in getattr(viewable, "objects", []):
        tables.extend(_collect_tabulators(child))
    return tables


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

    assert [
        definition.page_id for definition in definitions
    ] == EXPECTED_DEFAULT_LEAF_PAGE_IDS
    assert [
        definition.title for definition in definitions
    ] == EXPECTED_DEFAULT_LEAF_PAGE_TITLES
    assert page_definition_by_id("daily_activity_pattern") is not None
    assert (
        page_definition_by_id("daily_activity_pattern").title
        == "Daily Activity Pattern"
    )
    assert page_definition_by_id("daily_activity_pattern").group_id == "daily_travel"
    assert not hasattr(page_definition_by_id("daily_activity_pattern"), "child_id")
    assert page_definition_by_id("trip_mode").page_cls is not None
    assert page_definition_by_id("raw_trip_demo") is not None
    assert page_definition_by_id("raw_trip_demo").default_enabled is False
    assert page_definition_by_id("raw_trip_demo").title == "Prepared Trip Demo"
    assert page_definition_by_id("raw_trip_demo").prepared_data_mode == "required"
    assert page_definition_by_id("raw_trip_demo").required_prepared_tables == ("trips",)


def test_discovered_page_modules_declare_decorated_page_classes() -> None:
    discovered_modules = []
    for module_info in pkgutil.iter_modules(dashboard_pages_package.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(
            f"{dashboard_pages_package.__name__}.{module_info.name}"
        )
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
        hasattr(module, "GROUP")
        or any(
            isinstance(value, type)
            and issubclass(value, DashboardPage)
            and value is not DashboardPage
            and value.__module__ == module.__name__
            and isinstance(value.definition, DashboardPageDefinition)
            for value in vars(module).values()
        )
        for module in discovered_modules
    )
    assert all(not hasattr(module, "PAGE") for module in discovered_modules)
    assert all(not hasattr(module, "build") for module in discovered_modules)


def test_page_registry_smoke_checks_metadata_and_class_attachment() -> None:
    definitions = all_page_definitions()

    assert all(definition.page_id for definition in definitions)
    assert all(definition.title for definition in definitions)
    assert len({definition.page_id for definition in definitions}) == len(definitions)
    assert all(definition.page_cls is not None for definition in definitions)

    for definition in definitions:
        assert definition.page_cls.definition is definition
        assert definition.prepared_data_mode in {"none", "optional", "required"}
        assert len(set(definition.required_summary_ids)) == len(
            definition.required_summary_ids
        )
        assert all(
            summary_id in SUMMARY_BY_ID
            for summary_id in definition.required_summary_ids
        )
        assert len(set(definition.optional_summary_ids)) == len(
            definition.optional_summary_ids
        )
        assert all(
            summary_id in SUMMARY_BY_ID
            for summary_id in definition.optional_summary_ids
        )


def test_page_registry_accepts_non_default_registered_summary_id() -> None:
    class ValidationAutoVmtPage(DashboardPage):
        pass

    definition = DashboardPageDefinition(
        page_id="auto_vmt_validation",
        title="Auto VMT Validation",
        page_cls=ValidationAutoVmtPage,
        required_summary_ids=("auto_vmt_validation_summary",),
        default_enabled=False,
    )

    _validate_page_definition(definition)
    requirements = data_requirements_for_pages([definition])

    assert requirements.required_summary_ids == ("auto_vmt_validation_summary",)


def test_dashboard_state_reports_missing_non_default_summary_as_diagnostic() -> None:
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {"population_totals": pl.DataFrame({"population": [1.0]})},
            "unweighted": {"population_totals": pl.DataFrame({"population": [1.0]})},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=["weighted", "unweighted"],
    )

    selection = state.inspect_summary_table("auto_vmt_validation_summary")

    assert selection.usable_runs == []
    assert [excluded.status for excluded in selection.excluded_runs] == ["missing"]
    assert selection.excluded_runs[0].source_id == "auto_vmt_validation_summary"


def test_external_traffic_helpers_filter_period_and_facility_type(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
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

    scatter = demo_count_scatter_data_from_sources(
        counts,
        volumes,
        volume_col="day_vol",
        facility_type="4",
    )
    aggregate = demo_link_aggregate_data(
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
    comparison = demo_volume_comparison_table(
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
            "link_id": 2,
            "facility_type": "4",
            "From_Node": 101,
            "To_Node": 201,
            "Observed Link Volume": 200.0,
            "Modeled Link Volume": 210.0,
            "Difference": 10.0,
            "% Difference": "5.00%",
        }
    ]
    comparison_without_metadata = demo_volume_comparison_table(
        counts,
        volumes,
        volume_col="day_vol",
        facility_type="4",
        top_n=10,
    )
    assert comparison_without_metadata[0][1].columns == [
        "link_id",
        "facility_type",
        "Observed Link Volume",
        "Modeled Link Volume",
        "Difference",
        "% Difference",
    ]
    comparison_with_empty_metadata = demo_volume_comparison_table(
        counts,
        volumes,
        link_list=[
            (
                "Run",
                pl.DataFrame(
                    {
                        "id": [1, 2],
                        "From_Node": [None, None],
                        "To_Node": [None, None],
                    }
                ),
            )
        ],
        volume_col="day_vol",
        facility_type="4",
        top_n=10,
    )
    assert comparison_with_empty_metadata[0][1].columns == [
        "link_id",
        "facility_type",
        "Observed Link Volume",
        "Modeled Link Volume",
        "Difference",
        "% Difference",
    ]
    comparison_top_modeled = demo_volume_comparison_table(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "id": [1, 2],
                        "FACTYPE": [4, 4],
                        "day_vol": [999.0, 100.0],
                    }
                ),
            )
        ],
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "id": [1, 2],
                        "FACTYPE": [4, 4],
                        "day_vol": [50.0, 200.0],
                    }
                ),
            )
        ],
        volume_col="day_vol",
        facility_type="All",
        top_n=1,
    )
    assert comparison_top_modeled[0][1]["link_id"].to_list() == [2]

    derived_scatter = demo_count_scatter_data(
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
    facility_comparison = demo_facility_comparison_table(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "id": [1, 2, 3],
                        "facility_type": ["4", "4", "3"],
                        "period": ["Day", "Day", "Day"],
                        "observed_volume": [100.0, 300.0, 50.0],
                        "modeled_volume": [110.0, 330.0, 75.0],
                    }
                ),
            )
        ],
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "facility_type": ["4"],
                        "period": ["Day"],
                        "r_squared": [0.875],
                    }
                ),
            )
        ],
        period="Day",
        facility_type="4",
        config=config,
    )

    assert facility_comparison[0][1].to_dicts() == [
        {
            "Facility Type": "4",
            "n": 2,
            "Total Observed Count": 400.0,
            "Total Modeled Count": 440.0,
            "% Difference": "10.00%",
            "RMSE": 22.360679774997898,
            "R^2": 0.875,
        }
    ]


def test_demo_count_fit_line_helper_builds_plot_data() -> None:
    fit_lines = demo_count_fit_line_data(
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


def test_demo_commercial_vehicle_helper_aggregates_selected_breakdown(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    commercial_vehicle_type:",
            "      mapping:",
            "        car: Car",
            "        su: Single-Unit Truck",
            "        mu: Multi-Unit Truck",
        ],
    )
    data = [
        (
            "Run",
            pl.DataFrame(
                {
                    "tod": ["AM", "PM", "Daily"],
                    "car": [10.0, 20.0, 100.0],
                    "mu": [30.0, 10.0, 200.0],
                    "su": [5.0, 15.0, 300.0],
                }
            ),
        )
    ]

    by_period = demo_commercial_vehicle_chart_data(
        data,
        breakdown="Time Period",
    )
    by_type = demo_commercial_vehicle_chart_data(
        data,
        breakdown="Commercial Vehicle Type",
        time_period="AM",
    )
    by_type_daily = demo_commercial_vehicle_chart_data(
        data,
        breakdown="Commercial Vehicle Type",
        time_period="Daily",
    )
    time_period_options, (vehicle_type_options, raw_by_label) = (
        demo_commercial_filter_options(data, config=config)
    )

    assert by_period[0][1].to_dicts() == [
        {
            "category": "AM",
            "value": 45.0,
            "value_percent": pytest.approx(7.5),
        },
        {
            "category": "PM",
            "value": 45.0,
            "value_percent": pytest.approx(7.5),
        },
        {
            "category": "Daily",
            "value": 600.0,
            "value_percent": 100.0,
        },
    ]
    assert by_period[0][1].select("category", "value_percent").to_dicts() == [
        {"category": "AM", "value_percent": pytest.approx(7.5)},
        {"category": "PM", "value_percent": pytest.approx(7.5)},
        {"category": "Daily", "value_percent": 100.0},
    ]
    assert by_type[0][1].to_dicts() == [
        {"category": "car", "value": 10.0},
        {"category": "mu", "value": 30.0},
        {"category": "su", "value": 5.0},
    ]
    assert by_type_daily[0][1].to_dicts() == [
        {"category": "car", "value": 100.0},
        {"category": "mu", "value": 200.0},
        {"category": "su", "value": 300.0},
    ]
    assert time_period_options == ["Daily", "AM", "PM"]
    assert vehicle_type_options == [
        "All",
        "Car",
        "Single-Unit Truck",
        "Multi-Unit Truck",
    ]
    assert raw_by_label["Car"] == "car"
    assert raw_by_label["Multi-Unit Truck"] == "mu"


def test_external_travel_helper_aggregates_selected_breakdown(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    trip_purpose:",
            "      mapping:",
            "        hbw: Work",
            "        nhbw: Non-Home-Based Work",
        ],
    )
    data = [
        (
            "Run",
            pl.DataFrame(
                {
                    "tod": ["AM", "PM", "Daily"],
                    "hbw": [10.0, 20.0, 100.0],
                    "nhbw": [30.0, 10.0, 200.0],
                    "truck": [5.0, 15.0, 300.0],
                    "Total": [45.0, 45.0, 600.0],
                }
            ),
        )
    ]

    by_period = external_travel_chart_data(
        data,
        breakdown="Time Period",
    )
    by_purpose = external_travel_chart_data(
        data,
        breakdown="Trip Purpose",
        time_period="AM",
    )
    time_period_options, (purpose_options, raw_by_label) = (
        external_travel_filter_options(
            data,
            config=config,
        )
    )

    assert by_period[0][1].to_dicts() == [
        {
            "category": "AM",
            "value": 45.0,
            "value_percent": pytest.approx(7.5),
        },
        {
            "category": "PM",
            "value": 45.0,
            "value_percent": pytest.approx(7.5),
        },
        {
            "category": "Daily",
            "value": 600.0,
            "value_percent": 100.0,
        },
    ]
    assert by_purpose[0][1].to_dicts() == [
        {"category": "hbw", "value": 10.0},
        {"category": "nhbw", "value": 30.0},
        {"category": "truck", "value": 5.0},
    ]
    assert time_period_options == ["Daily", "AM", "PM"]
    assert purpose_options[:3] == ["All", "Work", "Non-Home-Based Work"]
    assert raw_by_label["Work"] == "hbw"


def test_personal_auto_vmt_helper_aggregates_time_period_with_filters() -> None:
    data = [
        (
            "Period Run",
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
        ),
        (
            "Daily Run",
            pl.DataFrame(
                {
                    "geography_type": ["all_geographies"],
                    "geography_id": ["all_geographies"],
                    "income_segment": ["low"],
                    "household_size": ["1"],
                    "time_period": ["Daily"],
                    "auto_vmt": [7.0],
                    "trip_count": [2.0],
                }
            ),
        ),
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

    assert chart_data[0][1].select("category", "auto_vmt", "trip_count").to_dicts() == [
        {"category": "EA", "auto_vmt": 3.0, "trip_count": 1.0},
        {"category": "AM", "auto_vmt": 10.0, "trip_count": 2.0},
        {"category": "PM", "auto_vmt": 5.0, "trip_count": 1.0},
    ]
    assert chart_data[1][1].select("category", "auto_vmt", "trip_count").to_dicts() == [
        {"category": "Daily", "auto_vmt": 7.0, "trip_count": 2.0},
    ]


def test_personal_auto_vmt_time_period_percent_uses_daily_total() -> None:
    chart_data = personal_auto_vmt_chart_data(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "geography_type": ["all_geographies"] * 3,
                        "geography_id": ["all_geographies"] * 3,
                        "income_segment": ["low"] * 3,
                        "household_size": ["1"] * 3,
                        "time_period": ["AM", "PM", "Daily"],
                        "auto_vmt": [10.0, 5.0, 15.0],
                        "trip_count": [2.0, 1.0, 3.0],
                    }
                ),
            )
        ],
        breakdown="Time Period",
        geography_type="all_geographies",
        geography_id="all_geographies",
        time_period="All",
        income_segment="low",
        household_size="1",
    )

    rows = chart_data[0][1].select("category", "auto_vmt_percent").to_dicts()
    assert rows == [
        {"category": "AM", "auto_vmt_percent": pytest.approx(66.6666666667)},
        {"category": "PM", "auto_vmt_percent": pytest.approx(33.3333333333)},
        {"category": "Daily", "auto_vmt_percent": 100.0},
    ]


def test_personal_auto_vmt_all_time_period_filter_prefers_daily_totals() -> None:
    chart_data = personal_auto_vmt_chart_data(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "geography_type": ["all_geographies"] * 3,
                        "geography_id": ["all_geographies"] * 3,
                        "income_segment": ["low"] * 3,
                        "household_size": ["1"] * 3,
                        "time_period": ["AM", "PM", "Daily"],
                        "auto_vmt": [10.0, 5.0, 15.0],
                        "trip_count": [2.0, 1.0, 3.0],
                    }
                ),
            )
        ],
        breakdown="Income Segment",
        geography_type="all_geographies",
        geography_id="all_geographies",
        time_period="All",
        income_segment="All",
        household_size="1",
    )

    assert chart_data[0][1].to_dicts() == [
        {"category": "low", "auto_vmt": 15.0, "trip_count": 3.0},
    ]


def test_personal_auto_vmt_helper_breaks_down_by_mode() -> None:
    chart_data = personal_auto_vmt_chart_data(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "geography_type": ["all_geographies"] * 4,
                        "geography_id": ["all_geographies"] * 4,
                        "income_segment": ["low"] * 4,
                        "household_size": ["1"] * 4,
                        "time_period": ["AM", "Daily", "AM", "Daily"],
                        "mode": ["SOV", "SOV", "HOV2", "HOV2"],
                        "auto_vmt": [10.0, 10.0, 3.0, 3.0],
                        "trip_count": [1.0, 1.0, 1.0, 1.0],
                    }
                ),
            )
        ],
        breakdown="Mode",
        geography_type="all_geographies",
        geography_id="all_geographies",
        time_period="All",
        income_segment="low",
        household_size="1",
    )

    assert chart_data[0][1].to_dicts() == [
        {"category": "SOV", "auto_vmt": 10.0, "trip_count": 1.0},
        {"category": "HOV2", "auto_vmt": 3.0, "trip_count": 1.0},
    ]


def test_personal_auto_vmt_helper_filters_by_mode() -> None:
    chart_data = personal_auto_vmt_chart_data(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "geography_type": ["all_geographies"] * 4,
                        "geography_id": ["all_geographies"] * 4,
                        "income_segment": ["low", "low", "high", "high"],
                        "household_size": ["1"] * 4,
                        "time_period": ["Daily"] * 4,
                        "mode": ["SOV", "HOV2", "SOV", "HOV2"],
                        "auto_vmt": [10.0, 3.0, 20.0, 7.0],
                        "trip_count": [1.0, 1.0, 2.0, 2.0],
                    }
                ),
            )
        ],
        breakdown="Income Segment",
        geography_type="all_geographies",
        geography_id="all_geographies",
        time_period="Daily",
        mode="HOV2",
        income_segment="All",
        household_size="1",
    )

    assert chart_data[0][1].to_dicts() == [
        {"category": "high", "auto_vmt": 7.0, "trip_count": 2.0},
        {"category": "low", "auto_vmt": 3.0, "trip_count": 1.0},
    ]


def test_vmt_page_labels_personal_auto_modes_from_display_config(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    mode:",
            "      mapping:",
            "        SOV: Drive Alone",
            "        HOV2: Shared Ride 2",
            "        TAXI: Taxi",
        ],
    )
    personal_vmt = pl.DataFrame(
        {
            "geography_type": ["all_geographies"] * 3,
            "geography_id": ["all_geographies"] * 3,
            "income_segment": ["low"] * 3,
            "household_size": ["1"] * 3,
            "time_period": ["Daily"] * 3,
            "mode": ["SOV", "HOV2", "TAXI"],
            "auto_vmt": [10.0, 3.0, 4.0],
            "trip_count": [1.0, 1.0, 1.0],
            "distance_source": ["od_dist"] * 3,
            "time_period_source": ["trip_period"] * 3,
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
    state.value_mode = "Count"

    page = VMTValidationPage(state, config)
    page.refresh(force=True)

    assert list(page.personal_vmt_mode_sel.options) == [
        "All",
        "Drive Alone",
        "Shared Ride 2",
        "Taxi",
    ]
    page.personal_vmt_breakdown_sel.value = "Income Segment"
    page.personal_vmt_mode_sel.value = "Taxi"
    page.refresh(force=True)

    assert page.selected_personal_vmt_mode_raw() == "TAXI"


def test_non_motorized_vmt_section_mirrors_personal_auto_controls(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    mode:",
            "      mapping:",
            "        WALK: Walk",
            "        BIKE: Bike",
            "    geography:",
            "      mapping:",
            "        all_geographies: All Geographies",
            "        home_county: County",
        ],
    )
    personal_vmt = pl.DataFrame(
        {
            "geography_type": ["all_geographies"],
            "geography_id": ["all_geographies"],
            "income_segment": ["all_income_segments"],
            "household_size": ["all_household_sizes"],
            "time_period": ["Daily"],
            "mode": ["SOV"],
            "auto_vmt": [10.0],
            "trip_count": [1.0],
            "distance_source": ["skim_auto_distance"],
            "time_period_source": ["trip_period"],
        }
    )
    non_motorized_vmt = pl.DataFrame(
        {
            "geography_type": [
                "all_geographies",
                "all_geographies",
                "home_county",
                "home_county",
            ],
            "geography_id": ["all_geographies", "all_geographies", "Wake", "Wake"],
            "income_segment": ["low", "high", "low", "high"],
            "household_size": ["1", "2", "1", "2"],
            "time_period": ["Daily", "Daily", "AM", "PM"],
            "mode": ["WALK", "BIKE", "WALK", "BIKE"],
            "non_motorized_vmt": [5.0, 3.0, 2.0, 3.0],
            "trip_count": [3.0, 2.0, 1.0, 2.0],
            "distance_source": ["prepared_non_motorized_distance"] * 4,
            "time_period_source": ["trip_period"] * 4,
        }
    )
    external_vmt = pl.DataFrame(
        {
            "tod": ["Daily"],
            "hbo": [20.0],
            "Total": [20.0],
        }
    )
    commercial_vmt = pl.DataFrame(
        {
            "tod": ["Daily"],
            "car": [7.0],
            "mu": [3.0],
            "su": [0.0],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                PERSONAL_AUTO_VMT_SUMMARY_ID: personal_vmt,
                NON_MOTORIZED_VMT_SUMMARY_ID: non_motorized_vmt,
                "external_vmt_validation_summary": external_vmt,
                "commercial_vehicle_vmt_validation_summary": commercial_vmt,
            },
            "unweighted": {
                PERSONAL_AUTO_VMT_SUMMARY_ID: personal_vmt,
                NON_MOTORIZED_VMT_SUMMARY_ID: non_motorized_vmt,
                "external_vmt_validation_summary": external_vmt,
                "commercial_vehicle_vmt_validation_summary": commercial_vmt,
            },
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Count"

    page = VMTValidationPage(state, config)
    page.refresh(force=True)

    markdown_titles = [
        obj.object for obj in page.view.objects if isinstance(obj, pn.pane.Markdown)
    ]
    assert markdown_titles[:4] == [
        "## VMT Validation",
        "### VMT Overview",
        "### Personal Auto VMT",
        "### Non-Motorized VMT",
    ]
    assert markdown_titles[4] == "### External VMT and Travel"
    overview_tables = _collect_tabulators(page._vmt_overview_body)
    assert len(overview_tables) == 1
    assert overview_tables[0].value.to_dict("records") == [
        {
            "Category": "Personal Auto",
            "VMT": "10",
            "% Share of Total": "20.83",
        },
        {
            "Category": "Non-Motorized",
            "VMT": "8",
            "% Share of Total": "16.67",
        },
        {
            "Category": "External",
            "VMT": "20",
            "% Share of Total": "41.67",
        },
        {
            "Category": "Commercial",
            "VMT": "10",
            "% Share of Total": "20.83",
        },
    ]
    assert list(page.non_motorized_vmt_mode_sel.options) == [
        "All",
        "Walk",
        "Bike",
    ]
    assert page.non_motorized_vmt_geography_type_sel.disabled is False
    assert page.non_motorized_vmt_geography_sel.disabled is False

    page.non_motorized_vmt_breakdown_sel.value = "Home Geography"
    page.refresh(force=True)
    page.non_motorized_vmt_geography_type_sel.value = "County"
    page.refresh(force=True)

    assert page.non_motorized_vmt_geography_type_sel.disabled is False
    assert page.non_motorized_vmt_geography_sel.name == "County Name"
    assert page.selected_non_motorized_vmt_geography_type_raw() == "home_county"

    page.non_motorized_vmt_breakdown_sel.value = "Mode"
    page.refresh(force=True)
    assert page.non_motorized_vmt_geography_type_sel.disabled is False
    assert page.non_motorized_vmt_geography_sel.disabled is False
    assert page.non_motorized_vmt_mode_sel.disabled is True
    assert page.non_motorized_vmt_mode_sel.value == "All"

    chart = page.render_non_motorized_vmt_section()[0]
    assert chart.object.layout.title.text == "Non-Motorized VMT by Mode"
    assert chart.object.layout.yaxis.title.text == "Non-Motorized Miles Traveled"
    assert list(chart.object.layout.xaxis.categoryarray) == ["Walk", "Bike"]


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
            "weighted": {"population_totals": pl.DataFrame({"population": [1.0]})},
            "unweighted": {"population_totals": pl.DataFrame({"population": [1.0]})},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = VMTValidationPage(state, config)
    page.refresh(force=True)

    assert PERSONAL_AUTO_VMT_SUMMARY_ID in page.required_summary_ids
    assert NON_MOTORIZED_VMT_SUMMARY_ID in page.required_summary_ids
    assert page._personal_vmt_body.objects
    assert page._non_motorized_vmt_body.objects


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
            "mode": ["SOV", "HOV2"],
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

    assert page.personal_vmt_geography_type_sel.disabled is False
    assert page.personal_vmt_geography_sel.disabled is False
    assert page.personal_vmt_time_period_sel.disabled is True
    assert page.personal_vmt_mode_sel.disabled is False
    assert page.personal_vmt_income_segment_sel.disabled is False
    assert page.personal_vmt_household_size_sel.disabled is False

    page.personal_vmt_breakdown_sel.value = "Home Geography"
    page.refresh(force=True)

    assert page.personal_vmt_geography_type_sel.disabled is False
    assert page.personal_vmt_geography_sel.disabled is False

    page.personal_vmt_breakdown_sel.value = "Income Segment"
    page.refresh(force=True)

    assert page.personal_vmt_geography_type_sel.disabled is False
    assert page.personal_vmt_geography_sel.disabled is False
    assert page.personal_vmt_time_period_sel.disabled is False
    assert page.personal_vmt_mode_sel.disabled is False
    assert page.personal_vmt_income_segment_sel.disabled is True
    assert page.personal_vmt_income_segment_sel.value == "All"
    assert page.personal_vmt_household_size_sel.disabled is False

    page.personal_vmt_breakdown_sel.value = "Mode"
    page.refresh(force=True)

    assert page.personal_vmt_geography_type_sel.disabled is False
    assert page.personal_vmt_geography_sel.disabled is False
    assert page.personal_vmt_time_period_sel.disabled is False
    assert page.personal_vmt_mode_sel.disabled is True
    assert page.personal_vmt_mode_sel.value == "All"


def test_vmt_page_geography_selectors_use_display_labels_and_raw_filters(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    geography:",
            "      mapping:",
            "        all_geographies: All Geographies",
            "        home_county: County",
        ],
    )
    personal_vmt = pl.DataFrame(
        {
            "geography_type": ["all_geographies", "home_county", "home_county"],
            "geography_id": ["all_geographies", "Wake", "Durham"],
            "income_segment": ["low", "low", "low"],
            "household_size": ["1", "1", "1"],
            "time_period": ["Daily", "Daily", "Daily"],
            "mode": ["SOV", "SOV", "SOV"],
            "auto_vmt": [30.0, 10.0, 20.0],
            "trip_count": [3.0, 1.0, 2.0],
            "distance_source": ["skim_auto_distance"] * 3,
            "time_period_source": ["trip_period"] * 3,
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

    assert list(page.personal_vmt_geography_type_sel.options) == [
        "All Geography Types",
        "County",
    ]
    assert page.personal_vmt_breakdown_sel.value == "Time Period"
    assert page.personal_vmt_geography_type_sel.disabled is False
    assert page.personal_vmt_geography_sel.disabled is False

    page.personal_vmt_geography_type_sel.value = "County"
    page.refresh(force=True)

    assert page.personal_vmt_geography_type_sel.disabled is False
    assert page.personal_vmt_geography_sel.disabled is False
    assert page.personal_vmt_geography_sel.name == "County Name"
    assert list(page.personal_vmt_geography_sel.options) == [
        "All Counties",
        "Durham",
        "Wake",
    ]
    page.personal_vmt_geography_sel.value = "Durham"

    assert page.selected_personal_vmt_geography_type_raw() == "home_county"
    assert page.selected_personal_vmt_geography_raw() == "Durham"


def test_vmt_export_states_collapse_ignored_personal_auto_selectors(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    personal_vmt = pl.DataFrame(
        {
            "geography_type": [
                "all_geographies",
                "home_county",
                "home_county",
                "home_county",
            ],
            "geography_id": [
                "all_geographies",
                "Wake",
                "Durham",
                "Wake",
            ],
            "income_segment": ["low", "low", "high", "low"],
            "household_size": ["1", "1", "2", "1"],
            "time_period": ["Daily", "AM", "PM", "AM"],
            "mode": ["SOV", "SOV", "HOV2", "HOV2"],
            "auto_vmt": [30.0, 10.0, 20.0, 5.0],
            "trip_count": [3.0, 1.0, 2.0, 1.0],
            "distance_source": ["skim_auto_distance"] * 4,
            "time_period_source": ["trip_period"] * 4,
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

    selector_widgets = {
        selector.selector_id: selector.widget for selector in page.registered_selectors
    }
    assert selector_widgets["personal_auto_vmt_geography_type"].disabled is False
    assert selector_widgets["personal_auto_vmt_geography"].disabled is False

    active_selector_ids = [
        "personal_auto_vmt_breakdown",
        "personal_auto_vmt_geography_type",
        "personal_auto_vmt_geography",
        "personal_auto_vmt_time_period",
        "personal_auto_vmt_mode",
        "personal_auto_vmt_income_segment",
        "personal_auto_vmt_household_size",
    ]
    request_modes = {
        "personal_auto_vmt_breakdown": "explicit",
        "personal_auto_vmt_geography_type": "all",
        "personal_auto_vmt_geography": "all",
        "personal_auto_vmt_time_period": "default",
        "personal_auto_vmt_mode": "all",
        "personal_auto_vmt_income_segment": "default",
        "personal_auto_vmt_household_size": "default",
    }
    requested_values = {
        "personal_auto_vmt_breakdown": ["Mode", "Home Geography"],
    }
    selector_metadata = {
        selector_id: {
            "id": selector_id,
            "label": selector_id,
            "available": True,
            "request_mode": request_modes[selector_id],
            "requested_values": requested_values.get(selector_id, []),
            "resolved_values": [
                str(option) for option in selector_widgets[selector_id].options
            ],
            "default_value": str(selector_widgets[selector_id].value),
            "options": [
                str(option) for option in selector_widgets[selector_id].options
            ],
            "export_enabled": True,
        }
        for selector_id in active_selector_ids
    }

    states, aliases = resolve_export_section_states(
        page,
        page_def=VMTValidationPage.definition,
        part_def=type("Part", (), {"part_id": "personal_auto_vmt_body"})(),
        active_selector_ids=active_selector_ids,
        selector_widgets=selector_widgets,
        selector_metadata_by_id=selector_metadata,
    )

    assert all(
        state["personal_auto_vmt_mode"] == "All"
        for state in states
        if state["personal_auto_vmt_breakdown"] == "Mode"
    )
    mode_states = [
        state for state in states if state["personal_auto_vmt_breakdown"] == "Mode"
    ]
    assert (
        len({state["personal_auto_vmt_geography_type"] for state in mode_states}) == 1
    )
    assert {state["personal_auto_vmt_geography_type"] for state in mode_states} == {
        "All Geography Types"
    }
    assert len({state["personal_auto_vmt_geography"] for state in mode_states}) == 1
    home_state_groups = {
        tuple(
            value
            for selector_id, value in state.items()
            if selector_id != "personal_auto_vmt_geography"
        )
        for state in states
        if state["personal_auto_vmt_breakdown"] == "Home Geography"
    }
    home_states = [
        state
        for state in states
        if state["personal_auto_vmt_breakdown"] == "Home Geography"
    ]
    assert len(home_states) == len(home_state_groups)
    assert len({state["personal_auto_vmt_geography_type"] for state in home_states}) > 1
    assert aliases


def test_vmt_demo_commercial_vehicle_chart_uses_breakdown_and_percent_mode(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    commercial_vehicle_type:",
            "      mapping:",
            "        car: Car",
            "        su: Single-Unit Truck",
            "        mu: Multi-Unit Truck",
        ],
    )
    demo_commercial = pl.DataFrame(
        {
            "tod": ["AM", "PM", "Daily"],
            "car": [10.0, 20.0, 100.0],
            "mu": [30.0, 10.0, 200.0],
            "su": [5.0, 15.0, 300.0],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "commercial_vehicle_validation_summary": demo_commercial,
            },
            "unweighted": {
                "commercial_vehicle_validation_summary": demo_commercial,
            },
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Percent"

    page = VMTValidationPage(state, config)
    page.refresh(force=True)
    page.demo_commercial_metric_sel.value = "Trips"
    page.demo_commercial_breakdown_sel.value = "Time Period"
    page.demo_commercial_vehicle_type_sel.value = "Car"

    chart = page.render_demo_commercial_chart()
    fig = chart.object

    assert fig.layout.title.text == "Commercial Vehicle Trips by Time Period"
    assert fig.layout.showlegend is True
    assert fig.layout.yaxis.title.text == "Percent of Trips (%)"
    assert len(fig.data) == 1
    assert list(fig.data[0].x) == ["AM", "PM", "Daily"]
    assert list(fig.data[0].y) == [10.0, 20.0, 100.0]
    assert list(fig.layout.xaxis.categoryarray) == ["AM", "PM", "Daily"]
    assert list(page.demo_commercial_time_period_sel.options) == [
        "Daily",
        "AM",
        "PM",
    ]
    assert list(page.demo_commercial_vehicle_type_sel.options) == [
        "All",
        "Car",
        "Single-Unit Truck",
        "Multi-Unit Truck",
    ]
    assert page.selected_demo_commercial_vehicle_type_raw() == "car"

    page.refresh(force=True)
    assert page.demo_commercial_time_period_sel.disabled is True
    assert page.demo_commercial_time_period_sel.value == "Daily"
    assert page.demo_commercial_vehicle_type_sel.disabled is False

    page.demo_commercial_breakdown_sel.value = "Commercial Vehicle Type"
    page.demo_commercial_time_period_sel.value = "AM"
    chart = page.render_demo_commercial_chart()

    assert chart.object.layout.title.text == (
        "Commercial Vehicle Trips by Commercial Vehicle Type"
    )
    assert list(chart.object.layout.xaxis.categoryarray) == [
        "Car",
        "Single-Unit Truck",
        "Multi-Unit Truck",
    ]


def test_vmt_external_travel_chart_uses_metric_breakdown_and_filters(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    trip_purpose:",
            "      mapping:",
            "        hbw: Work",
            "        nhbw: Non-Home-Based Work",
        ],
    )
    external_travel = pl.DataFrame(
        {
            "tod": ["AM", "PM", "Daily"],
            "hbw": [10.0, 20.0, 100.0],
            "nhbw": [30.0, 10.0, 200.0],
            "truck": [5.0, 15.0, 300.0],
            "Total": [45.0, 45.0, 600.0],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "external_trip_validation_summary": external_travel,
            },
            "unweighted": {
                "external_trip_validation_summary": external_travel,
            },
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Percent"

    page = VMTValidationPage(state, config)
    page.refresh(force=True)
    page.external_travel_metric_sel.value = "Trips"
    page.external_travel_breakdown_sel.value = "Time Period"
    page.external_travel_trip_purpose_sel.value = "Work"

    chart = page.render_external_travel_chart()
    fig = chart.object

    assert fig.layout.title.text == "External Trips by Time Period"
    assert fig.layout.yaxis.title.text == "Percent of Trips (%)"
    assert list(fig.data[0].x) == ["AM", "PM", "Daily"]
    assert list(fig.data[0].y) == [10.0, 20.0, 100.0]
    assert list(fig.layout.xaxis.categoryarray) == ["AM", "PM", "Daily"]
    assert list(page.external_travel_time_period_sel.options) == [
        "Daily",
        "AM",
        "PM",
    ]
    assert page.external_travel_time_period_sel.disabled is True
    assert page.external_travel_time_period_sel.value == "Daily"
    assert page.external_travel_trip_purpose_sel.disabled is False
    assert page.selected_external_travel_trip_purpose_raw() == "hbw"

    page.external_travel_breakdown_sel.value = "Trip Purpose"
    page.external_travel_time_period_sel.value = "AM"
    chart = page.render_external_travel_chart()

    assert chart.object.layout.title.text == "External Trips by Trip Purpose"
    assert list(chart.object.layout.xaxis.categoryarray) == [
        "Work",
        "Non-Home-Based Work",
        "truck",
    ]
    assert list(chart.object.data[0].x) == [
        "Work",
        "Non-Home-Based Work",
        "truck",
    ]


def _export_selector_widgets(page) -> dict[str, pn.widgets.Widget]:
    return {
        selector.selector_id: selector.widget for selector in page.registered_selectors
    }


def _export_selector_metadata(
    selector_widgets: dict[str, pn.widgets.Widget],
    selector_ids: list[str],
    *,
    request_modes: dict[str, str] | None = None,
    requested_values: dict[str, list[str]] | None = None,
) -> dict[str, dict]:
    request_modes = request_modes or {}
    requested_values = requested_values or {}
    return {
        selector_id: {
            "id": selector_id,
            "label": selector_id,
            "available": True,
            "request_mode": request_modes.get(selector_id, "all"),
            "requested_values": requested_values.get(selector_id, []),
            "resolved_values": [
                str(option) for option in selector_widgets[selector_id].options
            ],
            "default_value": str(selector_widgets[selector_id].value),
            "options": [
                str(option) for option in selector_widgets[selector_id].options
            ],
            "export_enabled": True,
        }
        for selector_id in selector_ids
    }


def test_mandatory_location_choice_geography_labels_filter_raw_and_export(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    geography:",
            "      mapping:",
            "        all_geographies: All Geographies",
            "        home_county: County",
        ],
    )
    internal_external = pl.DataFrame(
        {
            "geography_type": [
                "all_geographies",
                "home_county",
                "home_county",
            ],
            "geography_id": ["all_geographies", "Wake", "Durham"],
            "internal_worker_count": [30.0, 10.0, 20.0],
            "external_worker_count": [3.0, 1.0, 2.0],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {"internal_external_worker_by_geography": internal_external},
            "unweighted": {"internal_external_worker_by_geography": internal_external},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
        export_mode=True,
    )

    page = MandatoryLocationChoicePage(state, config)
    page.refresh(force=True)

    assert list(page.geo_level_sel.options) == [
        "All Geography Types",
        "County",
    ]
    assert "Durham" in page.geography_sel.options
    assert "Wake" in page.geography_sel.options

    page.geo_level_sel.value = "County"
    page.geography_sel.value = "Durham"

    assert page._selected_geography() == ("home_county", "Durham")


def test_mandatory_location_choice_export_aliases_invalid_geography_pairs(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    geography:",
            "      mapping:",
            "        all_geographies: All Geography Types",
            "        home_county: County",
            "        district: District",
        ],
    )
    internal_external = pl.DataFrame(
        {
            "geography_type": [
                "all_geographies",
                "home_county",
                "home_county",
                "district",
            ],
            "geography_id": ["all_geographies", "Wake", "Durham", "North"],
            "internal_worker_count": [30.0, 10.0, 20.0, 15.0],
            "external_worker_count": [3.0, 1.0, 2.0, 1.5],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {"internal_external_worker_by_geography": internal_external},
            "unweighted": {"internal_external_worker_by_geography": internal_external},
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
        export_mode=True,
    )
    page = MandatoryLocationChoicePage(state, config)
    page.refresh(force=True)

    selector_ids = ["geography_level", "geography"]
    selector_widgets = _export_selector_widgets(page)
    states, aliases = resolve_export_section_states(
        page,
        page_def=MandatoryLocationChoicePage.definition,
        part_def=type("Part", (), {"part_id": "remote_work"})(),
        active_selector_ids=selector_ids,
        selector_widgets=selector_widgets,
        selector_metadata_by_id=_export_selector_metadata(
            selector_widgets,
            selector_ids,
        ),
    )

    state_pairs = {(state["geography_level"], state["geography"]) for state in states}
    assert ("County", "North") not in state_pairs
    assert ("District", "Durham") not in state_pairs
    assert ("District", "Wake") not in state_pairs
    assert ("County", "Durham") in state_pairs
    assert ("County", "Wake") in state_pairs
    assert ("District", "North") in state_pairs
    assert aliases['["County","North"]'] == '["County","All"]'
    assert aliases['["District","Durham"]'] == '["District","All"]'
    assert len(states) < (
        len(page.geo_level_sel.options) * len(page.geography_sel.options)
    )


def test_tour_distance_export_geography_pairs_follow_selected_level(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    average_mandatory = pl.DataFrame(
        {
            "mandatory_tour_purpose": ["work"],
            "geography_level": ["Region"],
            "average_tour_distance": [8.0],
        }
    )
    average_nonmandatory = pl.DataFrame(
        {
            "nonmandatory_tour_purpose": ["shopping", "shopping", "shopping"],
            "geography_type": ["district", "district", "county"],
            "geography_id": ["North", "South", "Wake"],
            "average_tour_distance": [4.0, 8.0, 12.0],
            "tour_count": [2.0, 3.0, 4.0],
        }
    )
    distance = pl.DataFrame(
        {
            "tour_purpose": ["all_tour_purposes"],
            "distance_bin": [0],
            "tour_count": [5.0],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "tour_distance_by_tour_purpose": distance,
                "average_mandatory_tour_distance_by_purpose_and_geography": average_mandatory,
                "average_nonmandatory_tour_distance_by_purpose_and_geography": average_nonmandatory,
            },
            "unweighted": {
                "tour_distance_by_tour_purpose": distance,
                "average_mandatory_tour_distance_by_purpose_and_geography": average_mandatory,
                "average_nonmandatory_tour_distance_by_purpose_and_geography": average_nonmandatory,
            },
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    page = TourDistancePage(state, config)
    page.refresh(force=True)

    selector_ids = [
        "geography_level",
        "geography",
    ]
    selector_widgets = _export_selector_widgets(page)
    states, aliases = resolve_export_section_states(
        page,
        page_def=TourDistancePage.definition,
        part_def=type("Part", (), {"part_id": "tour_distance_averages"})(),
        active_selector_ids=selector_ids,
        selector_widgets=selector_widgets,
        selector_metadata_by_id=_export_selector_metadata(
            selector_widgets,
            selector_ids,
        ),
    )

    state_pairs = {(state["geography_level"], state["geography"]) for state in states}
    assert ("District", "North") in state_pairs
    assert ("District", "South") in state_pairs
    assert ("County", "Wake") in state_pairs
    assert ("District", "Wake") not in state_pairs
    assert ("County", "North") not in state_pairs
    assert aliases == {}


def test_regional_helpers_rename_blank_origin() -> None:
    matrix = pl.DataFrame(
        {
            "": ["A", "Total"],
            "A": [1.0, 2.0],
            "Total": [3.0, 4.0],
        }
    )

    normalized = normalize_flow_matrix(matrix, include_totals=False)

    assert normalized.to_dicts() == [{"Origin": "A", "A": 1.0}]


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


def test_regional_flow_comparison_aligns_observed_and_modeled_flows() -> None:
    observed = [
        (
            "Base",
            pl.DataFrame(
                {
                    "": ["A", "B", "Total"],
                    "A": [10.0, 3.0, 13.0],
                    "B": [5.0, 20.0, 25.0],
                    "Total": [15.0, 23.0, 38.0],
                }
            ),
        )
    ]
    modeled = [
        (
            "Base",
            pl.DataFrame(
                {
                    "origin_geography_type": ["home_county"] * 4,
                    "origin_geography_id": ["A", "A", "B", "B"],
                    "destination_geography_type": ["home_county"] * 4,
                    "destination_geography_id": ["A", "B", "A", "B"],
                    "commuter_count": [12.0, 4.0, 3.0, 18.0],
                }
            ),
        )
    ]

    comparison = flow_comparison_data(
        observed,
        modeled,
        geography_type="home_county",
        include_totals=False,
    )

    assert comparison[0][1].select(
        "Origin",
        "Destination",
        "observed",
        "modeled",
        "difference",
        "percent_difference",
    ).to_dicts() == [
        {
            "Origin": "A",
            "Destination": "A",
            "observed": 10.0,
            "modeled": 12.0,
            "difference": 2.0,
            "percent_difference": 20.0,
        },
        {
            "Origin": "A",
            "Destination": "B",
            "observed": 5.0,
            "modeled": 4.0,
            "difference": -1.0,
            "percent_difference": -20.0,
        },
        {
            "Origin": "B",
            "Destination": "A",
            "observed": 3.0,
            "modeled": 3.0,
            "difference": 0.0,
            "percent_difference": 0.0,
        },
        {
            "Origin": "B",
            "Destination": "B",
            "observed": 20.0,
            "modeled": 18.0,
            "difference": -2.0,
            "percent_difference": -10.0,
        },
    ]


def test_regional_validation_page_compares_county_flows_to_commuting_flows(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    observed = pl.DataFrame(
        {
            "": ["A", "B", "Total"],
            "A": [10.0, 3.0, 13.0],
            "B": [5.0, 20.0, 25.0],
            "Total": [15.0, 23.0, 38.0],
        }
    )
    modeled = pl.DataFrame(
        {
            "origin_geography_type": ["home_county"] * 4,
            "origin_geography_id": ["A", "A", "B", "B"],
            "destination_geography_type": ["home_county"] * 4,
            "destination_geography_id": ["A", "B", "A", "B"],
            "commuter_count": [12.0, 4.0, 3.0, 18.0],
        }
    )
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "county_flows_joja_validation_summary": observed,
                "commuting_flows": modeled,
            },
            "unweighted": {
                "county_flows_joja_validation_summary": observed,
                "commuting_flows": modeled,
            },
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = RegionalValidationPage(state, config)
    page.refresh(force=True)

    assert list(page.flow_matrix_sel.options) == ["County flows"]
    assert list(page.comparison_metric_sel.options) == [
        "Observed",
        "Difference",
        "Percent Difference",
        "Absolute Percent Difference",
        "Modeled",
    ]
    chart = page.render_flow_section()
    tabs = chart.objects[0]
    plot = tabs.objects[0][0]

    assert plot.object.layout.title.text == "Observed County flows"
    assert plot.object.data[0].z == ([10.0, 5.0], [3.0, 20.0])

    page.comparison_metric_sel.value = "Difference"
    chart = page.render_flow_section()
    tabs = chart.objects[0]
    plot = tabs.objects[0][0]

    assert plot.object.layout.title.text == "Difference County flows"
    assert plot.object.data[0].z == ([2.0, -1.0], [0.0, -2.0])


def test_resolve_page_definitions_defaults_to_default_pages_when_unconfigured(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)

    resolved_pages = resolve_live_page_definitions(config)

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
    assert selector_row.objects == [page.tour_purpose_sel, page.hide_drive_alone]
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

    resolved_pages = resolve_live_page_definitions(config)

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

    resolved_pages = resolve_live_page_definitions(config)

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


def test_data_requirements_for_pages_aggregates_summary_and_prepared_dependencies() -> (
    None
):
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
    assert NON_MOTORIZED_VMT_SUMMARY_ID in requirements.required_summary_ids
    assert "commercial_vmt_totals" not in requirements.required_summary_ids
    assert "commercial_vmt_totals" not in requirements.optional_summary_ids
    assert "auto_vmt_validation_summary" not in requirements.optional_summary_ids
    assert "county_flows_validation_summary" in requirements.optional_summary_ids
    assert "commuting_flows" in requirements.optional_summary_ids
    assert "auto_vmt_validation_summary" not in requirements.summary_ids_for_pruning


def test_resolve_page_definitions_rejects_unknown_configured_page_ids(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=["overview", "unknown_page"])

    with pytest.raises(
        ValueError, match="Unsupported dashboard.live.pages entries"
    ):
        resolve_live_page_definitions(config)


def test_resolve_page_definitions_rejects_duplicate_configured_page_ids(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="dashboard.live.pages contains duplicate page id 'overview'",
    ):
        _write_config(tmp_path, dashboard_pages=["overview", "overview"])


def test_build_dashboard_uses_expected_default_page_order(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])

    assert [
        page.name for page in template._dashboard_pages
    ] == EXPECTED_DEFAULT_PAGE_TITLES
    assert [
        page.page_id() for page in template._dashboard_pages
    ] == EXPECTED_DEFAULT_PAGE_IDS
    assert [
        page.page_id() for page in template._dashboard_leaf_pages
    ] == EXPECTED_DEFAULT_LEAF_PAGE_IDS


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
    assert (
        state.page_state["overview"]["last_rendered_state"] == state.global_state_key()
    )

    leaf_pages = {page.page_id(): page for page in template._dashboard_leaf_pages}
    assert [
        selector.selector_id
        for selector in leaf_pages["trip_stop_distance"].registered_selectors
    ] == [
        "tour_purpose",
        "trip_stop_distance_min",
        "trip_stop_distance_max",
    ]
    assert leaf_pages["daily_activity_pattern"].person_type_sel.options == [
        "All Person Types",
        "worker",
    ]
    assert leaf_pages["joint_travel"].hhsize_sel.options == [
        "All",
        "2",
        "3",
        "4",
        "5+",
    ]
    assert leaf_pages["tour_time"].purpose_sel.options == ["All Tour Purposes", "work"]
    assert leaf_pages["tour_mode"].purpose_sel.options == ["All Tour Purposes", "work"]
    assert leaf_pages["tour_stop_frequency"].purpose_sel.options == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]
    assert leaf_pages["trip_stop_time"].tour_purpose_sel.options == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]
    assert leaf_pages["trip_mode"].tour_purpose_sel.options == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]


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
    weighted_runs = template._dashboard_state.get_prepared_runs_if_loaded(
        weighting_mode="weighted"
    )

    assert weighted_runs is not None
    assert weighted_runs[0][0] == "Base"


def test_build_dashboard_loads_prepared_runs_when_demo_page_is_enabled(
    tmp_path: Path,
) -> None:
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
    assert any(
        getattr(obj, "title", "") == "Data Not Available" for obj in page.view.objects
    )


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
    assert state.get_prepared_runs_if_loaded(weighting_mode="weighted") is None
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

    weighted_runs = loaded_state.get_prepared_runs_if_loaded(
        weighting_mode="weighted"
    )
    unweighted_runs = loaded_state.get_prepared_runs_if_loaded(
        weighting_mode="unweighted"
    )

    assert loaded_state.prepared_run_availability == "loaded"
    assert weighted_runs is not None
    assert weighted_runs[0][0] == "Base"
    assert weighted_runs[0][1].hh["finalweight"][0] == 2.0
    assert unweighted_runs is not None
    assert unweighted_runs[0][1].hh["finalweight"][0] == 1.0
    assert unavailable_state.prepared_run_availability == "unavailable"
    assert (
        unavailable_state.get_prepared_runs_if_loaded(weighting_mode="weighted")
        is None
    )


def test_build_dashboard_switches_tabs_and_refreshes_only_the_active_page(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    template = build_dashboard([], config, summary_runs=[_full_summary_run()])
    state = template._dashboard_state
    tabs = template.main[0]

    assert state.active_tab == 0
    assert (
        state.page_state["overview"]["last_rendered_state"] == state.global_state_key()
    )
    assert state.page_state["daily_activity_pattern"].get("last_rendered_state") is None

    tabs.active = 1

    assert state.active_tab == 1
    assert (
        state.page_state["overview"]["last_rendered_state"] == state.global_state_key()
    )
    assert (
        state.page_state["daily_activity_pattern"]["last_rendered_state"]
        == state.global_state_key()
    )
    assert state.page_state["tour_purpose"].get("last_rendered_state") is None

    state.weight_mode = "Unweighted"

    assert state.page_state["overview"]["last_rendered_state"] is None
    assert (
        state.page_state["daily_activity_pattern"]["last_rendered_state"]
        == state.global_state_key()
    )
    assert state.page_state["tour_purpose"].get("last_rendered_state") is None

    state.value_mode = "Count"

    assert (
        state.page_state["daily_activity_pattern"]["last_rendered_state"]
        == state.global_state_key()
    )
    assert state.page_state["overview"].get("last_rendered_state") is None
    assert (
        state.page_state["mandatory_location_choice"].get("last_rendered_state") is None
    )
    assert state.page_state["tour_purpose"].get("last_rendered_state") is None


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
                        "bicycle_comfort_level": [
                            "InterestedButConcerned",
                            "StrongAndFearless",
                        ],
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


def test_dashboard_page_cache_helpers_reuse_summary_and_query_results(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _full_summary_run()
    probe_summary_run = type(summary_run)(
        label=summary_run.label,
        run_key=summary_run.run_key,
        summaries_by_mode={
            "weighted": {
                **summary_run.summaries_by_mode["weighted"],
                "probe_summary": pl.DataFrame({"value": ["summary"]}),
            },
            "unweighted": {
                **summary_run.summaries_by_mode["unweighted"],
                "probe_summary": pl.DataFrame({"value": ["summary"]}),
            },
        },
        source_run_dir=summary_run.source_run_dir,
        manifest=summary_run.manifest,
    )
    state = DashboardState(
        summary_runs=[probe_summary_run],
        weighting_modes=config.weighting_modes,
    )
    call_counts = {"query": 0}

    class CacheProbePage(DashboardPage):
        def __init__(self) -> None:
            super().__init__(state, config)
            self.view = pn.Column()

        def _query_factory(self) -> dict[str, str]:
            call_counts["query"] += 1
            return {"kind": "query"}

        def _refresh(self) -> None:
            self.summary_value = self.data.summary("probe_summary")
            self.query_value = self.query(self._query_factory)

    page = CacheProbePage()

    page.refresh(force=True)
    page.refresh(force=True)
    page.mark_stale()
    page.refresh_if_needed()

    assert call_counts == {"query": 1}
    assert page.summary_value[0][1]["value"][0] == "summary"
    assert page.query_value == {"kind": "query"}
    assert state.cache_stats["page_query"] == {"hits": 2, "misses": 1}


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
                        "component": [
                            "skim_auto_time",
                            "skim_auto_time",
                            "skim_auto_time",
                        ],
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
    assert tuple(
        trip_page._distribution_section.objects[-1].object.layout.xaxis.range
    ) == pytest.approx((10.0, 200.0))
    assert trip_page._distribution_section.objects[-1].object.layout.title.text == (
        "Trip Distribution - skim_auto_time / All Modes"
    )

    trip_page.trip_min_sel.value = 11.0
    trip_page.trip_max_sel.value = 13.0

    assert tuple(
        trip_page._distribution_section.objects[-1].object.layout.xaxis.range
    ) == pytest.approx((11.0, 13.0))

    trip_page.trip_reset_btn.clicks = trip_page.trip_reset_btn.clicks + 1

    assert tuple(
        trip_page._distribution_section.objects[-1].object.layout.xaxis.range
    ) == pytest.approx((10.0, 200.0))

    tour_page = TourSkimsPage(state, config)
    tour_page.refresh(force=True)

    outbound_note_view = tour_page._distribution_section.objects[1]
    inbound_note_view = tour_page._distribution_section.objects[3]
    assert "calculation-note-view" in outbound_note_view.css_classes
    assert "calculation-note-view" in inbound_note_view.css_classes
    outbound_plot = outbound_note_view.objects[0]
    inbound_plot = inbound_note_view.objects[0]

    assert isinstance(outbound_plot, pn.pane.Plotly)
    assert isinstance(inbound_plot, pn.pane.Plotly)
    assert tuple(outbound_plot.object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert tuple(inbound_plot.object.layout.xaxis.range) == pytest.approx((10.0, 200.0))
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

    outbound_plot = tour_page._distribution_section.objects[1].objects[0]
    inbound_plot = tour_page._distribution_section.objects[3].objects[0]
    assert tuple(outbound_plot.object.layout.xaxis.range) == pytest.approx((11.0, 13.0))
    assert tuple(inbound_plot.object.layout.xaxis.range) == pytest.approx((11.0, 13.0))

    tour_page.outbound_reset_btn.clicks = tour_page.outbound_reset_btn.clicks + 1
    tour_page.inbound_reset_btn.clicks = tour_page.inbound_reset_btn.clicks + 1

    outbound_plot = tour_page._distribution_section.objects[1].objects[0]
    inbound_plot = tour_page._distribution_section.objects[3].objects[0]
    assert tuple(outbound_plot.object.layout.xaxis.range) == pytest.approx(
        (10.0, 200.0)
    )
    assert tuple(inbound_plot.object.layout.xaxis.range) == pytest.approx((10.0, 200.0))
