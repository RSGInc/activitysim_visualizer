from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.pages.destination import DestinationPage
from dashboard.pages.long_term import LongTermPage
from dashboard.pages.overview import OverviewPage
from dashboard.pages.stop_freq import StopFreqPage
from dashboard.pages.stop_location import StopLocationPage
from dashboard.pages.stop_timing import StopTimingPage
from dashboard.pages.tour_mode import TourModePage
from dashboard.pages.tour_summary import TourSummaryPage
from dashboard.pages.tour_tod import TourTODPage
from dashboard.pages.trip_mode import TripModePage
from dashboard.data_access import DashboardRawRunProvider
from dashboard.state import DashboardState
from summarize.cache import (
    SummaryCacheError,
    build_run_keys,
    create_summary_run,
    load_summary_run_cache,
    write_summary_run_cache,
)
from runtime.config import Config
from runtime.models import RunData


def _write_config(tmp_path: Path) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
                "visualizer:",
                '  dashboard_title: "Test Dashboard"',
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


def _sample_summary_run() -> object:
    weighted = {
        "destination_distance": pl.DataFrame(
            {
                "purpose": ["All NM", "All NM", "shopping", "shopping"],
                "distbin": [0, 1, 0, 1],
                "freq": [5.0, 7.5, 2.0, 4.0],
            }
        ),
        "destination_average_distance": pl.DataFrame(
            {
                "purpose": ["shopping"],
                "avg_distance": [3.25],
            }
        ),
        "geo_flows": pl.DataFrame(),
    }
    unweighted = {
        "destination_distance": pl.DataFrame(
            {
                "purpose": ["All NM", "All NM", "shopping", "shopping"],
                "distbin": [0, 1, 0, 1],
                "freq": [2.0, 3.0, 1.0, 2.0],
            }
        ),
        "destination_average_distance": pl.DataFrame(
            {
                "purpose": ["shopping"],
                "avg_distance": [2.5],
            }
        ),
        "geo_flows": pl.DataFrame(),
    }
    return create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": unweighted,
        },
        source_run_dir=str(Path("C:/runs/base")),
    )


def _summary_run_with_tables(
    *,
    label: str,
    weighted: dict[str, pl.DataFrame],
    unweighted: dict[str, pl.DataFrame] | None = None,
) -> object:
    return create_summary_run(
        label=label,
        run_key=label.lower(),
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": weighted if unweighted is None else unweighted,
        },
        source_run_dir=str(Path(f"C:/runs/{label.lower()}")),
    )


def _destination_raw_run() -> RunData:
    tours = pl.DataFrame(
        {
            "tour_category": ["non-mandatory", "non-mandatory", "joint"],
            "primary_purpose": [1, 2, 2],
            "tour_type": ["eatout", "social", "social"],
            "SKIMDIST": [3.0, 5.0, 4.0],
            "finalweight": [1.0, 2.0, 1.5],
            "NUMBER_HH": [1, 1, 2],
        }
    )
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=tours,
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_build_run_keys_handles_case_insensitive_collisions() -> None:
    assert build_run_keys(["Base", "base", "Build"]) == ["base-1", "base-2", "build"]


def test_summary_cache_round_trip_creates_configured_layout(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    fingerprint = {"label": "Base", "run_dir": "C:/runs/base"}

    cache_dir = write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
    )

    assert cache_dir == Path(config.summary_root) / "base"
    assert cache_dir.exists()
    assert (cache_dir / "manifest.json").exists()
    assert (cache_dir / "weighted" / "destinationDistByPurpose.csv").exists()
    assert (cache_dir / "unweighted" / "destinationAvgDistance.csv").exists()

    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=[
            "destination_distance",
            "destination_average_distance",
            "geo_flows",
        ],
        expected_summary_config_digest=config.summary_config_digest,
        expected_run_fingerprint=fingerprint,
        expected_label="Base",
        expected_run_key="base",
    )

    assert loaded.label == "Base"
    assert loaded.run_key == "base"
    assert loaded.summaries_by_mode["weighted"]["destination_distance"].to_dicts() == [
        {"purpose": "All NM", "distbin": 0, "freq": 5.0},
        {"purpose": "All NM", "distbin": 1, "freq": 7.5},
        {"purpose": "shopping", "distbin": 0, "freq": 2.0},
        {"purpose": "shopping", "distbin": 1, "freq": 4.0},
    ]
    assert loaded.summaries_by_mode["weighted"]["geo_flows"].width == 0


