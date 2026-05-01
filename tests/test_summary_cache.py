from __future__ import annotations

from pathlib import Path
import sys

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.components import bar_chart
from dashboard.pages.legacy.destination import DestinationPage
from dashboard.pages.legacy.long_term import LongTermPage
from dashboard.pages.long_term_choices.individual_choices import (
    IndividualChoicesPage,
)
from dashboard.pages.long_term_choices.mandatory_location_choice import (
    MandatoryLocationChoicePage,
)
from dashboard.pages.overview import OverviewPage
from dashboard.pages.legacy.stop_freq import StopFreqPage
from dashboard.pages.legacy.stop_location import StopLocationPage
from dashboard.pages.legacy.stop_timing import StopTimingPage
from dashboard.pages.legacy.tour_mode import TourModePage
from dashboard.pages.tour_summaries.tour_mode import (
    TourModePage as TourSummariesTourModePage,
)
from dashboard.pages.tour_summaries.tour_mode import _filter_col
from dashboard.pages.legacy.tour_summary import TourSummaryPage
from dashboard.pages.legacy.tour_tod import TourTODPage
from dashboard.pages.legacy.trip_mode import TripModePage
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.state import DashboardState
from processor.models import RunData
from processor.prepare.cache import build_prepared_manifest_identity
from processor.prepare.enrichment.pipeline import prepare_data
from processor.summarize import cache as summary_cache_module
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.cache import (
    SummaryCacheError,
    build_summaries_with_metadata,
    build_run_keys,
    create_summary_run,
    load_summary_run_cache,
    write_summary_run_cache,
)
from processor.summarize.schema import SUMMARY_OUTPUT_COLUMNS
from processor.summarize.summary_specs import SUMMARY_SPECS, SummarySpec
from processor.summarize.summary_specs import SUMMARY_SPEC_BY_ID
from runtime.config import Config
from processor.summarize.summaries import legacy


def _write_config(
    tmp_path: Path,
    *,
    visualizer_lines: list[str] | None = None,
) -> Config:
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
    if visualizer_lines:
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n"
            + "\n".join(f"  {line}" for line in visualizer_lines),
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


def _prepared_destination_raw_run() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [1],
                "num_workers": [1],
                "num_adults": [1],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "tour_purpose": [10],
                "primary_purpose": [10],
                "tour_type": ["eatout"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
                "origin": [10],
                "destination": [20],
                "SKIMDIST": [3.5],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _prepared_identity(
    *,
    config: Config,
    run_key: str,
    fingerprint: dict[str, object],
) -> dict[str, object]:
    return build_prepared_manifest_identity(
        run_key=run_key,
        config=config,
        run_fingerprint=fingerprint,
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
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
        ),
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
        expected_prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
        ),
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

    cache_dir = write_summary_run_cache(
        summary_run,
        config_a,
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config_a,
            run_key="base",
            fingerprint=fingerprint,
        ),
    )

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
        expected_prepared_manifest_identity=_prepared_identity(
            config=config_b,
            run_key="base",
            fingerprint=fingerprint,
        ),
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

    cache_dir = write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
        ),
    )

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
            expected_prepared_manifest_identity=_prepared_identity(
                config=changed_config,
                run_key="base",
                fingerprint=fingerprint,
            ),
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


