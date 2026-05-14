from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard import DashboardState
from dashboard.page_base import (
    CollectedStatePage,
    MultiSelectorComparisonPage,
    SectionSpec,
    SelectorSpec,
    SingleSelectorSummaryPage,
)
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
from dashboard.pages.long_term_choices.shadow_pricing import ShadowPricingPage
from dashboard.pages.tour_summaries.internal_external_tours import (
    InternalExternalToursPage,
)
from dashboard.pages.tour_summaries.tour_distance import TourDistancePage
from dashboard.pages.tour_summaries.tour_mode import TourModePage
from dashboard.pages.tour_summaries.tour_purpose import TourPurposePage
from dashboard.pages.tour_summaries.tour_stop_frequency import TourStopFrequencyPage
from dashboard.pages.tour_summaries.tour_time import TourTimePage
from dashboard.pages.trip_summaries.trip_mode import TripModePage
from dashboard.pages.trip_summaries.trip_stop_purpose import TripStopPurposePage
from dashboard.pages.trip_summaries.trip_stop_time import TripStopTimePage
from dashboard.pages.validation.traffic import TrafficValidationPage
from dashboard.pages.validation.transit import TransitValidationPage
from processor.summarize.cache import create_summary_run
from runtime.config import Config
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


def _summary_run_for_controller_pages():
    weighted = {
        "traffic_count_comparisons": pl.DataFrame(
            {
                "direction": ["EB", "WB"],
                "count_period": ["AM", "PM"],
                "count_location_id": ["1", "2"],
                "observed_volume": [100.0, 120.0],
                "modeled_volume": [95.0, 130.0],
            }
        ),
        "screenline_flow_comparisons": pl.DataFrame(
            {
                "direction": ["EB", "WB"],
                "count_period": ["AM", "PM"],
                "screenline_id": ["S1", "S2"],
                "observed_volume": [80.0, 90.0],
                "modeled_volume": [75.0, 92.0],
            }
        ),
        "transit_boardings_by_operator_and_technology": pl.DataFrame(
            {
                "technology": ["Bus", "Rail"],
                "operator": ["A", "B"],
                "boardings": [50.0, 75.0],
            }
        ),
        "transit_transfer_rate": pl.DataFrame(
            {
                "technology": ["Bus", "Rail"],
                "access_mode": ["Walk", "Drive"],
                "operator": ["A", "B"],
                "transfer_rate": [1.2, 0.8],
            }
        ),
        "workplace_location_employment_comparison": pl.DataFrame(
            {
                "geography_type": ["district", "taz"],
                "employment_count": [1000.0, 500.0],
                "worker_count": [950.0, 525.0],
            }
        ),
        "school_location_enrollment_comparison": pl.DataFrame(
            {
                "geography_type": ["district", "district", "taz", "taz"],
                "student_type": ["grade", "university", "grade", "university"],
                "enrollment_count": [400.0, 150.0, 200.0, 100.0],
                "student_count": [390.0, 160.0, 210.0, 90.0],
            }
        ),
    }
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label="Controller",
        run_key="controller",
        summaries_by_mode={"weighted": weighted, "unweighted": unweighted},
        source_run_dir=str(Path("C:/runs/controller")),
    )


def _summary_run_for_tour_purpose_category_pages():
    weighted = {
        "tour_category_distribution": pl.DataFrame(
            {
                "tour_category": ["mandatory", "non-mandatory"],
                "tour_count": [12.0, 8.0],
            }
        ),
        "tour_purpose_distribution": pl.DataFrame(
            {
                "tour_purpose": ["social", "shop", "work"],
                "tour_count": [5.0, 2.0, 7.0],
            }
        ),
        "tour_stop_frequency_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "work",
                    "social",
                ],
                "outbound_stop_count": [0, 1, 0, 1],
                "inbound_stop_count": [0, 1, 0, 1],
                "total_stop_count": [0, 2, 0, 2],
                "tour_count": [10.0, 4.0, 6.0, 3.0],
            }
        ),
        "atwork_subtour_frequency_distribution": pl.DataFrame(
            {
                "atwork_subtour_frequency_category": ["0", "1"],
                "atwork_subtour_count": [4.0, 2.0],
            }
        ),
        "tour_distance_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "work",
                    "social",
                ],
                "distance_bin": ["1", "2", "1", "2"],
                "tour_count": [8.0, 6.0, 5.0, 3.0],
            }
        ),
        "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
            {
                "mandatory_tour_purpose": ["work", "school"],
                "geography": ["all_geographies", "all_geographies"],
                "average_tour_distance": [8.5, 5.0],
            }
        ),
        "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
            {
                "nonmandatory_tour_purpose": ["shop", "social"],
                "geography": ["all_geographies", "all_geographies"],
                "average_tour_distance": [3.5, 4.0],
            }
        ),
        "trip_purpose_distribution": pl.DataFrame(
            {
                "trip_purpose": ["work", "shop"],
                "trip_count": [9.0, 4.0],
            }
        ),
        "stop_destination_purpose_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "work",
                    "social",
                ],
                "stop_destination_purpose": ["shop", "shop", "visit"],
                "stop_count": [4.0, 3.0, 2.0],
            }
        ),
    }
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label="Categories",
        run_key="categories",
        summaries_by_mode={"weighted": weighted, "unweighted": unweighted},
        source_run_dir=str(Path("C:/runs/categories")),
    )


