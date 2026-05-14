from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard import DashboardState
from dashboard.pages._shared.geography import (
    filter_geo_level,
    geo_level_options,
    normalize_geography_columns,
)
from dashboard.pages._shared.person_types import (
    filter_person_type_runs,
    person_type_display_mapping,
)
from dashboard.pages._shared.purposes import raw_tour_purpose, tour_purpose_options
from dashboard.pages._shared.time_distance import (
    distance_bin_sort_expr,
    duration_hours,
    time_label,
)
from dashboard.pages.daily_travel.daily_activity_pattern import DailyActivityPatternPage
from dashboard.pages.long_term_choices.individual_choices import IndividualChoicesPage
from dashboard.pages.long_term_choices.mandatory_location_choice import (
    MandatoryLocationChoicePage,
)
from dashboard.pages.tour_summaries.internal_external_tours import (
    InternalExternalToursPage,
)
from dashboard.pages.tour_summaries.tour_time import TourTimePage
from dashboard.pages.trip_summaries.trip_stop_time import TripStopTimePage
from processor.summarize.cache import create_summary_run
from test_export_html import _full_summary_run, _scale_table, _write_config


class _StubConfig:
    def person_type_label(self, value) -> str:
        return {
            "worker": "Worker",
            "student": "Student",
        }.get(str(value), str(value))


def _summary_run_with_individual_choices():
    base_run = _full_summary_run()
    weighted = dict(base_run.summaries_by_mode["weighted"])
    weighted["license_holding_status_distribution"] = pl.DataFrame(
        {
            "person_type": ["all_person_types", "worker", "student"],
            "license_holding_status": ["has_license", "has_license", "no_license"],
            "person_count": [10.0, 6.0, 4.0],
            "pct": [50.0, 60.0, 40.0],
        }
    )
    weighted["bicycle_comfort_level_distribution"] = pl.DataFrame(
        {
            "person_type": ["all_person_types", "worker", "student"],
            "bicycle_comfort_level": ["1", "2", "4"],
            "person_count": [10.0, 6.0, 4.0],
            "pct": [50.0, 60.0, 40.0],
        }
    )
    weighted["transit_pass_ownership_by_person_type"] = pl.DataFrame(
        {
            "person_type": ["all_person_types", "worker", "student"],
            "transit_pass_ownership_status": ["yes", "yes", "no"],
            "person_count": [10.0, 6.0, 4.0],
            "pct": [50.0, 60.0, 40.0],
        }
    )
    weighted["transit_subsidy_by_person_type"] = pl.DataFrame(
        {
            "person_type": ["all_person_types", "worker", "student"],
            "transit_subsidy_status": ["full", "full", "none"],
            "person_count": [10.0, 6.0, 4.0],
            "pct": [50.0, 60.0, 40.0],
        }
    )
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label=base_run.label,
        run_key=base_run.run_key,
        summaries_by_mode={"weighted": weighted, "unweighted": unweighted},
        source_run_dir=base_run.source_run_dir,
    )


def _summary_run_with_internal_external_tours():
    base_run = _full_summary_run()
    weighted = dict(base_run.summaries_by_mode["weighted"])
    weighted["internal_external_nonmandatory_tour_frequency_by_home_geography"] = (
        pl.DataFrame(
            {
                "geography_type": ["Urban", "Suburban"],
                "tour_class": ["Internal", "External"],
                "tour_count": [10.0, 4.0],
            }
        )
    )
    weighted["external_nonmandatory_tour_locations"] = pl.DataFrame(
        {
            "geography_type": ["Urban", "Suburban"],
            "destination": ["Downtown", "Mall"],
            "tour_count": [6.0, 3.0],
        }
    )
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label=base_run.label,
        run_key=base_run.run_key,
        summaries_by_mode={"weighted": weighted, "unweighted": unweighted},
        source_run_dir=base_run.source_run_dir,
    )


def test_tour_purpose_helpers_preserve_total_mapping() -> None:
    data = [
        (
            "Base",
            pl.DataFrame({"tour_purpose": ["all_tour_purposes", "work", "school"]}),
        )
    ]

    assert tour_purpose_options(data) == ["Total", "school", "work"]
    assert raw_tour_purpose("Total") == "all_tour_purposes"


def test_time_and_distance_helpers_match_existing_behavior() -> None:
    assert time_label(1, 48) == "03:00"
    assert time_label(2, 24) == "04:00"
    assert duration_hours(3, 48) == 1.5
    assert duration_hours(3, 24) == 3.0

    df = (
        pl.DataFrame({"distance_bin": ["40+", "2", "10"]})
        .with_columns(distance_bin_sort_expr("distance_bin").alias("_sort"))
        .sort("_sort")
    )
    assert df["distance_bin"].to_list() == ["2", "10", "40+"]


def test_person_type_helpers_preserve_total_and_filtering() -> None:
    options, mapping = person_type_display_mapping(
        ["all_person_types", "worker", "student"],
        _StubConfig(),
    )
    assert options == ["Total", "Worker", "Student"]
    assert mapping == {
        "Total": "all_person_types",
        "Worker": "worker",
        "Student": "student",
    }

    filtered = filter_person_type_runs(
        [
            (
                "Base",
                pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker", "student"],
                        "person_count": [10.0, 6.0, 4.0],
                    }
                ),
            )
        ],
        None,
    )
    assert filtered[0][1]["person_type"].to_list() == ["worker", "student"]


def test_geography_helpers_preserve_renames_and_filters() -> None:
    normalized = normalize_geography_columns(
        pl.DataFrame(
            {
                "geography_type": ["district", "taz"],
                "geography_id": ["all_geographies", "101"],
            }
        )
    )
    assert normalized.columns == ["geography_level", "geography"]

    data = [("Base", normalized)]
    assert geo_level_options(data) == ["All", "district", "taz"]

    filtered = filter_geo_level(data, "district")
    assert filtered[0][1]["geography_level"].to_list() == ["district"]


def test_pages_keep_expected_selector_options_after_shared_helper_refactor(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    state = DashboardState(summary_runs=[_full_summary_run()], weighting_modes=config.weighting_modes)
    daily_page = DailyActivityPatternPage(state, config)
    daily_page.refresh(force=True)
    assert list(daily_page.person_type_sel.options) == ["Total", "worker"]

    tour_time_page = TourTimePage(state, config)
    tour_time_page.refresh(force=True)
    assert list(tour_time_page.purpose_sel.options) == ["Total", "work"]

    trip_stop_time_page = TripStopTimePage(state, config)
    trip_stop_time_page.refresh(force=True)
    assert list(trip_stop_time_page.tour_purpose_sel.options) == [
        "Total",
        "eatout",
        "social",
    ]

    int_ext_state = DashboardState(
        summary_runs=[_summary_run_with_internal_external_tours()],
        weighting_modes=config.weighting_modes,
    )
    int_ext_page = InternalExternalToursPage(int_ext_state, config)
    int_ext_page.refresh(force=True)
    assert list(int_ext_page.geo_level_sel.options) == ["All", "Suburban", "Urban"]

    mandatory_page = MandatoryLocationChoicePage(state, config)
    mandatory_page.refresh(force=True)
    assert list(mandatory_page.geo_level_sel.options) == ["Suburban", "Urban"]


def test_individual_choices_page_keeps_person_type_options(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_summary_run_with_individual_choices()],
        weighting_modes=config.weighting_modes,
    )

    page = IndividualChoicesPage(state, config)
    page.refresh(force=True)

    assert list(page.person_type_sel.options) == ["Total", "student", "worker"]