def test_summary_cache_ignores_presentation_only_config_changes(
    tmp_path: Path,
) -> None:
    config_a_path = tmp_path / "a" / "config.yaml"
    config_a_path.parent.mkdir(parents=True, exist_ok=True)
    config_a_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
                "visualizer:",
                '  dashboard_title: "Dashboard A"',
                "  dashboard_pages:",
                "    - overview",
                "    - destination",
                "  export_html:",
                "    dashboard:",
                "      weighting: all",
                "    pages:",
                "      destination: {}",
                "      overview: {}",
            ]
        ),
        encoding="utf-8",
    )
    config_b_path = tmp_path / "b" / "config.yaml"
    config_b_path.parent.mkdir(parents=True, exist_ok=True)
    config_b_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
                "visualizer:",
                '  dashboard_title: "Dashboard B"',
                "  dashboard_pages:",
                "    - destination",
                "    - overview",
                "  export_html:",
                "    dashboard:",
                "      values: all",
                "    pages:",
                "      overview: {}",
                "      destination:",
                "        purpose: all",
            ]
        ),
        encoding="utf-8",
    )
    config_a = Config.from_yaml(config_a_path)
    config_b = Config.from_yaml(config_b_path)
    summary_run = _sample_summary_run()
    fingerprint = {"label": "Base", "run_dir": "C:/runs/base"}

    cache_dir = write_summary_run_cache(summary_run, config_a, run_fingerprint=fingerprint)

    loaded = load_summary_run_cache(
        cache_dir,
        config_b,
        expected_modes=config_b.weighting_modes,
        expected_summary_ids=[
            "destination_distance",
            "destination_average_distance",
            "geo_flows",
        ],
        expected_summary_config_digest=config_b.summary_config_digest,
        expected_run_fingerprint=fingerprint,
        expected_label="Base",
        expected_run_key="base",
    )

    assert loaded.label == "Base"


def test_summary_cache_invalidates_when_summary_affecting_config_changes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path / "base")
    changed_path = tmp_path / "changed" / "config.yaml"
    changed_path.parent.mkdir(parents=True, exist_ok=True)
    changed_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "visualizer:",
                '  dashboard_title: "Test Dashboard"',
            ]
        ),
        encoding="utf-8",
    )
    changed_config = Config.from_yaml(changed_path)
    summary_run = _sample_summary_run()
    fingerprint = {"label": "Base", "run_dir": "C:/runs/base"}

    cache_dir = write_summary_run_cache(summary_run, config, run_fingerprint=fingerprint)

    with pytest.raises(
        SummaryCacheError,
        match="summary config digest mismatch|missing weighting modes",
    ):
        load_summary_run_cache(
            cache_dir,
            changed_config,
            expected_modes=changed_config.weighting_modes,
            expected_summary_ids=[
                "destination_distance",
                "destination_average_distance",
                "geo_flows",
            ],
            expected_summary_config_digest=changed_config.summary_config_digest,
            expected_run_fingerprint=fingerprint,
            expected_label="Base",
            expected_run_key="base",
        )