def _write_category_config(tmp_path: Path) -> Config:
    config_path = tmp_path / "category_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Category Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
                "visualizer:",
                '  dashboard_title: "Category Dashboard"',
                "modes:",
                "  order:",
                "    - LEGACY_DRIVE",
                "person_types:",
                "  worker: Legacy Worker",
                "transit_subsidies:",
                '  "yes": Legacy Yes',
                "geography:",
                "  enabled: true",
                "  landuse_col: COUNTY",
                "  mapping:",
                "    A: Legacy A",
                "categories:",
                "  person_type:",
                "    mapping:",
                "      worker: Config Worker",
                "      student: Config Student",
                "    order: descending",
                "  transit_subsidy:",
                "    mapping:",
                '      "yes": Config Yes',
                '      "no": Config No',
                "  geography:",
                "    mapping:",
                "      A: Config A",
                "      B: Config B",
                "  mode:",
                "    mapping:",
                "      WALK: Walk Label",
                "      DRIVE: Drive Label",
                "    order: descending",
                "  tour_purpose:",
                "    mapping:",
                "      all_tour_purposes: Total Tours",
                "      work: Work Tours",
                "      social: Social Tours",
                "    order: ascending",
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


class _SelectorSpecTestPage(MultiSelectorComparisonPage):
    definition = None

    def __init__(self, state, config, options: list[str]) -> None:
        self._options = list(options)
        super().__init__(state, config)

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="choice",
                label="Choice",
                attr_name="choice_sel",
                options_factory=lambda page: list(page._options),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Choice",
                    options=options,
                    value=value,
                ),
            ),
        )

    def build_page(self):
        self.register_selectors(*self.selector_specs())
        return self.new_section(self.selector_row("choice"))

    def _refresh(self) -> None:
        return None


class _CountingSelect(pn.widgets.Select):
    def __init__(self, *args, **kwargs) -> None:
        self.options_assignments = 0
        super().__init__(*args, **kwargs)

    def __setattr__(self, name, value) -> None:
        if name == "options" and hasattr(self, "options_assignments"):
            self.options_assignments += 1
        super().__setattr__(name, value)


class _SelectorDependencyTestPage(MultiSelectorComparisonPage):
    definition = None

    def __init__(self, state, config) -> None:
        self.left_option_calls = 0
        self.right_option_calls = 0
        super().__init__(state, config)

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="left",
                label="Left",
                attr_name="left_sel",
                options_factory=lambda page: page._left_options(),
                widget_factory=lambda page, options, value: _CountingSelect(
                    name="Left",
                    options=options,
                    value=value,
                ),
            ),
            SelectorSpec(
                selector_id="right",
                label="Right",
                attr_name="right_sel",
                options_factory=lambda page: page._right_options(),
                option_depends_on_selectors=("left",),
                widget_factory=lambda page, options, value: _CountingSelect(
                    name="Right",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _left_options(self) -> list[str]:
        self.left_option_calls += 1
        return ["A", "B"]

    def _right_options(self) -> list[str]:
        self.right_option_calls += 1
        return ["One"] if self.left_sel.value == "A" else ["Two"]

    def build_page(self):
        self.register_selectors(*self.selector_specs())
        self.register_sections(
            SectionSpec(
                section_id="body",
                selector_ids=("left", "right"),
                render=lambda page: [pn.pane.Markdown("body")],
                attr_name="_body",
            )
        )
        return self.new_section(self.selector_row("left", "right"), self._body)


class _RenderWrapperTestPage(SingleSelectorSummaryPage):
    definition = None

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="choice",
                label="Choice",
                attr_name="choice_sel",
                options_factory=lambda page: ["All"],
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Choice",
                    options=options,
                    value=value,
                ),
            ),
        )

    def render_ready(self, summaries):
        return [pn.pane.Markdown("ready")]

    def render_body(self):
        return self.render_summary_page(
            self.render_ready,
            required_summary_ids=("missing_summary",),
        )


