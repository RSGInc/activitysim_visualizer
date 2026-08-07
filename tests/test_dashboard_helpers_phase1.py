from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.rendering import (
    column_titles,
    data_table,
)
from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    column_value_intersection,
    common_column_options,
    complete_category_counts,
    normalize_category_strings,
    numeric_like_sort_expr,
)
from dashboard.helpers.comparison_helpers import (
    build_ab_comparison_row,
    build_ab_comparison_table,
    build_base_run_percent_difference_table,
    format_percent_error_table,
    weighted_average_lookup,
)
from dashboard.helpers.geography_helpers import (
    all_within_geography_type_label,
    export_geography_name_options,
    geography_level_options,
    geography_name_options_for_type,
    geography_name_selector_label,
    geography_options_for_level,
    geography_type_options,
    normalize_geography_columns,
    export_geography_options,
    filter_geography_level,
)
from dashboard.helpers.person_type_helpers import (
    ALL_PERSON_TYPES,
    filter_person_type_counts,
    filter_person_type_rates,
    person_type_selector_options,
    person_type_weights_by_run,
)
from dashboard.helpers.time_distance_helpers import (
    distance_sort_expr,
    max_timebin,
    timebin_duration_hours,
    timebin_label,
)
from dashboard.page_base import DashboardPage
from dashboard.pages.skim_summaries._shared import component_display_name
from dashboard.pages.trip_summaries.parking_location import parking_scatter_data
from dashboard.state import DashboardState
from processor.models import RunData
from test_export_html import _full_summary_run, _write_config


@pytest.mark.parametrize(
    ("component", "expected"),
    [
        (
            "skim_bike_transit_distance_bus",
            "Total Bike Distance - Local Bus (mi) (Estimated from Walk Skims)",
        ),
        (
            "skim_bike_transit_distance_premium",
            "Total Bike Distance - Premium Transit (mi) (Estimated from Walk Skims)",
        ),
    ],
)
def test_component_display_name_labels_estimated_bike_transit_distances(
    component: str,
    expected: str,
) -> None:
    assert component_display_name(component) == expected


def test_run_table_view_filters_transforms_and_joins_by_run_label() -> None:
    counts = RunTables.from_runs(
        [
            ("Base", pl.DataFrame({"direction": ["outbound", "inbound"], "n": [2, 3]})),
            ("Build", pl.DataFrame({"direction": ["outbound"], "n": [5]})),
        ]
    )
    totals = RunTables.from_runs(
        [
            ("Base", pl.DataFrame({"direction": ["outbound"], "total": [10]})),
            ("Build", pl.DataFrame({"direction": ["outbound"], "total": [20]})),
        ]
    )

    result = (
        counts.where(direction="outbound")
        .join(totals, on="direction")
        .with_columns((pl.col("n") / pl.col("total") * 100).alias("pct"))
        .select("direction", "pct")
    )

    assert result.values("direction") == ["outbound"]
    assert [frame["pct"][0] for _, frame in result] == [20.0, 25.0]

    empty_build = counts.where(direction="inbound")
    assert [label for label, _ in empty_build] == ["Base", "Build"]
    assert empty_build[1][1].is_empty()

    complete = RunTables.from_runs(
        [
            ("Base", pl.DataFrame({"id": [1], "value": [2]})),
            ("Build", pl.DataFrame({"id": [2]})),
        ]
    ).requiring("id", "value")
    assert [label for label, _ in complete] == ["Base"]
    assert [label for label, _ in empty_build.drop_empty()] == ["Base"]

    outer = RunTables.from_runs(
        [("Base", pl.DataFrame({"id": [1], "left": [10]}))]
    ).join(
        RunTables.from_runs(
            [("Base", pl.DataFrame({"id": [2], "right": [20]}))]
        ),
        on="id",
        how="full",
        coalesce=True,
    )
    assert outer[0][1].sort("id")["id"].to_list() == [1, 2]