def test_destination_page_shows_data_unavailable_when_only_prepared_runs_are_loaded(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(
        weighting_modes=config.weighting_modes,
        prepared_run_provider=DashboardPreparedRunProvider.loaded(
            [("Base", _destination_raw_run())]
        ),
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM"]
    assert len(page._body.objects) == 3
    assert sum(isinstance(obj, pn.Card) for obj in page._body.objects) == 2
    assert all(
        getattr(obj, "title", "") == "Data Not Available"
        for obj in page._body.objects
        if isinstance(obj, pn.Card)
    )


def test_destination_page_can_hide_missing_visualizations_when_configured_blank(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        visualizer_lines=["missing_data_display: blank"],
    )
    state = DashboardState(
        weighting_modes=config.weighting_modes,
        prepared_run_provider=DashboardPreparedRunProvider.loaded(
            [("Base", _destination_raw_run())]
        ),
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert any(isinstance(obj, pn.Spacer) for obj in page._body.objects)
    assert not any(isinstance(obj, pn.Card) for obj in page._body.objects)


def test_destination_page_ignores_prepared_runs_and_uses_summary_purpose_discovery(
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
        prepared_run_provider=DashboardPreparedRunProvider.loaded(
            [("Base", _destination_raw_run())]
        ),
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM", "1"]
    assert page._body.objects


def test_destination_legacy_summaries_prefer_readable_purpose_aliases(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = prepare_data(_prepared_destination_raw_run(), config)

    distance_df = legacy.distance_distribution(prepared, config)
    average_df = legacy.average_distance(prepared, config)

    assert sorted(distance_df["purpose"].unique().to_list()) == ["All NM", "eatout"]
    assert average_df["purpose"].to_list() == ["eatout"]


def test_destination_legacy_summaries_return_empty_without_canonical_purpose(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    distance_df = legacy.distance_distribution(_destination_raw_run(), config)
    average_df = legacy.average_distance(_destination_raw_run(), config)

    assert distance_df.is_empty()
    assert average_df.is_empty()


def test_prepare_data_overwrites_numeric_tour_purpose_before_destination_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = prepare_data(_prepared_destination_raw_run(), config)

    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]

    distance_df = legacy.distance_distribution(prepared, config)
    average_df = legacy.average_distance(prepared, config)

    assert sorted(distance_df["purpose"].unique().to_list()) == ["All NM", "eatout"]
    assert average_df["purpose"].to_list() == ["eatout"]


def test_registered_summary_builders_expose_contract_metadata() -> None:
    missing = [
        spec.summary_id
        for spec in SUMMARY_SPECS
        if not hasattr(spec.builder, "_summary_contract")
    ]
    assert missing == []


def test_summary_output_columns_are_derived_from_builder_contracts() -> None:
    assert SUMMARY_OUTPUT_COLUMNS["trip_mode_by_tour_purpose_and_tour_mode"] == (
        "tour_purpose",
        "tour_mode",
        "trip_mode",
        "trip_count",
    )
    assert SUMMARY_OUTPUT_COLUMNS["destination_distance"] == (
        "purpose",
        "distbin",
        "freq",
    )


def test_build_summaries_with_metadata_marks_missing_inputs_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _write_config(tmp_path)

    @summary_contract(
        schema={"value": pl.Float64},
        required_columns={"trips": ("needed",)},
    )
    def unavailable_summary(rd: RunData, config: Config) -> pl.DataFrame:
        raise AssertionError(
            "builder should not be called when prerequisites are missing"
        )

    spec = SummarySpec("probe_unavailable", "probe_unavailable", unavailable_summary)
    monkeypatch.setattr(
        summary_cache_module, "DEFAULT_SUMMARY_IDS", ["probe_unavailable"]
    )
    monkeypatch.setitem(
        summary_cache_module.SUMMARY_SPEC_BY_ID, "probe_unavailable", spec
    )

    tables, metadata = build_summaries_with_metadata(_destination_raw_run(), config)

    assert (
        tables["probe_unavailable"].schema
        == empty_summary_frame(unavailable_summary).schema
    )
    assert metadata["probe_unavailable"]["state"] == "unavailable"
    assert "missing required columns" in metadata["probe_unavailable"]["detail"]


def test_summary_cache_round_trip_preserves_summary_states_and_diagnostics(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "destination_distance": pl.DataFrame(),
                "destination_average_distance": pl.DataFrame(),
            },
            "unweighted": {
                "destination_distance": pl.DataFrame(),
                "destination_average_distance": pl.DataFrame(),
            },
        },
        summary_metadata_by_mode={
            "weighted": {
                "destination_distance": {
                    "state": "unavailable",
                    "detail": "tours (missing required columns: SKIMDIST)",
                },
                "destination_average_distance": {
                    "state": "failed",
                    "detail": "boom",
                },
            },
            "unweighted": {
                "destination_distance": {
                    "state": "unavailable",
                    "detail": "tours (missing required columns: SKIMDIST)",
                },
                "destination_average_distance": {
                    "state": "failed",
                    "detail": "boom",
                },
            },
        },
        source_run_dir="C:/runs/base",
    )
    fingerprint = {"label": "Base", "run_dir": "C:/runs/base"}

    cache_dir = write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
        ),
    )

    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=[
            "destination_distance",
            "destination_average_distance",
        ],
        expected_summary_config_digest=config.summary_config_digest,
        expected_run_fingerprint=fingerprint,
        expected_prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
        ),
        expected_label="Base",
        expected_run_key="base",
    )

    assert (
        loaded.summary_metadata_by_mode["weighted"]["destination_distance"]["state"]
        == "unavailable"
    )
    assert (
        loaded.summary_metadata_by_mode["weighted"]["destination_average_distance"][
            "state"
        ]
        == "failed"
    )
    assert loaded.manifest["failed_summaries"]["weighted"] == [
        "destination_average_distance"
    ]


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

    assert list(page.purp_sel.options) == ["Total", "eatout", "social"]
    assert page.purp_sel.value == "Total"
    assert len(page._body.objects) == 1

    page.purp_sel.value = "social"
    page.refresh(force=True)

    assert len(page._body.objects) == 1


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