class _CollectedStateTestPage(CollectedStatePage):
    definition = None

    def __init__(self, state, config) -> None:
        self.collect_calls = 0
        self.base_collect_calls = 0
        self.selector_collect_calls = 0
        super().__init__(state, config)

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="choice",
                label="Choice",
                attr_name="choice_sel",
                options_factory=lambda page: list(page._current_data.get("options", ["All"])),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Choice",
                    options=options,
                    value=value,
                ),
            ),
        )

    def collect_base_state(self) -> dict[str, object]:
        self.base_collect_calls += 1
        self.collect_calls += 1
        return {"options": ["All", "One"], "base_value": self.base_collect_calls}

    def collect_selector_state(self, base_state: dict[str, object]) -> dict[str, object]:
        self.selector_collect_calls += 1
        return {
            "options": list(base_state["options"]),
            "value": self.selector_collect_calls,
            "base_value": base_state["base_value"],
        }

    def collect_page_state(self) -> dict[str, object]:
        self.collect_calls += 1
        return {"options": ["All", "One"], "value": self.collect_calls}

    def build_page(self):
        self.register_selectors(*self.selector_specs())
        self.register_sections(
            SectionSpec(
                section_id="body",
                selector_ids=("choice",),
                render=lambda page: page.render_body(),
                attr_name="_body",
            )
        )
        return self.new_section(self._body)

    def render_body(self):
        return [pn.pane.Markdown(str(self._current_data["value"]))]


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


def test_selector_spec_defaults_and_sync(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    page = _SelectorSpecTestPage(
        DashboardState(weighting_modes=config.weighting_modes),
        config,
        ["A", "B"],
    )

    assert list(page.choice_sel.options) == ["A", "B"]
    assert page.choice_sel.value == "A"

    page.choice_sel.value = "B"
    page._options = ["B", "C"]
    page.sync_registered_selectors()
    assert list(page.choice_sel.options) == ["B", "C"]
    assert page.choice_sel.value == "B"

    page._options = ["C", "D"]
    page.sync_registered_selectors()
    assert list(page.choice_sel.options) == ["C", "D"]
    assert page.choice_sel.value == "C"


def test_category_specs_override_legacy_labels_and_preserve_order(tmp_path: Path) -> None:
    config = _write_category_config(tmp_path)

    assert config.person_type_label("worker") == "Config Worker"
    assert config.transit_subsidy_label("yes") == "Config Yes"
    assert config.apply_geo_mapping(pl.Series(["A", "B"])).to_list() == [
        "Config A",
        "Config B",
    ]
    assert config.ordered_modes(["DRIVE", "WALK", "BIKE"]) == ["WALK", "DRIVE", "BIKE"]
    assert config.ordered_values("tour_purpose", ["social", "shop", "work"]) == [
        "work",
        "social",
        "shop",
    ]


def test_summary_selection_lookups_use_state_cache(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_full_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    first = state.inspect_summary_table("daily_activity_pattern_by_person_type")
    second = state.inspect_summary_table("daily_activity_pattern_by_person_type")
    summary_table_set = state.get_summary_table_set("daily_activity_pattern_by_person_type")

    assert first is second
    assert summary_table_set is not None
    assert state.cache_stats["summary_selection"] == {"hits": 2, "misses": 1}
    assert state.cache_stats["summary_table_set"] == {"hits": 0, "misses": 1}


def test_summary_column_values_use_union_cache(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[
            create_summary_run(
                label="Base",
                run_key="base",
                summaries_by_mode={
                    "weighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": ["eatout", "all_tour_purposes"],
                                "tour_mode": ["DRIVE", "all_tour_modes"],
                                "trip_mode": ["DRIVEALONE", "WALK"],
                                "trip_count": [2.0, 1.0],
                            }
                        )
                    },
                    "unweighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": ["eatout", "all_tour_purposes"],
                                "tour_mode": ["DRIVE", "all_tour_modes"],
                                "trip_mode": ["DRIVEALONE", "WALK"],
                                "trip_count": [1.0, 1.0],
                            }
                        )
                    },
                },
                source_run_dir="C:/runs/base",
            ),
            create_summary_run(
                label="Build",
                run_key="build",
                summaries_by_mode={
                    "weighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": ["social", "all_tour_purposes"],
                                "tour_mode": ["WALK", "all_tour_modes"],
                                "trip_mode": ["WALK", "WALK"],
                                "trip_count": [3.0, 1.0],
                            }
                        )
                    },
                    "unweighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": ["social", "all_tour_purposes"],
                                "tour_mode": ["WALK", "all_tour_modes"],
                                "trip_mode": ["WALK", "WALK"],
                                "trip_count": [1.0, 1.0],
                            }
                        )
                    },
                },
                source_run_dir="C:/runs/build",
            ),
        ],
        weighting_modes=config.weighting_modes,
    )

    first = state.get_summary_column_values(
        "trip_mode_by_tour_purpose_and_tour_mode",
        "tour_purpose",
    )
    second = state.get_summary_column_values(
        "trip_mode_by_tour_purpose_and_tour_mode",
        "tour_purpose",
    )

    assert first == ["eatout", "all_tour_purposes", "social"]
    assert second == first
    assert state.cache_stats["summary_column_values"] == {"hits": 1, "misses": 1}