def test_destination_page_can_render_from_cached_summaries_only(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM", "shopping"]
    assert page._body.objects


def test_destination_page_avoids_string_vs_int_purpose_mismatch_from_cached_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "destination_distance": pl.DataFrame(
                {
                    "purpose": ["All NM", "All NM", "1", "1"],
                    "distbin": [0, 1, 0, 1],
                    "freq": [5.0, 7.5, 2.0, 4.0],
                }
            ),
            "destination_average_distance": pl.DataFrame(
                {
                    "purpose": [1],
                    "avg_distance": [3.25],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM", "1"]
    assert page._body.objects


def test_destination_page_shows_data_unavailable_when_only_raw_runs_are_loaded(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        weighting_modes=config.weighting_modes,
        raw_run_provider=DashboardRawRunProvider.loaded([("Base", _destination_raw_run())]),
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM"]
    assert len(page._body.objects) == 1
    assert isinstance(page._body.objects[0], pn.Card)
    assert page._body.objects[0].title == "Data Not Available"


def test_destination_page_ignores_raw_runs_and_uses_summary_purpose_discovery(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "destination_distance": pl.DataFrame(
                {
                    "purpose": ["All NM", "All NM", "1", "1"],
                    "distbin": [0, 1, 0, 1],
                    "freq": [5.0, 7.5, 2.0, 4.0],
                }
            ),
            "destination_average_distance": pl.DataFrame(
                {
                    "purpose": [1],
                    "avg_distance": [3.25],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
        raw_run_provider=DashboardRawRunProvider.loaded([("Base", _destination_raw_run())]),
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM", "1"]
    assert page._body.objects


def test_stop_frequency_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    stop_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_stop_frequency_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["eatout", "eatout", "social"],
                    "outbound_stop_count": [0, 1, 0],
                    "inbound_stop_count": [0, 0, 1],
                    "total_stop_count": [0, 1, 1],
                    "tour_count": [10.0, 5.0, 8.0],
                }
            ),
            "stop_destination_purpose_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["eatout", "eatout", "social"],
                    "stop_destination_purpose": ["shop", "eat", "visit"],
                    "stop_count": [4.0, 6.0, 8.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[stop_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = StopFreqPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["Total", "eatout", "social"]
    page.purp_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects


def test_trip_mode_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    trip_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                {
                    "tour_purpose": [
                        "eatout",
                        "eatout",
                        "social",
                        "social",
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "eatout",
                        "social",
                        "all_tour_purposes",
                    ],
                    "tour_mode": [
                        "DRIVE",
                        "WALK",
                        "DRIVE",
                        "WALK",
                        "DRIVE",
                        "WALK",
                        "all_tour_modes",
                        "all_tour_modes",
                        "all_tour_modes",
                    ],
                    "trip_mode": [
                        "DRIVEALONE",
                        "WALK",
                        "SHARED",
                        "WALK",
                        "DRIVEALONE",
                        "WALK",
                        "DRIVEALONE",
                        "SHARED",
                        "WALK",
                    ],
                    "trip_count": [10.0, 2.0, 5.0, 3.0, 15.0, 5.0, 10.0, 5.0, 5.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[trip_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TripModePage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["Total", "eatout", "social"]
    assert list(page.tmode_sel.options) == ["All", "DRIVE", "WALK"]
    page.purp_sel.value = "social"
    page.tmode_sel.value = "WALK"
    page.refresh(force=True)
    assert page._body.objects


def test_stop_timing_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    timing_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "trip_departure_time_by_purpose": pl.DataFrame(
                {
                    "tour_purpose": [
                        "eatout",
                        "eatout",
                        "social",
                        "social",
                        "all_tour_purposes",
                        "all_tour_purposes",
                    ],
                    "time_bin": [1, 2, 1, 2, 1, 2],
                    "departure_trip_count": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
                    "departure_stop_count": [3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[timing_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = StopTimingPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["Total", "eatout", "social"]
    page.purp_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects


def test_stop_location_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    location_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "stop_out_of_direction_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "eatout",
                        "eatout",
                        "social",
                        "social",
                    ],
                    "distance_bin": [0, 1, 0, 1, 0, 1],
                    "stop_count": [13.0, 11.0, 8.0, 4.0, 5.0, 7.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[location_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = StopLocationPage(state, config)
    page.refresh(force=True)

    assert len(page._body.objects) == 4


def test_tour_summary_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    tour_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "daily_activity_pattern_by_person_type": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "daily_activity_pattern": ["M", "N", "H", "M", "N"],
                    "person_count": [10.0, 8.0, 2.0, 6.0, 4.0],
                }
            ),
            "mandatory_tour_frequency_by_person_type": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "mandatory_tour_frequency": [1, 2, 1, 5],
                    "person_count": [7.0, 5.0, 4.0, 2.0],
                }
            ),
            "nonmandatory_tour_frequency_by_person_type": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "nonmandatory_tour_frequency": ["0", "1", "0", "2"],
                    "person_count": [3.0, 9.0, 2.0, 6.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[tour_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourSummaryPage(state, config)
    page.refresh(force=True)

    assert list(page.ptype_sel.options) == ["Total", "worker"]
    page.ptype_sel.value = "worker"
    page.refresh(force=True)
    assert page._body.objects


def test_overview_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    overview_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "population_totals": pl.DataFrame(
                {
                    "person_count": [100.0],
                    "household_count": [40.0],
                    "tour_count": [55.0],
                    "trip_count": [120.0],
                    "stop_count": [35.0],
                }
            ),
            "person_type_distribution": pl.DataFrame(
                {
                    "person_type": ["worker", "student"],
                    "person_type_label": ["worker", "student"],
                    "person_count": [70.0, 30.0],
                }
            ),
            "household_size_distribution": pl.DataFrame(
                {
                    "household_size": [1, 2],
                    "household_count": [15.0, 25.0],
                }
            ),
            "auto_vmt_totals": pl.DataFrame({"auto_vmt": [180.0]}),
        },
    )
    state = DashboardState(
        summary_runs=[overview_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = OverviewPage(state, config)
    page.refresh(force=True)

    assert len(page._body.objects) == 8


def test_tour_mode_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    mode_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_mode_by_tour_purpose_and_auto_sufficiency": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "work",
                        "work",
                    ],
                    "tour_mode": ["DRIVE", "WALK", "DRIVE", "WALK"],
                    "tour_count_all_households": [10.0, 5.0, 7.0, 3.0],
                    "tour_count_zero_auto": [2.0, 4.0, 1.0, 2.0],
                    "tour_count_auto_deficient": [3.0, 1.0, 2.0, 1.0],
                    "tour_count_auto_sufficient": [5.0, 0.0, 4.0, 0.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[mode_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourModePage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["Total", "work"]
    page.purp_sel.value = "work"
    page.refresh(force=True)
    assert page._body.objects


def test_tour_tod_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    tod_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_time_of_day_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "work",
                        "work",
                    ],
                    "time_bin": [1, 2, 1, 2],
                    "departure_tour_count": [5.0, 6.0, 3.0, 4.0],
                    "arrival_tour_count": [4.0, 5.0, 2.0, 3.0],
                    "duration_tour_count": [2.0, 3.0, 1.0, 2.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[tod_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourTODPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["Total", "work"]
    page.purp_sel.value = "work"
    page.refresh(force=True)
    assert page._body.objects


def test_long_term_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    long_term_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "auto_ownership_distribution": pl.DataFrame(
                {
                    "household_vehicle_count": [0, 1],
                    "household_count": [12.0, 18.0],
                }
            ),
            "work_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography": ["all_geographies", "all_geographies"],
                    "person_count": [6.0, 4.0],
                }
            ),
            "university_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography": ["all_geographies", "all_geographies"],
                    "person_count": [3.0, 2.0],
                }
            ),
            "school_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography": ["all_geographies", "all_geographies"],
                    "person_count": [5.0, 1.0],
                }
            ),
            "work_from_home_rate_by_geography": pl.DataFrame(
                {
                    "geography": ["all_geographies"],
                    "worker_count": [20.0],
                    "work_from_home_worker_count": [11.0],
                }
            ),
            "telecommute_frequency_distribution": pl.DataFrame(
                {
                    "telecommute_frequency": ["never", "often"],
                    "person_count": [7.0, 5.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography": ["all_geographies"],
                    "average_tour_distance": [8.5],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[long_term_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = LongTermPage(state, config)
    page.refresh(force=True)

    assert page._body.objects