def test_parking_query_joins_summary_and_prepared_tables_by_run() -> None:
    empty = pl.DataFrame()
    prepared = RunData(
        label="Base",
        run_dir="base",
        skim_file=None,
        hh=empty,
        per=empty,
        tours=empty,
        trips=empty,
        joint_participants=empty,
        land_use=pl.DataFrame({"MAZ": [1, 2], "PRKSPACES": [10, 20]}),
        skim_matrix=None,
    )
    summaries = [
        (
            "Base",
            pl.DataFrame(
                {
                    "geography_type": ["maz", "maz"],
                    "geography_id": ["1", "3"],
                    "trip_count": [4, 6],
                }
            ),
        )
    ]

    result = parking_scatter_data(summaries, [("Base", prepared.land_use)])

    assert [label for label, _ in result] == ["Base"]
    assert result[0][1].to_dict(as_series=False) == {
        "geography_id": ["1", "2", "3"],
        "parking_capacity": [10.0, 20.0, 0.0],
        "trip_count": [4.0, 0.0, 6.0],
    }


def test_category_helpers_support_intersection_normalization_and_numeric_sort(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    data_a = [("Base", pl.DataFrame({"value": ["All", "2", "10", "40+"]}))]
    data_b = [("Base", pl.DataFrame({"value": ["All", "10", "40+"]}))]

    intersection = column_value_intersection(data_a, data_b, column="value")
    options, mapping = common_column_options(
        data_a,
        data_b,
        column="value",
        total_raw="All",
        total_label="All",
    )
    normalized = normalize_category_strings(
        [("Base", pl.DataFrame({"category": ["", "Worker"]}))],
        "category",
    )
    completed = complete_category_counts(
        [("Base", pl.DataFrame({"bin": ["10", "40+"], "count": [2, 1]}))],
        category="bin",
        category_values=["2", "10", "40+"],
        value_cols=("count",),
    )
    sorted_bins = (
        pl.DataFrame({"bin": ["40+", "2", "10"]})
        .with_columns(numeric_like_sort_expr("bin").alias("_sort"))
        .sort("_sort")
        .drop("_sort")["bin"]
        .to_list()
    )

    assert intersection == ["All", "10", "40+"]
    assert options == ["All", "10", "40+"]
    assert mapping["10"] == "10"
    assert normalized[0][1]["category"].to_list() == ["Unspecified", "Worker"]
    assert completed[0][1]["count"].to_list() == [0, 2, 1]
    assert sorted_bins == ["2", "10", "40+"]


def test_geography_helpers_normalize_and_build_options(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        geography_lines=["enabled: true", "landuse_col: COUNTY"],
        extra_lines=[
            "display:",
            "  labels:",
            "    geography:",
            "      mapping:",
            "        all_geographies: All Geographies",
            "        home_county: County",
            "        district: District",
        ],
    )
    summary = [
        (
            "Base",
            pl.DataFrame(
                {
                    "geography_type": [
                        "all_geographies",
                        "district",
                        "district",
                        "home_county",
                        "home_county",
                    ],
                    "geography_id": [
                        "all_geographies",
                        "Urban",
                        "Suburban",
                        "Wake",
                        "Durham",
                    ],
                }
            ),
        )
    ]
    flow_summary = [
        (
            "Base",
            pl.DataFrame(
                {
                    "origin_geography_level": ["district", "district"],
                    "destination_geography_level": ["district", "district"],
                }
            ),
        )
    ]

    normalized = normalize_geography_columns(summary[0][1])
    geo_levels = geography_level_options(summary, flow_summary, config=config)
    geo_type_options, geo_type_raw_by_label = geography_type_options(
        summary,
        flow_summary,
        config=config,
        include_all_types=True,
    )
    county_options, county_raw_by_label = geography_name_options_for_type(
        "home_county",
        summary,
        config=config,
    )
    district_options = geography_options_for_level("district", summary, config=config)
    flattened = export_geography_options(
        {"district": district_options, "all_geographies": ["All Geographies"]},
        config=config,
    )
    flattened_display, flattened_raw_by_label = export_geography_name_options(
        {
            "home_county": (county_options, county_raw_by_label),
        },
        config=config,
    )
    filtered = filter_geography_level(summary, "district")

    assert {"geography_level", "geography"}.issubset(normalized.columns)
    assert geo_levels == ["All Geography Types", "County", "District"]
    assert geo_type_options == [
        "All Geography Types",
        "County",
        "District",
    ]
    assert geo_type_raw_by_label["All Geography Types"] == "all_geographies"
    assert geo_type_raw_by_label["County"] == "home_county"
    assert all_within_geography_type_label("home_county", config=config) == "All Counties"
    assert geography_name_selector_label("home_county", config=config) == "County Name"
    assert county_options == ["All Counties", "Durham", "Wake"]
    assert county_raw_by_label["All Counties"] == "All"
    assert county_raw_by_label["Wake"] == "Wake"
    assert district_options == ["All", "Suburban", "Urban"]
    assert flattened == ["All", "Suburban", "Urban"]
    assert flattened_display == ["All", "Durham", "Wake"]
    assert flattened_raw_by_label["Wake"] == "Wake"
    assert filtered[0][1]["geography_id"].to_list() == ["Urban", "Suburban"]


def test_person_type_helpers_support_selector_domains_and_weighted_rollups(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )
    counts = [
        (
            "Base",
            pl.DataFrame(
                {
                    "person_type": [ALL_PERSON_TYPES, "worker", "student"],
                    "person_count": [10.0, 6.0, 4.0],
                }
            ),
        )
    ]
    rates = [
        (
            "Base",
            pl.DataFrame(
                {
                    "person_type": ["worker", "student"],
                    "tour_purpose": ["work", "work"],
                    "tour_rate": [2.0, 1.0],
                }
            ),
        )
    ]

    options, mapping = person_type_selector_options(
        counts,
        config=config,
        state=state,
        cache_key=("phase1", "person_type"),
    )
    filtered_counts = filter_person_type_counts(counts, "worker")
    weights = person_type_weights_by_run(counts)
    rolled_up = filter_person_type_rates(
        rates,
        ALL_PERSON_TYPES,
        purpose_col="tour_purpose",
        rate_col="tour_rate",
        person_weights=weights,
    )

    assert options == ["All Person Types", "worker", "student"]
    assert mapping["All Person Types"] == ALL_PERSON_TYPES
    assert filtered_counts[0][1]["person_count"].to_list() == [6.0]
    assert rolled_up[0][1]["tour_rate"].to_list() == [1.6]


def test_time_distance_helpers_match_existing_dashboard_bin_conventions() -> None:
    data_list = [("Base", pl.DataFrame({"time_bin": [1, 2, 48]}))]
    sorted_bins = (
        pl.DataFrame({"bin": ["40+", "2", "10"]})
        .with_columns(distance_sort_expr("bin").alias("_sort"))
        .sort("_sort")
        .drop("_sort")["bin"]
        .to_list()
    )

    assert max_timebin(data_list) == 48
    assert timebin_label(1, 48) == "03:00"
    assert timebin_duration_hours(2, 48) == 1.0
    assert sorted_bins == ["2", "10", "40+"]


def test_comparison_helpers_format_and_build_comparison_tables() -> None:
    formatted = format_percent_error_table(
        pl.DataFrame({"percent_error": [12.3456, float("inf"), None]})
    )
    lookup = weighted_average_lookup(
        pl.DataFrame(
            {
                "purpose": ["work", "work", "school"],
                "average_distance": [10.0, 20.0, 5.0],
                "tour_count": [1.0, 3.0, 2.0],
            }
        ),
        category="purpose",
        average_col="average_distance",
        weight_col="tour_count",
    )
    table = build_base_run_percent_difference_table(
        run_labels=["Base", "Build"],
        base_run_label="Base",
        row_header="Metric",
        row_values={
            "Tours": {"Base": 100.0, "Build": 110.0},
            "Trips": {"Base": 50.0, "Build": 45.0},
        },
    )

    assert formatted["percent_error"].to_list() == ["12.35%", "", ""]
    assert lookup == {"work": 17.5, "school": 5.0}
    assert table.to_dicts() == [
        {"Metric": "Tours", "Base": "0.00%", "Build": "10.00%"},
        {"Metric": "Trips", "Base": "0.00%", "Build": "-10.00%"},
    ]
    renamed_table = build_base_run_percent_difference_table(
        run_labels=["Reference", "Build"],
        base_run_label="Reference",
        row_header="Metric",
        row_values={"Tours": {"Reference": 100.0, "Build": 110.0}},
    )
    assert renamed_table.columns == ["Metric", "Reference (Base Run)", "Build"]


def test_ab_comparison_helper_formats_difference_columns() -> None:
    table = build_ab_comparison_table(
        [
            build_ab_comparison_row(
                keys={"Metric": "Tours"},
                quantity_a=110.0,
                quantity_b=100.0,
                quantity_a_column="Build Value",
                quantity_b_column="Base Value",
            ),
            build_ab_comparison_row(
                keys={"Metric": "Trips"},
                quantity_a=45.0,
                quantity_b=0.0,
                quantity_a_column="Build Value",
                quantity_b_column="Base Value",
            ),
            build_ab_comparison_row(
                keys={"Metric": "Distance"},
                quantity_a=None,
                quantity_b=10.0,
                quantity_a_column="Build Value",
                quantity_b_column="Base Value",
            ),
        ],
        key_columns=["Metric"],
        quantity_a_column="Build Value",
        quantity_b_column="Base Value",
    )

    assert table.to_dicts() == [
        {
            "Metric": "Tours",
            "Build Value": 110.0,
            "Base Value": 100.0,
            "Difference": 10.0,
            "% Difference": "10.00%",
        },
        {
            "Metric": "Trips",
            "Build Value": 45.0,
            "Base Value": 0.0,
            "Difference": 45.0,
            "% Difference": "",
        },
        {
            "Metric": "Distance",
            "Build Value": None,
            "Base Value": 10.0,
            "Difference": None,
            "% Difference": "",
        },
    ]


def test_data_table_drops_index_columns_and_hides_pandas_index() -> None:
    table = data_table(
        [
            (
                "Run",
                pl.DataFrame(
                    {
                        "index": [0],
                        "__index_level_0__": [99],
                        "metric": ["Tours"],
                        "value": [10.0],
                    }
                ),
            )
        ]
    )
    tabulator = table.objects[0]

    assert tabulator.show_index is False
    assert tabulator.value.columns.tolist() == ["metric", "value"]
    assert tabulator.titles == {"metric": "Metric", "value": "Value"}


def test_data_table_shortens_long_run_tabs_and_column_titles() -> None:
    run_label = "Regional Transportation Scenario Baseline 2050 North"
    column = "regional_transportation_scenario_comparison_measure"
    table = data_table([(run_label, pl.DataFrame({column: [1.0]}))])

    assert table._names == ["Regional Transportation…North"]
    assert table._run_label_full_titles == (run_label,)
    content = table.objects[0]
    assert run_label in content.objects[0].object
    tabulator = content.objects[1]
    assert len(tabulator.titles[column]) <= 30
    assert tabulator.header_tooltips == {
        column: "Regional Transportation Scenario Comparison Measure"
    }


def test_column_titles_for_display_humanizes_machine_column_names() -> None:
    titles = column_titles(
        [
            "id",
            "facility_type",
            "From_Node",
            "auto_vmt",
            "pm_vol",
            "nonmandatory_tour_purpose",
        ]
    )

    assert titles == {
        "id": "ID",
        "facility_type": "Facility Type",
        "From_Node": "From Node",
        "auto_vmt": "Auto VMT",
        "pm_vol": "PM Volume",
        "nonmandatory_tour_purpose": "Non-Mandatory Tour Purpose",
    }


def test_dashboard_page_phase1_convenience_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    class ProbePage(DashboardPage):
        def __init__(self) -> None:
            super().__init__(state, config)
            self.view = pn.Column()

        def _refresh(self) -> None:
            self.summary_dict = self.data.summaries(
                "population_totals",
                "missing_summary",
            )

    page = ProbePage()
    page.refresh(force=True)

    no_runs = page.no_runs_message()
    unavailable = page.summary_only_unavailable_card(summary_ids=["missing_summary"])

    assert isinstance(no_runs, pn.pane.Markdown)
    assert no_runs.object == "No runs loaded."
    assert unavailable.title == "Data Not Available"
    assert page.summary_dict["population_totals"]
    assert not page.summary_dict["missing_summary"]
