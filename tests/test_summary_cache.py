from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl

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
from dashboard.state import DashboardState
from summarize.cache import (
    build_run_keys,
    create_summary_run,
    load_summary_run_cache,
    write_summary_run_cache,
)
from summarize.reader import Config, RunData


def _write_config(tmp_path: Path) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                'dashboard_title: "Test Dashboard"',
                "runs: []",
                "outputs:",
                "  summary_root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
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
        expected_config_digest=config.config_digest,
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


def test_destination_page_can_render_from_cached_summaries_only(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    state = DashboardState(
        runs=[],
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
        runs=[],
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
        runs=[("Base", _destination_raw_run())],
        weighting_modes=config.weighting_modes,
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
        runs=[("Base", _destination_raw_run())],
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
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
            "stop_freq": pl.DataFrame(
                {
                    "primary_purpose": [1, 1, 2],
                    "tour_type": ["eatout", "eatout", "social"],
                    "ob_stops": [0, 1, 0],
                    "ib_stops": [0, 0, 1],
                    "tot_stops": [0, 1, 1],
                    "freq": [10.0, 5.0, 8.0],
                }
            ),
            "stop_purpose_by_tour_purpose": pl.DataFrame(
                {
                    "primary_purpose": [1, 1, 2],
                    "tour_type": ["eatout", "eatout", "social"],
                    "purpose": ["shop", "eat", "visit"],
                    "freq": [4.0, 6.0, 8.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "trip_mode_profile": pl.DataFrame(
                {
                    "primary_purpose": [1, 1, 2, 2],
                    "tour_type": ["eatout", "eatout", "social", "social"],
                    "tour_mode": ["DRIVE", "WALK", "DRIVE", "WALK"],
                    "trip_mode": ["DRIVEALONE", "WALK", "SHARED", "WALK"],
                    "freq": [10.0, 2.0, 5.0, 3.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "stop_timing": pl.DataFrame(
                {
                    "primary_purpose": [1, 1, 2, 2],
                    "tour_type": ["eatout", "eatout", "social", "social"],
                    "timebin": [1, 2, 1, 2],
                    "freq_stop_dep": [3.0, 4.0, 5.0, 6.0],
                    "freq_trip_dep": [2.0, 3.0, 4.0, 5.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
        summary_runs=[timing_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = StopTimingPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["eatout", "social"]
    page.purp_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects


def test_stop_location_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    location_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "stop_location": pl.DataFrame(
                {
                    "primary_purpose": [1, 1, 2, 2],
                    "tour_type": ["eatout", "eatout", "social", "social"],
                    "distbin": [0, 1, 0, 1],
                    "freq": [8.0, 4.0, 5.0, 7.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "dap_summary": pl.DataFrame(
                {
                    "ptype": ["Total", "Total", "Total", "worker", "worker"],
                    "DAP": ["M", "N", "H", "M", "N"],
                    "freq": [10.0, 8.0, 2.0, 6.0, 4.0],
                }
            ),
            "mandatory_tour_freq": pl.DataFrame(
                {
                    "ptype": ["Total", "Total", "worker", "worker"],
                    "MTF": [1, 2, 1, 5],
                    "freq": [7.0, 5.0, 4.0, 2.0],
                }
            ),
            "indiv_nm_summary": pl.DataFrame(
                {
                    "ptype": ["Total", "Total", "worker", "worker"],
                    "nmtours": ["0", "1", "0", "2"],
                    "freq": [3.0, 9.0, 2.0, 6.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "totals": pl.DataFrame(
                {
                    "population": [100.0],
                    "households": [40.0],
                    "employment": [60.0],
                    "tours": [55.0],
                    "trips": [120.0],
                    "stops": [35.0],
                    "pmt": [250.0],
                    "vmt": [180.0],
                    "vehicle_trips": [90.0],
                }
            ),
            "person_type": pl.DataFrame(
                {
                    "ptype_name": ["worker", "student"],
                    "freq": [70.0, 30.0],
                    "pct": [70.0, 30.0],
                }
            ),
            "hh_size": pl.DataFrame(
                {
                    "HHSIZE": [1, 2],
                    "freq": [15.0, 25.0],
                    "pct": [37.5, 62.5],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "tour_mode_profile": pl.DataFrame(
                {
                    "purpose": ["Total", "Total", "work", "work"],
                    "tour_mode": ["DRIVE", "WALK", "DRIVE", "WALK"],
                    "freq_all": [10.0, 5.0, 7.0, 3.0],
                    "freq_as0": [2.0, 4.0, 1.0, 2.0],
                    "freq_as1": [3.0, 1.0, 2.0, 1.0],
                    "freq_as2": [5.0, 0.0, 4.0, 0.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "tour_tod_profiles": pl.DataFrame(
                {
                    "purpose": ["Total", "Total", "work", "work"],
                    "timebin": [1, 2, 1, 2],
                    "freq_dep": [5.0, 6.0, 3.0, 4.0],
                    "freq_arr": [4.0, 5.0, 2.0, 3.0],
                    "freq_dur": [2.0, 3.0, 1.0, 2.0],
                }
            ),
        },
    )
    state = DashboardState(
        runs=[],
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
            "auto_ownership": pl.DataFrame(
                {"HHVEH": [0, 1], "freq": [12.0, 18.0], "pct": [40.0, 60.0]}
            ),
            "tlfd_work": pl.DataFrame({"distbin": [0, 1], "Total": [6.0, 4.0]}),
            "tlfd_univ": pl.DataFrame({"distbin": [0, 1], "Total": [3.0, 2.0]}),
            "tlfd_schl": pl.DataFrame({"distbin": [0, 1], "Total": [5.0, 1.0]}),
            "wfh": pl.DataFrame({"Geography": ["Total"], "WFH": [11.0]}),
            "telecommute": pl.DataFrame(
                {"telecommute_frequency": ["never", "often"], "freq": [7.0, 5.0]}
            ),
            "mand_tour_lengths": pl.DataFrame({"segment": ["work"], "freq": [8.5]}),
        },
    )
    state = DashboardState(
        runs=[],
        summary_runs=[long_term_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = LongTermPage(state, config)
    page.refresh(force=True)

    assert page._body.objects