def test_selector_sync_recomputes_only_dependent_options(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    page = _SelectorDependencyTestPage(
        DashboardState(weighting_modes=config.weighting_modes),
        config,
    )

    page.refresh(force=True)
    assert page.left_option_calls == 2
    assert page.right_option_calls == 2

    left_assignments = page.left_sel.options_assignments
    right_assignments = page.right_sel.options_assignments
    left_calls = page.left_option_calls
    right_calls = page.right_option_calls
    page.left_sel.value = "B"

    assert page.left_option_calls == left_calls
    assert page.right_option_calls == right_calls + 1
    assert page.left_sel.options_assignments == left_assignments
    assert page.right_sel.options_assignments == right_assignments + 1


def test_selector_sync_skips_reassigning_unchanged_options(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    test_page = _SelectorDependencyTestPage(
        DashboardState(weighting_modes=config.weighting_modes),
        config,
    )
    initial_assignments = test_page.left_sel.options_assignments
    test_page.sync_registered_selectors("left")
    assert test_page.left_sel.options_assignments == initial_assignments


def test_render_summary_page_handles_no_runs_and_missing_summary(tmp_path: Path) -> None:
    config = _write_config(tmp_path)

    no_run_page = _RenderWrapperTestPage(
        DashboardState(weighting_modes=config.weighting_modes),
        config,
    )
    no_run_result = no_run_page.render_body()
    assert len(no_run_result) == 1
    assert "No runs loaded." in no_run_result[0].object

    missing_summary_page = _RenderWrapperTestPage(
        DashboardState(summary_runs=[_full_summary_run()], weighting_modes=config.weighting_modes),
        config,
    )
    missing_result = missing_summary_page.render_body()
    assert len(missing_result) == 1
    assert getattr(missing_result[0], "title", "") == "Data Not Available"


def test_collected_state_page_recomputes_only_during_refresh(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    page = _CollectedStateTestPage(
        DashboardState(summary_runs=[_full_summary_run()], weighting_modes=config.weighting_modes),
        config,
    )

    assert page.collect_calls == 0
    page.refresh(force=True)
    assert page.collect_calls == 1
    assert page.base_collect_calls == 1
    assert page.selector_collect_calls == 1
    first_state = dict(page._current_data)
    page.render_body()
    assert page.collect_calls == 1
    assert page._current_data == first_state
    page.choice_sel.value = "One"
    assert page.base_collect_calls == 1
    assert page.selector_collect_calls == 2


def test_refresh_summary_bundle_reuses_summary_within_refresh_cycle(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    page = _RenderWrapperTestPage(
        DashboardState(summary_runs=[_full_summary_run()], weighting_modes=config.weighting_modes),
        config,
    )

    page.begin_refresh_context()
    try:
        first = page.get_refresh_summary(
            "daily_activity_pattern_by_person_type",
            optional=True,
        )
        second = page.get_refresh_summary(
            "daily_activity_pattern_by_person_type",
            optional=True,
        )
    finally:
        page.end_refresh_context()

    assert first is second


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

    trip_mode_page = TripModePage(state, config)
    trip_mode_page.refresh(force=True)
    assert list(trip_mode_page.tour_purpose_sel.options) == ["All", "eatout", "social"]

    controller_state = DashboardState(
        summary_runs=[_summary_run_for_controller_pages()],
        weighting_modes=config.weighting_modes,
    )
    traffic_page = TrafficValidationPage(controller_state, config)
    traffic_page.refresh(force=True)
    assert list(traffic_page.direction_sel.options) == ["All", "EB", "WB"]
    assert list(traffic_page.count_period_sel.options) == ["All", "AM", "PM"]

    transit_page = TransitValidationPage(controller_state, config)
    transit_page.refresh(force=True)
    assert list(transit_page.technology_sel.options) == ["All", "Bus", "Rail"]
    assert list(transit_page.access_mode_sel.options) == ["All", "Drive", "Walk"]

    shadow_page = ShadowPricingPage(controller_state, config)
    shadow_page.refresh(force=True)
    assert list(shadow_page.geo_level_sel.options) == ["All", "district", "taz"]
    assert list(shadow_page.student_type_sel.options) == ["All", "grade", "university"]


def test_trip_mode_selector_uses_union_across_runs_and_zero_fills_missing_run(
    tmp_path: Path,
) -> None:
    config = _write_category_config(tmp_path)
    state = DashboardState(
        summary_runs=[
            create_summary_run(
                label="Base",
                run_key="base",
                summaries_by_mode={
                    "weighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": [
                                    "work",
                                    "all_tour_purposes",
                                ],
                                "tour_mode": [
                                    "all_tour_modes",
                                    "all_tour_modes",
                                ],
                                "trip_mode": ["DRIVE", "DRIVE"],
                                "trip_count": [5.0, 5.0],
                            }
                        )
                    },
                    "unweighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": ["work", "all_tour_purposes"],
                                "tour_mode": ["all_tour_modes", "all_tour_modes"],
                                "trip_mode": ["DRIVE", "DRIVE"],
                                "trip_count": [2.0, 2.0],
                            }
                        )
                    },
                },
                source_run_dir="C:/runs/base",
            ),
            create_summary_run(
                label="Build",
                run_key="build",
                summaries_by_mode={
                    "weighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": [
                                    "social",
                                    "all_tour_purposes",
                                ],
                                "tour_mode": [
                                    "all_tour_modes",
                                    "all_tour_modes",
                                ],
                                "trip_mode": ["WALK", "WALK"],
                                "trip_count": [7.0, 7.0],
                            }
                        )
                    },
                    "unweighted": {
                        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                            {
                                "tour_purpose": ["social", "all_tour_purposes"],
                                "tour_mode": ["all_tour_modes", "all_tour_modes"],
                                "trip_mode": ["WALK", "WALK"],
                                "trip_count": [3.0, 3.0],
                            }
                        )
                    },
                },
                source_run_dir="C:/runs/build",
            ),
        ],
        weighting_modes=config.weighting_modes,
    )

    page = TripModePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == [
        "Total Tours",
        "Work Tours",
        "Social Tours",
    ]
    page.tour_purpose_sel.value = "Social Tours"
    summary = page.get_refresh_summary(
        "trip_mode_by_tour_purpose_and_tour_mode",
        optional=True,
    )
    assert summary is not None
    from dashboard.pages.trip_summaries.trip_mode import _filtered_trip_mode_data

    filtered = _filtered_trip_mode_data(
        summary,
        page._tour_purpose_to_raw["Social Tours"],
    )
    assert [label for label, _ in filtered] == ["Base", "Build"]
    assert filtered[0][1]["trip_count"].sum() == 0.0
    assert filtered[1][1]["trip_count"].sum() == 7.0


