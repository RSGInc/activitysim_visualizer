from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import (
    column_value_intersection,
    common_column_options,
    complete_category_counts,
    normalize_category_strings,
    numeric_like_sort_expr,
)
from dashboard.helpers.comparison_helpers import (
    build_base_run_percent_difference_table,
    format_percent_error_table,
    weighted_average_lookup,
)
from dashboard.helpers.geography_helpers import (
    geography_level_options,
    geography_options_for_level,
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
from dashboard.state import DashboardState
from test_export_html import _full_summary_run, _write_config


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
        category_col="bin",
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
    )
    summary = [
        (
            "Base",
            pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "district"],
                    "geography_id": ["all_geographies", "Urban", "Suburban"],
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
    district_options = geography_options_for_level("district", summary, config=config)
    flattened = export_geography_options(
        {"district": district_options, "all_geographies": ["all_geographies"]},
        config=config,
    )
    filtered = filter_geography_level(summary, "district")

    assert {"geography_level", "geography"}.issubset(normalized.columns)
    assert geo_levels == ["all_geographies", "district"]
    assert district_options == ["All", "Suburban", "Urban"]
    assert flattened == ["All", "Suburban", "Urban"]
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

    assert options == ["Total", "worker", "student"]
    assert mapping["Total"] == ALL_PERSON_TYPES
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
        category_col="purpose",
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


def test_bar_chart_omits_pct_hover_lines() -> None:
    chart = bar_chart(
        [
            (
                "Base",
                pl.DataFrame(
                    {
                        "mode": ["Walk"],
                        "trip_count": [5.0],
                        "pct": [100.0],
                    }
                ),
            )
        ],
        x_col="mode",
        y_col="trip_count",
        pct_col="pct",
        xaxis_categoryarray=["Walk", "Bike"],
    )

    hover = list(chart.object.data[0].customdata)

    assert "Pct:" not in hover[0]
    assert "Pct:" not in hover[1]


def test_dashboard_page_phase1_convenience_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    class ProbePage(DashboardPage):
        def __init__(self) -> None:
            super().__init__("Probe", state, config)
            self.view = pn.Column()

        def _refresh(self) -> None:
            self.summary_dict = self.optional_summaries_dict(
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
    assert page.summary_dict["population_totals"] is not None
    assert page.summary_dict["missing_summary"] is None