def test_overview_page_skips_bad_run_for_one_visualization_but_keeps_rendering(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    base_run = _summary_run_with_tables(
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
    broken_run = _summary_run_with_tables(
        label="Build",
        weighted={
            "population_totals": pl.DataFrame(
                {
                    "person_count": [90.0],
                    "household_count": [38.0],
                    "tour_count": [50.0],
                    "trip_count": [110.0],
                    "stop_count": [30.0],
                }
            ),
            "person_type_distribution": pl.DataFrame(
                {
                    "person_type": ["worker", "student"],
                    "person_count": [60.0, 30.0],
                }
            ),
            "household_size_distribution": pl.DataFrame(
                {
                    "household_size": [1, 2],
                    "household_count": [14.0, 24.0],
                }
            ),
            "auto_vmt_totals": pl.DataFrame({"auto_vmt": [170.0]}),
        },
    )
    state = DashboardState(
        summary_runs=[base_run, broken_run],
        weighting_modes=config.weighting_modes,
    )

    page = OverviewPage(state, config)
    page.refresh(force=True)

    assert any(isinstance(obj, pn.Row) for obj in page._body.objects)
    person_type_diag = next(
        diagnostic
        for diagnostic in page.visualization_diagnostics
        if diagnostic.visualization_id == "overview_person_type_distribution"
    )
    assert person_type_diag.render_state == "partial"
    assert person_type_diag.usable_run_labels == ("Base",)
    assert person_type_diag.excluded_runs[0].label == "Build"
    assert person_type_diag.excluded_runs[0].status == "schema_mismatch"


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


def test_individual_choices_page_renders_partial_content_when_some_summaries_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "license_holding_status_distribution": empty_summary_frame(
                SUMMARY_SPEC_BY_ID["license_holding_status_distribution"].builder
            ),
            "bicycle_comfort_level_distribution": empty_summary_frame(
                SUMMARY_SPEC_BY_ID["bicycle_comfort_level_distribution"].builder
            ),
            "transit_pass_ownership_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "all_person_types"],
                    "transit_pass_ownership_status": [
                        "has_transit_pass",
                        "no_transit_pass",
                    ],
                    "person_type_label": ["All Person Types", "All Person Types"],
                    "person_count": [6.0, 4.0],
                }
            ),
            "transit_subsidy_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "all_person_types"],
                    "transit_subsidy_status": [
                        "has_transit_subsidy",
                        "no_transit_subsidy",
                    ],
                    "person_type_label": ["All Person Types", "All Person Types"],
                    "person_count": [3.0, 7.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = IndividualChoicesPage(state, config)
    page.refresh(force=True)

    cards = [
        obj
        for row in page._body.objects
        if isinstance(row, pn.Row)
        for obj in row.objects
        if isinstance(obj, pn.Card)
    ]
    assert len(cards) == 2
    assert any(isinstance(obj, pn.Row) for obj in page._body.objects)


def test_tour_summaries_tour_mode_page_renders_main_chart_without_vehicle_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
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
            "allocated_vehicle_age_by_occupancy": empty_summary_frame(
                SUMMARY_SPEC_BY_ID["allocated_vehicle_age_by_occupancy"].builder
            ),
            "allocated_vehicle_fuel_type_by_occupancy": empty_summary_frame(
                SUMMARY_SPEC_BY_ID["allocated_vehicle_fuel_type_by_occupancy"].builder
            ),
            "allocated_vehicle_body_type_by_occupancy": empty_summary_frame(
                SUMMARY_SPEC_BY_ID["allocated_vehicle_body_type_by_occupancy"].builder
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourSummariesTourModePage(state, config)
    page.refresh(force=True)

    assert list(page.purpose_sel.options) == ["Total", "work"]
    assert len(page._mode_section.objects) == 3
    vehicle_cards = [
        obj
        for obj in page._vehicle_section.objects[-1].objects
        if isinstance(obj, pn.Card)
    ]
    assert len(vehicle_cards) == 3


def test_mandatory_location_choice_uses_commuting_flows_when_worker_geography_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": empty_summary_frame(
                SUMMARY_SPEC_BY_ID["internal_external_worker_by_geography"].builder
            ),
            "commuting_flows": pl.DataFrame(
                {
                    "origin_geography_type": ["maz", "maz"],
                    "origin_geography_id": ["10", "20"],
                    "destination_geography_type": ["maz", "maz"],
                    "destination_geography_id": ["30", "40"],
                    "commuter_count": [5.0, 7.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = MandatoryLocationChoicePage(state, config)
    page.refresh(force=True)

    assert list(page.geo_level_sel.options) == ["maz"]
    commuting_widget = page._commuting_flows_section.objects[0]
    assert not isinstance(commuting_widget, pn.Card)


def test_tour_mode_vehicle_filters_sort_categories_stably() -> None:
    filtered = _filter_col(
        [
            (
                "Base",
                pl.DataFrame(
                    {
                        "occupancy": ["All", "All", "All"],
                        "fuel_type": ["Hybrid", "Battery EV", "Gasoline"],
                        "vehicle_count": [3.0, 1.0, 2.0],
                    }
                ),
            )
        ],
        "occupancy",
        "All",
    )

    assert filtered[0][1]["fuel_type"].to_list() == [
        "Battery EV",
        "Gasoline",
        "Hybrid",
    ]


def test_bar_chart_pins_category_order_from_input_sequence() -> None:
    chart = bar_chart(
        [
            (
                "Base",
                pl.DataFrame(
                    {
                        "fuel_type": ["Hybrid", "Battery EV", "Gasoline"],
                        "vehicle_count": [3.0, 1.0, 2.0],
                    }
                ),
            )
        ],
        x_col="fuel_type",
        y_col="vehicle_count",
    )

    category_array = list(chart.object.layout.xaxis.categoryarray)
    assert category_array == ["Hybrid", "Battery EV", "Gasoline"]


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