def test_tour_purpose_pages_apply_shared_category_mapping(tmp_path: Path) -> None:
    config = _write_category_config(tmp_path)
    state = DashboardState(
        summary_runs=[_summary_run_for_tour_purpose_category_pages()],
        weighting_modes=config.weighting_modes,
    )

    tour_purpose_page = TourPurposePage(state, config)
    tour_purpose_page.refresh(force=True)
    purpose_chart = tour_purpose_page._body.objects[0].objects[1]
    assert list(purpose_chart.object.layout.xaxis.categoryarray) == [
        "Work Tours",
        "Social Tours",
        "shop",
    ]

    tour_stop_frequency_page = TourStopFrequencyPage(state, config)
    tour_stop_frequency_page.refresh(force=True)
    assert list(tour_stop_frequency_page.purpose_sel.options) == [
        "Total Tours",
        "Work Tours",
        "Social Tours",
    ]

    tour_distance_page = TourDistancePage(state, config)
    tour_distance_page.refresh(force=True)
    assert list(tour_distance_page.tour_purpose_sel.options) == [
        "Total Tours",
        "Work Tours",
        "Social Tours",
    ]

    trip_stop_purpose_page = TripStopPurposePage(state, config)
    trip_stop_purpose_page.refresh(force=True)
    assert list(trip_stop_purpose_page.tour_purpose_sel.options) == [
        "Total Tours",
        "Work Tours",
        "Social Tours",
    ]


def test_individual_choices_page_keeps_person_type_options(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        summary_runs=[_summary_run_with_individual_choices()],
        weighting_modes=config.weighting_modes,
    )

    page = IndividualChoicesPage(state, config)
    page.refresh(force=True)

    assert list(page.person_type_sel.options) == ["Total", "student", "worker"]
