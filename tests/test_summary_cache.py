from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import time

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.rendering import Plotter, RenderContext
from dashboard.pages.long_term_choices.individual_choices import (
    IndividualChoicesPage,
)
from dashboard.pages.long_term_choices.mandatory_location_choice import (
    MandatoryLocationChoicePage,
)
from dashboard.pages.long_term_choices.shadow_pricing import ShadowPricingPage
from dashboard.pages.long_term_choices.vehicle_ownership_type import (
    VehicleOwnershipTypePage,
)
from dashboard.pages.daily_travel.daily_activity_pattern import (
    DailyActivityPatternPage,
    filter_person_type_rates,
)
from dashboard.pages.daily_travel.escorted_tours import EscortedToursPage
from dashboard.pages.joint_travel import JointTravelPage
from dashboard.pages.overview import OverviewPage
from dashboard.pages.skim_summaries.trip_skims import TripSkimsPage
from dashboard.pages.skim_summaries.tour_skims import TourSkimsPage
from dashboard.pages.tour_summaries.tour_mode import (
    TourModePage as TourSummariesTourModePage,
)
from dashboard.pages.tour_summaries.tour_mode import (
    auto_sufficiency_definitions_markdown,
    vehicle_attribute_data,
)
from dashboard.pages.tour_summaries.internal_external_tours import (
    InternalExternalToursPage,
)
from dashboard.pages.tour_summaries.park_and_ride_location import (
    ParkAndRideLocationPage,
)
from dashboard.pages.tour_summaries.tour_distance import TourDistancePage
from dashboard.pages.tour_summaries.tour_purpose import TourPurposePage
from dashboard.pages.tour_summaries.tour_stop_frequency import (
    TourStopFrequencyPage,
    stop_frequency_chart_data,
)
from dashboard.pages.tour_summaries.tour_time import TourTimePage
from dashboard.pages.trip_summaries.trip_mode import TripModePage
from dashboard.pages.trip_summaries.trip_stop_purpose import TripStopPurposePage
from dashboard.pages.trip_summaries.trip_stop_distance import TripStopDistancePage
from dashboard.pages.trip_summaries.trip_stop_time import TripStopTimePage
from dashboard.pages.validation.traffic import TrafficValidationPage
from dashboard.pages.validation.transit import TransitValidationPage
from dashboard.pages.validation.regional import RegionalValidationPage
from dashboard.pages.validation.vmt import VMTValidationPage
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.state import DashboardState
from dashboard.page_registry import page_definitions_for_group
from processor.models import RunData
from processor.prepare.cache import build_prepared_manifest_identity
from processor.prepare.enrichment.pipeline import prepare_data
from processor.summarize import builder as summary_builder_module
from processor.summarize.contracts import empty_summary_frame, summary
from processor.summarize.cache import (
    build_run_fingerprint,
    build_run_keys,
    load_summary_run_cache,
    write_summary_run_cache,
)
from processor.summarize.cache_types import SummaryCacheError, create_summary_run
from processor.summarize.builder import build_summaries_with_metadata
from processor.summarize.schema import SUMMARY_OUTPUT_COLUMNS
from processor.summarize.catalog import SUMMARY_BY_ID, SUMMARY_DEFINITIONS
from runtime.config import Config
from runtime.config.models import SkimjoinSettings


def _collect_cards(viewable) -> list[pn.Card]:
    cards: list[pn.Card] = []
    if isinstance(viewable, pn.Card):
        cards.append(viewable)
    if hasattr(viewable, "objects"):
        for child in viewable.objects:
            cards.extend(_collect_cards(child))
    return cards


def _collect_plotly_panes(viewable) -> list[pn.pane.Plotly]:
    plots: list[pn.pane.Plotly] = []
    if isinstance(viewable, pn.pane.Plotly):
        plots.append(viewable)
    if hasattr(viewable, "objects"):
        for child in viewable.objects:
            plots.extend(_collect_plotly_panes(child))
    return plots


def _collect_tabulators(viewable) -> list[pn.widgets.Tabulator]:
    tables: list[pn.widgets.Tabulator] = []
    if isinstance(viewable, pn.widgets.Tabulator):
        tables.append(viewable)
    if hasattr(viewable, "objects"):
        for child in viewable.objects:
            tables.extend(_collect_tabulators(child))
    return tables


def _collect_tabs(viewable) -> list[pn.Tabs]:
    tabs: list[pn.Tabs] = []
    if isinstance(viewable, pn.Tabs):
        tabs.append(viewable)
    if hasattr(viewable, "objects"):
        for child in viewable.objects:
            tabs.extend(_collect_tabs(child))
    return tabs


def _write_config(
    tmp_path: Path,
    *,
    dashboard_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                "runs: []",
                "root: summary_cache",
                "summarize:",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
                "dashboard:",
                '  title: "Test Dashboard"',
            ]
        ),
        encoding="utf-8",
    )
    if extra_lines:
        config_path.write_text(
            config_path.read_text(encoding="utf-8") + "\n" + "\n".join(extra_lines),
            encoding="utf-8",
        )
    if dashboard_lines:
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n"
            + "\n".join(f"  {line}" for line in dashboard_lines),
            encoding="utf-8",
        )
    return Config.from_yaml(config_path)


def _sample_summary_run() -> object:
    weighted = {
        "tour_distance_by_tour_purpose": pl.DataFrame(
            {
                "distance_bin": ["0", "1", "0", "1"],
                "tour_purpose": ["all", "all", "shopping", "shopping"],
                "tour_count": [5.0, 7.5, 2.0, 4.0],
            }
        ),
        "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
            {
                "nonmandatory_tour_purpose": ["shopping"],
                "geography_type": ["all_geographies"],
                "geography_id": ["all_geographies"],
                "average_tour_distance": [3.25],
                "tour_count": [6.0],
            }
        ),
        "commuting_flows": pl.DataFrame(),
    }
    unweighted = {
        "tour_distance_by_tour_purpose": pl.DataFrame(
            {
                "distance_bin": ["0", "1", "0", "1"],
                "tour_purpose": ["all", "all", "shopping", "shopping"],
                "tour_count": [2.0, 3.0, 1.0, 2.0],
            }
        ),
        "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
            {
                "nonmandatory_tour_purpose": ["shopping"],
                "geography_type": ["all_geographies"],
                "geography_id": ["all_geographies"],
                "average_tour_distance": [2.5],
                "tour_count": [3.0],
            }
        ),
        "commuting_flows": pl.DataFrame(),
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


def _skim_summary_tables() -> tuple[dict[str, pl.DataFrame], dict[str, pl.DataFrame]]:
    weighted = {
        "skimjoin_trip_component_stats": pl.DataFrame(
            {
                "component": [
                    "skim_auto_time",
                    "skim_auto_cost",
                    "skim_auto_bonus",
                    "skim_walk_distance",
                    "skim_walk_time",
                    "skim_walk_maz_distance",
                    "skim_walk_maz_actual",
                    "skim_walk_time",
                    "skim_transit_tiv",
                    "skim_transit_tiv",
                    "skim_auto_distance",
                    "skim_school_special",
                ],
                "trip_mode": [
                    "SOV",
                    "HOV2",
                    "SOV",
                    "WALK",
                    "WALK",
                    "WALK",
                    "WALK",
                    "BIKE",
                    "WALK_TRANSIT",
                    "PNR_TRANSIT",
                    "HOV3",
                    "SCHOOLBUS",
                ],
                "n_total": [
                    10.0,
                    12.0,
                    10.0,
                    7.0,
                    7.0,
                    7.0,
                    7.0,
                    6.0,
                    8.0,
                    9.0,
                    11.0,
                    5.0,
                ],
                "n_valid": [
                    9.0,
                    11.0,
                    10.0,
                    7.0,
                    7.0,
                    7.0,
                    7.0,
                    6.0,
                    8.0,
                    9.0,
                    10.0,
                    5.0,
                ],
                "mean": [
                    15.126,
                    3.452,
                    99.111,
                    1.827,
                    12.233,
                    1.604,
                    28.06,
                    8.887,
                    34.221,
                    28.781,
                    7.004,
                    18.5,
                ],
                "std": [
                    1.554,
                    0.882,
                    9.001,
                    0.214,
                    2.104,
                    0.187,
                    3.109,
                    1.443,
                    5.115,
                    4.201,
                    0.993,
                    1.2,
                ],
                "min": [
                    11.0,
                    1.2,
                    88.0,
                    1.4,
                    8.1,
                    1.2,
                    22.0,
                    5.5,
                    20.0,
                    18.0,
                    5.0,
                    17.0,
                ],
                "max": [
                    18.5,
                    5.4,
                    110.0,
                    2.1,
                    16.8,
                    1.9,
                    35.0,
                    12.7,
                    44.0,
                    37.0,
                    8.9,
                    20.0,
                ],
                "median": [
                    15.0,
                    3.5,
                    100.0,
                    1.8,
                    12.0,
                    1.6,
                    28.0,
                    8.8,
                    34.0,
                    28.5,
                    7.0,
                    18.0,
                ],
                "mode": [
                    14.0,
                    3.0,
                    98.0,
                    1.7,
                    11.5,
                    1.5,
                    27.0,
                    8.4,
                    33.0,
                    27.0,
                    7.0,
                    18.0,
                ],
                "zero_share": [
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                ],
                "missing_share": [
                    0.1,
                    0.08,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.09,
                    0.0,
                ],
            }
        ),
        "skimjoin_tour_component_stats": pl.DataFrame(
            {
                "component": [
                    "skim_auto_time_outbound",
                    "skim_auto_time_inbound",
                    "skim_auto_cost_outbound",
                    "skim_transit_tiv_outbound",
                    "skim_transit_tiv_inbound",
                    "skim_walk_time_outbound",
                    "skim_walk_time_inbound",
                ],
                "tour_mode": [
                    "SOV",
                    "SOV",
                    "HOV2",
                    "WALK_TRANSIT",
                    "KNR_TRANSIT",
                    "WALK",
                    "WALK",
                ],
                "n_total": [5.0, 5.0, 6.0, 4.0, 4.0, 3.0, 3.0],
                "n_valid": [5.0, 4.0, 6.0, 4.0, 4.0, 3.0, 3.0],
                "mean": [25.333, 21.112, 4.557, 41.221, 39.778, 9.115, 8.441],
                "std": [2.111, 2.004, 0.631, 4.221, 3.992, 1.202, 1.103],
                "min": [21.0, 17.0, 3.4, 35.0, 34.0, 7.0, 6.7],
                "max": [29.0, 24.0, 5.3, 47.0, 45.0, 11.0, 10.2],
                "median": [25.0, 21.0, 4.5, 41.0, 40.0, 9.0, 8.5],
                "mode": [24.0, 20.0, 4.4, 40.0, 39.0, 8.9, 8.3],
                "zero_share": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "missing_share": [0.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0],
            }
        ),
    }
    unweighted = {
        summary_id: df.with_columns(
            pl.col("n_total").cast(pl.Float64) * 0.5,
            pl.col("n_valid").cast(pl.Float64) * 0.5,
        )
        for summary_id, df in weighted.items()
    }
    return weighted, unweighted


def _attach_test_skimjoin_config(
    config: Config,
    *,
    ignore_modes: list[str] | None = None,
) -> None:
    config.skimjoin = SkimjoinSettings(
        enabled=True,
        normalized_config=SimpleNamespace(
            ignore_modes=ignore_modes or [],
            trip_lookups=[
                SimpleNamespace(mode="SOV", output="skim_auto_time"),
                SimpleNamespace(mode="SOV", output="skim_auto_distance"),
                SimpleNamespace(mode="SOV", output="skim_auto_cost"),
                SimpleNamespace(mode="HOV2", output="skim_auto_time"),
                SimpleNamespace(mode="HOV2", output="skim_auto_distance"),
                SimpleNamespace(mode="HOV2", output="skim_auto_cost"),
                SimpleNamespace(mode="HOV3", output="skim_auto_time"),
                SimpleNamespace(mode="HOV3", output="skim_auto_distance"),
                SimpleNamespace(mode="HOV3", output="skim_auto_cost"),
                SimpleNamespace(mode="WALK_TRANSIT", output="skim_transit_tiv"),
                SimpleNamespace(mode="PNR_TRANSIT", output="skim_transit_tiv"),
                SimpleNamespace(mode="KNR_TRANSIT", output="skim_transit_tiv"),
                SimpleNamespace(mode="WALK", output="skim_walk_distance"),
                SimpleNamespace(mode="WALK", output="skim_walk_time"),
                SimpleNamespace(mode="WALK", output="skim_walk_maz_distance"),
                SimpleNamespace(mode="WALK", output="skim_walk_maz_actual"),
                SimpleNamespace(mode="BIKE", output="skim_walk_time"),
                SimpleNamespace(mode="SCHOOLBUS", output="skim_school_special"),
            ],
            tour_lookups=[
                SimpleNamespace(mode="SOV", output="skim_auto_time_outbound"),
                SimpleNamespace(mode="SOV", output="skim_auto_time_inbound"),
                SimpleNamespace(mode="SOV", output="skim_auto_distance_outbound"),
                SimpleNamespace(mode="SOV", output="skim_auto_distance_inbound"),
                SimpleNamespace(mode="SOV", output="skim_auto_cost_outbound"),
                SimpleNamespace(mode="SOV", output="skim_auto_cost_inbound"),
                SimpleNamespace(mode="HOV2", output="skim_auto_time_outbound"),
                SimpleNamespace(mode="HOV2", output="skim_auto_time_inbound"),
                SimpleNamespace(mode="HOV2", output="skim_auto_cost_outbound"),
                SimpleNamespace(mode="HOV2", output="skim_auto_cost_inbound"),
                SimpleNamespace(
                    mode="WALK_TRANSIT", output="skim_transit_tiv_outbound"
                ),
                SimpleNamespace(mode="KNR_TRANSIT", output="skim_transit_tiv_inbound"),
                SimpleNamespace(mode="WALK", output="skim_walk_time_outbound"),
                SimpleNamespace(mode="WALK", output="skim_walk_time_inbound"),
            ],
        ),
    )


def _skim_summary_run() -> object:
    weighted, unweighted = _skim_summary_tables()
    return _summary_run_with_tables(
        label="Base",
        weighted=weighted,
        unweighted=unweighted,
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
    source_type: str = "prepared_cache",
    prepared_table_map: dict[str, str] | None = None,
) -> dict[str, object]:
    return build_prepared_manifest_identity(
        run_key=run_key,
        config=config,
        run_fingerprint=fingerprint,
        source_type=source_type,
        prepared_table_map=prepared_table_map,
    )


def _write_custom_prepared_tables(
    root: Path,
    *,
    file_format: str = "parquet",
) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    tables = {
        "households": pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        "persons": pl.DataFrame(
            {"person_id": [10], "household_id": [1], "finalweight": [1.0]}
        ),
        "day": pl.DataFrame(
            {
                "day_id": [100],
                "person_id": [10],
                "household_id": [1],
                "finalweight": [1.0],
            }
        ),
        "tours": pl.DataFrame(
            {
                "tour_id": [100],
                "person_id": [10],
                "household_id": [1],
                "finalweight": [1.0],
            }
        ),
        "trips": pl.DataFrame(
            {
                "trip_id": [1000],
                "tour_id": [100],
                "person_id": [10],
                "finalweight": [1.0],
            }
        ),
        "vehicles": pl.DataFrame(
            {"vehicle_id": [1001], "household_id": [1], "finalweight": [1.0]}
        ),
        "joint_tour_participants": pl.DataFrame({"tour_id": [], "person_id": []}),
        "land_use": pl.DataFrame({"zone_id": [1], "TAZ": [1]}),
    }
    paths: dict[str, str] = {}
    for table_id, table in tables.items():
        path = root / f"{table_id}.{file_format}"
        if file_format == "parquet":
            table.write_parquet(path)
        else:
            table.write_csv(path)
        paths[table_id] = str(path.resolve())
    return paths


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
    assert (cache_dir / "weighted" / "tour_distance_by_tour_purpose.csv").exists()
    assert (
        cache_dir
        / "unweighted"
        / "average_nonmandatory_tour_distance_by_purpose_and_geography.csv"
    ).exists()

    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=[
            "tour_distance_by_tour_purpose",
            "average_nonmandatory_tour_distance_by_purpose_and_geography",
            "commuting_flows",
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
    assert loaded.summaries_by_mode["weighted"]["tour_distance_by_tour_purpose"].to_dicts() == [
        {"distance_bin": "0", "tour_purpose": "all", "tour_count": 5.0},
        {"distance_bin": "1", "tour_purpose": "all", "tour_count": 7.5},
        {"distance_bin": "0", "tour_purpose": "shopping", "tour_count": 2.0},
        {"distance_bin": "1", "tour_purpose": "shopping", "tour_count": 4.0},
    ]
    assert loaded.summaries_by_mode["weighted"]["commuting_flows"].is_empty()
    assert loaded.summaries_by_mode["weighted"]["commuting_flows"].columns == [
        "origin_geography_type",
        "origin_geography_id",
        "destination_geography_type",
        "destination_geography_id",
        "commuter_count",
    ]


def test_summary_cache_detects_file_map_only_run_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    fingerprint = build_run_fingerprint(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        file_map={"households": "final_households", "trips": "final_trips"},
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )

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

    with pytest.raises(SummaryCacheError, match="run fingerprint mismatch"):
        load_summary_run_cache(
            cache_dir,
            config,
            expected_modes=config.weighting_modes,
            expected_summary_ids=[
                "tour_distance_by_tour_purpose",
                "average_nonmandatory_tour_distance_by_purpose_and_geography",
                "commuting_flows",
            ],
            expected_summary_config_digest=config.summary_config_digest,
            expected_run_fingerprint=build_run_fingerprint(
                label="Base",
                run_dir="C:/runs/base",
                skim_file=None,
                file_map={"households": "final_hh", "trips": "final_trips"},
                hh_weight_col=None,
                person_weight_col=None,
                trip_weight_col=None,
            ),
            expected_prepared_manifest_identity=_prepared_identity(
                config=config,
                run_key="base",
                fingerprint=fingerprint,
            ),
            expected_label="Base",
            expected_run_key="base",
        )


def test_summary_cache_detects_fallback_file_map_only_run_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    fingerprint = build_run_fingerprint(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        file_map={"households": "final_households"},
        fallback_file_map={"land_use": "C:/shared/land_use_a.csv"},
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )

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

    with pytest.raises(SummaryCacheError, match="run fingerprint mismatch"):
        load_summary_run_cache(
            cache_dir,
            config,
            expected_modes=config.weighting_modes,
            expected_summary_ids=[
                "tour_distance_by_tour_purpose",
                "average_nonmandatory_tour_distance_by_purpose_and_geography",
                "commuting_flows",
            ],
            expected_summary_config_digest=config.summary_config_digest,
            expected_run_fingerprint=build_run_fingerprint(
                label="Base",
                run_dir="C:/runs/base",
                skim_file=None,
                file_map={"households": "final_households"},
                fallback_file_map={"land_use": "C:/shared/land_use_b.csv"},
                hh_weight_col=None,
                person_weight_col=None,
                trip_weight_col=None,
            ),
            expected_prepared_manifest_identity=_prepared_identity(
                config=config,
                run_key="base",
                fingerprint=fingerprint,
            ),
            expected_label="Base",
            expected_run_key="base",
        )


def test_summary_cache_detects_custom_prepared_table_path_or_mtime_change(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    prepared_map = _write_custom_prepared_tables(tmp_path / "prepared")
    fingerprint = build_run_fingerprint(
        label="Base",
        run_dir=None,
        skim_file=None,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )

    cache_dir = write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
            source_type="custom_prepared_table_map",
            prepared_table_map=prepared_map,
        ),
    )

    moved_households = tmp_path / "prepared_moved" / "households.parquet"
    moved_households.parent.mkdir(parents=True, exist_ok=True)
    Path(prepared_map["households"]).replace(moved_households)
    changed_path_map = dict(prepared_map)
    changed_path_map["households"] = str(moved_households)

    with pytest.raises(SummaryCacheError, match="prepared manifest identity mismatch"):
        load_summary_run_cache(
            cache_dir,
            config,
            expected_modes=config.weighting_modes,
            expected_summary_ids=[
                "tour_distance_by_tour_purpose",
                "average_nonmandatory_tour_distance_by_purpose_and_geography",
                "commuting_flows",
            ],
            expected_summary_config_digest=config.summary_config_digest,
            expected_run_fingerprint=fingerprint,
            expected_prepared_manifest_identity=_prepared_identity(
                config=config,
                run_key="base",
                fingerprint=fingerprint,
                source_type="custom_prepared_table_map",
                prepared_table_map=changed_path_map,
            ),
            expected_label="Base",
            expected_run_key="base",
        )

    prepared_map = _write_custom_prepared_tables(tmp_path / "prepared_again")
    cache_dir = write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
        prepared_manifest_identity=_prepared_identity(
            config=config,
            run_key="base",
            fingerprint=fingerprint,
            source_type="custom_prepared_table_map",
            prepared_table_map=prepared_map,
        ),
    )
    trips_path = Path(prepared_map["trips"])
    updated_ns = trips_path.stat().st_mtime_ns + 1_000_000_000
    time_s = updated_ns / 1_000_000_000
    time.sleep(0.01)
    trips_path.touch()
    import os

    os.utime(trips_path, ns=(updated_ns, updated_ns))

    with pytest.raises(SummaryCacheError, match="prepared manifest identity mismatch"):
        load_summary_run_cache(
            cache_dir,
            config,
            expected_modes=config.weighting_modes,
            expected_summary_ids=[
                "tour_distance_by_tour_purpose",
                "average_nonmandatory_tour_distance_by_purpose_and_geography",
                "commuting_flows",
            ],
            expected_summary_config_digest=config.summary_config_digest,
            expected_run_fingerprint=fingerprint,
            expected_prepared_manifest_identity=_prepared_identity(
                config=config,
                run_key="base",
                fingerprint=fingerprint,
                source_type="custom_prepared_table_map",
                prepared_table_map=prepared_map,
            ),
            expected_label="Base",
            expected_run_key="base",
        )


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
                "root: summary_cache",
                "summarize:",
                "  weighting_modes: [weighted, unweighted]",
                "dashboard:",
                '  title: "Dashboard A"',
                "  live:",
                "    pages: [overview, trip_mode]",
                "  export:",
                "    dashboard:",
                "      weighting: all",
                "    pages:",
                "      trip_mode: {}",
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
                "root: summary_cache",
                "summarize:",
                "  weighting_modes: [weighted, unweighted]",
                "dashboard:",
                '  title: "Dashboard B"',
                "  live:",
                "    pages: [trip_mode, overview]",
                "  export:",
                "    dashboard:",
                "      values: all",
                "    pages:",
                "      overview: {}",
                "      trip_mode:",
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
            "tour_distance_by_tour_purpose",
            "average_nonmandatory_tour_distance_by_purpose_and_geography",
            "commuting_flows",
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
                "root: summary_cache",
                "summarize:",
                "  weighting_modes: [weighted]",
                "dashboard:",
                '  title: "Test Dashboard"',
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
                "tour_distance_by_tour_purpose",
                "average_nonmandatory_tour_distance_by_purpose_and_geography",
                "commuting_flows",
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


def test_prepare_data_overwrites_numeric_tour_purpose_before_destination_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = prepare_data(_prepared_destination_raw_run(), config)

    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]

def test_registered_summary_builders_expose_contract_metadata() -> None:
    assert SUMMARY_DEFINITIONS
    assert all(definition.contract.schema for definition in SUMMARY_DEFINITIONS)


def test_summary_output_columns_are_derived_from_builder_contracts() -> None:
    assert SUMMARY_OUTPUT_COLUMNS["trip_mode_by_tour_purpose_and_tour_mode"] == (
        "tour_purpose",
        "tour_mode",
        "trip_mode",
        "trip_count",
    )
    assert SUMMARY_OUTPUT_COLUMNS["tour_distance_by_tour_purpose"] == (
        "distance_bin",
        "tour_purpose",
        "tour_count",
    )


def test_build_summaries_with_metadata_marks_missing_inputs_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _write_config(tmp_path)

    @summary(
        id="probe_unavailable",
        schema={"value": pl.Float64},
        required_columns={"trips": ("needed",)},
    )
    def unavailable_summary(rd: RunData, config: Config) -> pl.DataFrame:
        raise AssertionError(
            "builder should not be called when prerequisites are missing"
        )

    spec = unavailable_summary.summary_definition
    monkeypatch.setattr(
        summary_builder_module, "DEFAULT_SUMMARY_IDS", ["probe_unavailable"]
    )
    monkeypatch.setitem(SUMMARY_BY_ID, "probe_unavailable", spec)

    tables, metadata = build_summaries_with_metadata(_destination_raw_run(), config)

    assert (
        tables["probe_unavailable"].schema
        == empty_summary_frame(unavailable_summary).schema
    )
    assert metadata["probe_unavailable"]["state"] == "unavailable"
    assert "missing required columns" in metadata["probe_unavailable"]["detail"]


def test_build_summaries_with_metadata_can_fail_fast_on_builder_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _write_config(tmp_path)

    @summary(id="probe_failure", schema={"value": pl.Float64})
    def failing_summary(rd: RunData, config: Config) -> pl.DataFrame:
        raise RuntimeError("summary probe failed")

    spec = failing_summary.summary_definition
    monkeypatch.setattr(summary_builder_module, "DEFAULT_SUMMARY_IDS", ["probe_failure"])
    monkeypatch.setitem(SUMMARY_BY_ID, "probe_failure", spec)

    with pytest.raises(RuntimeError, match="summary probe failed"):
        build_summaries_with_metadata(
            _destination_raw_run(),
            config,
            raise_on_error=True,
        )


def test_summary_cache_round_trip_preserves_summary_states_and_diagnostics(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "tour_distance_by_tour_purpose": pl.DataFrame(),
                "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(),
            },
            "unweighted": {
                "tour_distance_by_tour_purpose": pl.DataFrame(),
                "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(),
            },
        },
        summary_metadata_by_mode={
            "weighted": {
                "tour_distance_by_tour_purpose": {
                    "state": "unavailable",
                    "detail": "tours (missing required columns: SKIMDIST)",
                },
                "average_nonmandatory_tour_distance_by_purpose_and_geography": {
                    "state": "failed",
                    "detail": "boom",
                },
            },
            "unweighted": {
                "tour_distance_by_tour_purpose": {
                    "state": "unavailable",
                    "detail": "tours (missing required columns: SKIMDIST)",
                },
                "average_nonmandatory_tour_distance_by_purpose_and_geography": {
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
            "tour_distance_by_tour_purpose",
            "average_nonmandatory_tour_distance_by_purpose_and_geography",
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
        loaded.summary_metadata_by_mode["weighted"]["tour_distance_by_tour_purpose"]["state"]
        == "unavailable"
    )
    assert (
        loaded.summary_metadata_by_mode["weighted"]["average_nonmandatory_tour_distance_by_purpose_and_geography"][
            "state"
        ]
        == "failed"
    )
    assert loaded.manifest["failed_summaries"]["weighted"] == [
        "average_nonmandatory_tour_distance_by_purpose_and_geography"
    ]


def test_summary_cache_writes_sentinel_csvs_for_empty_unavailable_and_failed_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "tour_distance_by_tour_purpose": pl.DataFrame(),
                "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(),
            },
            "unweighted": {
                "tour_distance_by_tour_purpose": pl.DataFrame(),
                "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(),
            },
        },
        summary_metadata_by_mode={
            "weighted": {
                "tour_distance_by_tour_purpose": {
                    "state": "unavailable",
                    "detail": "tours (missing required columns: SKIMDIST)",
                },
                "average_nonmandatory_tour_distance_by_purpose_and_geography": {
                    "state": "failed",
                    "detail": "boom",
                },
            },
            "unweighted": {
                "tour_distance_by_tour_purpose": {
                    "state": "empty",
                },
                "average_nonmandatory_tour_distance_by_purpose_and_geography": {
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

    assert (cache_dir / "weighted" / "tour_distance_by_tour_purpose.csv").read_text(
        encoding="utf-8"
    ) == "__empty__\n"
    assert (
        cache_dir
        / "weighted"
        / "average_nonmandatory_tour_distance_by_purpose_and_geography.csv"
    ).read_text(encoding="utf-8") == "__empty__\n"

    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=[
            "tour_distance_by_tour_purpose",
            "average_nonmandatory_tour_distance_by_purpose_and_geography",
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
        loaded.summaries_by_mode["weighted"]["tour_distance_by_tour_purpose"].schema
        == empty_summary_frame(
            SUMMARY_BY_ID["tour_distance_by_tour_purpose"].builder
        ).schema
    )
    assert (
        loaded.summaries_by_mode["weighted"]["average_nonmandatory_tour_distance_by_purpose_and_geography"].schema
        == empty_summary_frame(
            SUMMARY_BY_ID[
                "average_nonmandatory_tour_distance_by_purpose_and_geography"
            ].builder
        ).schema
    )


def test_tour_stop_frequency_live_page_uses_shared_summary_helpers(
    tmp_path: Path,
) -> None:
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
            "atwork_subtour_frequency_distribution": pl.DataFrame(
                {
                    "atwork_subtour_frequency_category": ["0", "1+"],
                    "atwork_subtour_count": [6.0, 4.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[stop_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourStopFrequencyPage(state, config)
    page.refresh(force=True)

    assert list(page.purpose_sel.options) == ["All Tour Purposes", "eatout", "social"]
    page.purpose_sel.value = "social"
    page.refresh(force=True)
    assert page.view.objects
    directional_rows = [
        obj
        for obj in page.render_body()
        if isinstance(obj, pn.Row)
        and sum(len(_collect_plotly_panes(child)) for child in obj.objects) == 2
    ]
    assert len(directional_rows) == 1
    directional_titles = {
        str(plot.object.layout.title.text)
        for child in directional_rows[0].objects
        for plot in _collect_plotly_panes(child)
    }
    assert {
        "Tour Stop Frequency - Purpose: social, Direction: Outbound",
        "Tour Stop Frequency - Purpose: social, Direction: Inbound",
    } == directional_titles


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

    assert list(page.tour_purpose_sel.options) == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]
    plots = _collect_plotly_panes(page._body)
    all_titles = {str(plot.object.layout.title.text) for plot in plots}
    assert "Trip Mode Distribution for All Tours" in all_titles
    assert "Trip Mode Distribution for All DRIVE Tours" in all_titles
    assert "Trip Mode Distribution for All WALK Tours" in all_titles
    page.tour_purpose_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects
    plots = _collect_plotly_panes(page._body)
    social_titles = {str(plot.object.layout.title.text) for plot in plots}
    assert "Trip Mode Distribution for social Tours" in social_titles
    assert "Trip Mode Distribution for DRIVE social Tours" in social_titles
    assert "Trip Mode Distribution for WALK social Tours" in social_titles


def test_trip_mode_selector_uses_union_across_runs_and_zero_fills_missing_modes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    run_a = _summary_run_with_tables(
        label="Base",
        weighted={
            "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                {
                    "tour_purpose": ["eatout", "all_tour_purposes"],
                    "tour_mode": ["all_tour_modes", "all_tour_modes"],
                    "trip_mode": ["WALK", "WALK"],
                    "trip_count": [2.0, 2.0],
                }
            ),
        },
    )
    run_b = _summary_run_with_tables(
        label="Build",
        weighted={
            "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                {
                    "tour_purpose": ["social", "social", "all_tour_purposes"],
                    "tour_mode": [
                        "all_tour_modes",
                        "all_tour_modes",
                        "all_tour_modes",
                    ],
                    "trip_mode": ["SHARED2", "WALK", "SHARED2"],
                    "trip_count": [5.0, 1.0, 5.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[run_a, run_b],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Count"

    page = TripModePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]
    page.tour_purpose_sel.value = "social"
    charts = page.render_body()
    overall_chart = _collect_plotly_panes(charts[0])[0]
    traces = {trace.name: trace for trace in overall_chart.object.data}

    assert set(traces) == {"Base", "Build"}
    assert list(traces["Base"].x) == ["WALK", "SHARED2"]
    assert list(traces["Base"].y) == [0.0, 0.0]
    assert list(traces["Build"].x) == ["WALK", "SHARED2"]
    assert list(traces["Build"].y) == [1.0, 5.0]


def test_trip_mode_page_uses_configured_mode_labels_on_plot_axes(
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
            "        SHARED2: Shared Ride 2",
            "        SHARED3: Shared Ride 3+",
            "        DRIVEALONE: Drive Alone",
            "        DRIVE: Drive",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "all_tour_purposes",
                    ],
                    "tour_mode": [
                        "all_tour_modes",
                        "all_tour_modes",
                        "all_tour_modes",
                        "all_tour_modes",
                    ],
                    "trip_mode": ["DRIVEALONE", "WALK", "SHARED2", "SHARED3"],
                    "trip_count": [3.0, 2.0, 5.0, 10.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TripModePage(state, config)
    page.refresh(force=True)

    overall_chart = _collect_plotly_panes(page.render_body()[0])[0]
    trace = overall_chart.object.data[0]

    assert page.hide_drive_alone.value is False
    assert page.hide_drive_alone.name == "Hide Auto Modes"
    assert list(trace.x) == [
        "Walk",
        "Shared Ride 2",
        "Shared Ride 3+",
        "Drive Alone",
    ]
    assert list(overall_chart.object.layout.xaxis.categoryarray) == [
        "Walk",
        "Shared Ride 2",
        "Shared Ride 3+",
        "Drive Alone",
    ]
    page.hide_drive_alone.value = True
    checked_chart = _collect_plotly_panes(page.render_body()[0])[0]
    checked_trace = checked_chart.object.data[0]

    assert list(checked_trace.x) == ["Walk"]
    assert list(checked_chart.object.layout.xaxis.categoryarray) == ["Walk"]
    assert list(checked_trace.y) == pytest.approx([10.0])


def test_daily_activity_pattern_page_uses_configured_mandatory_tour_labels_on_plot_axes(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    mandatory_tour_frequency:",
            "      mapping:",
            "        1: Work",
            "        2: 2 Work",
            "        5: Work + School",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "daily_activity_pattern_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types"],
                    "daily_activity_pattern": ["M"],
                    "person_count": [10.0],
                }
            ),
            "mandatory_tour_frequency_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "all_person_types"],
                    "mandatory_tour_frequency": [1, 5],
                    "person_count": [7.0, 2.0],
                }
            ),
            "nonmandatory_tour_frequency_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types"],
                    "nonmandatory_tour_frequency": ["0"],
                    "person_count": [3.0],
                }
            ),
            "tour_rates_by_person_type_and_tour_purpose": pl.DataFrame(
                {
                    "person_type": ["all_person_types"],
                    "tour_purpose": ["work"],
                    "tour_rate": [1.8],
                }
            ),
            "trip_rates_by_person_type_and_trip_purpose": pl.DataFrame(
                {
                    "person_type": ["all_person_types"],
                    "trip_purpose": ["work"],
                    "trip_rate": [2.4],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = DailyActivityPatternPage(state, config)
    page.refresh(force=True)

    mandatory_chart = _collect_plotly_panes(page.render_body()[1])[0]
    trace = mandatory_chart.object.data[0]

    assert list(trace.x) == ["Work", "Work + School"]
    assert list(mandatory_chart.object.layout.xaxis.categoryarray) == [
        "Work",
        "Work + School",
    ]


def test_tour_purpose_selectors_use_category_labels_from_config(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    tour_purpose:",
            "      mapping:",
            "        all_tour_purposes: All Tour Purposes",
            "        eatout: Eat Out",
            "        social: Social Time",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_time_of_day_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "eatout",
                        "eatout",
                        "social",
                        "social",
                    ],
                    "time_bin": [1, 2, 1, 2, 1, 2],
                    "departure_tour_count": [5.0, 6.0, 3.0, 4.0, 2.0, 2.0],
                    "arrival_tour_count": [4.0, 5.0, 2.0, 3.0, 1.0, 1.0],
                    "duration_tour_count": [2.0, 3.0, 1.0, 2.0, 1.0, 1.0],
                }
            ),
            "trip_departure_time_by_purpose": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "eatout",
                        "social",
                    ],
                    "time_bin": [1, 1, 1],
                    "departure_trip_count": [5.0, 3.0, 2.0],
                    "departure_stop_count": [2.0, 1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    tour_time_page = TourTimePage(state, config)
    tour_time_page.refresh(force=True)
    assert list(tour_time_page.purpose_sel.options) == [
        "All Tour Purposes",
        "Eat Out",
        "Social Time",
    ]

    trip_stop_time_page = TripStopTimePage(state, config)
    trip_stop_time_page.refresh(force=True)
    assert list(trip_stop_time_page.tour_purpose_sel.options) == [
        "All Tour Purposes",
        "Eat Out",
        "Social Time",
    ]


def test_trip_stop_time_live_page_uses_shared_summary_helpers(
    tmp_path: Path,
) -> None:
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
                        "social",
                        "all_tour_purposes",
                        "all_tour_purposes",
                    ],
                    "time_bin": [1, 2, 1, 2, 48, 1, 2],
                    "departure_trip_count": [2.0, 3.0, 4.0, 5.0, 0.0, 6.0, 8.0],
                    "departure_stop_count": [3.0, 4.0, 5.0, 6.0, 0.0, 8.0, 10.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[timing_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TripStopTimePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]
    page.tour_purpose_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects
    trip_chart = _collect_plotly_panes(page._body)[0]
    assert list(trip_chart.object.data[0].x)[:2] == ["03:00", "03:30"]
    assert list(trip_chart.object.layout.xaxis.tickvals) == ["03:00"]
    assert list(trip_chart.object.layout.xaxis.ticktext) == ["3:00"]
    trip_hover = str(trip_chart.object.data[0].customdata[0])
    assert "Clock Time: 03:00" in trip_hover
    assert "start at 03:00" not in trip_hover


def test_dashboard_pages_apply_configured_dashboard_labels_to_category_plots(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    license_holding_status:",
            "      mapping:",
            "        has_license: Has License",
            "        no_license: No License",
            "    transit_pass_ownership_status:",
            "      mapping:",
            "        has_transit_pass: Has Transit Pass",
            "        no_transit_pass: No Transit Pass",
            "    telecommute_frequency:",
            "      mapping:",
            "        No_Telecommute: No Telecommute",
            "        1_day_week: 1 Day per Week",
            "    tour_composition:",
            "      mapping:",
            "        adults: Adults Only",
            "        mixed: Mixed Group",
            "    tour_category:",
            "      mapping:",
            "        mandatory: Mandatory",
            "        non_mandatory: Non-Mandatory",
            "    atwork_subtour_frequency_category:",
            "      mapping:",
            "        no_subtours: None",
            "        eat: 1 Eating Out",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "license_holding_status_distribution": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "all_person_types"],
                    "license_holding_status": ["has_license", "no_license"],
                    "person_count": [7.0, 3.0],
                    "pct": [70.0, 30.0],
                }
            ),
            "bicycle_comfort_level_distribution": pl.DataFrame(
                {
                    "person_type": ["all_person_types"],
                    "bicycle_comfort_level": ["1"],
                    "person_count": [10.0],
                    "pct": [100.0],
                }
            ),
            "transit_pass_ownership_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "all_person_types"],
                    "transit_pass_ownership_status": [
                        "has_transit_pass",
                        "no_transit_pass",
                    ],
                    "person_count": [4.0, 6.0],
                    "pct": [40.0, 60.0],
                }
            ),
            "transit_subsidy_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types"],
                    "transit_subsidy_status": ["0"],
                    "person_count": [10.0],
                    "pct": [100.0],
                }
            ),
            "telecommute_frequency_distribution": pl.DataFrame(
                {
                    "telecommute_frequency": ["No_Telecommute", "1_day_week"],
                    "person_count": [6.0, 4.0],
                }
            ),
            "joint_tour_composition_by_party_size": pl.DataFrame(
                {
                    "tour_composition": ["adults", "mixed"],
                    "party_size": [2, 2],
                    "joint_tour_count": [3.0, 2.0],
                }
            ),
            "joint_tour_party_size_distribution": pl.DataFrame(
                {"party_size": [2], "joint_tour_count": [5.0]}
            ),
            "joint_tours_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "household_count": [6.0],
                    "joint_tour_hh_count": [3.0],
                }
            ),
            "jtf_distribution": pl.DataFrame(
                {
                    "jtf_code": [1],
                    "jtf_label": ["One Joint Tour"],
                    "household_count": [5.0],
                }
            ),
            "person_jtp_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "joint_tour_person_count": [2.0],
                    "total_person_count": [4.0],
                }
            ),
            "household_jtp_by_household_size_and_jtf": pl.DataFrame(
                {
                    "household_size": [2],
                    "jtf": ["1"],
                    "household_percent": [50.0],
                }
            ),
            "tour_category_distribution": pl.DataFrame(
                {
                    "tour_category": ["mandatory", "non_mandatory"],
                    "tour_count": [8.0, 5.0],
                    "pct": [61.5, 38.5],
                }
            ),
            "tour_purpose_distribution": pl.DataFrame(
                {"tour_purpose": ["work"], "tour_count": [8.0], "pct": [100.0]}
            ),
            "tour_stop_frequency_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "outbound_stop_count": [0],
                    "inbound_stop_count": [0],
                    "total_stop_count": [0],
                    "tour_count": [8.0],
                    "pct": [100.0],
                }
            ),
            "atwork_subtour_frequency_distribution": pl.DataFrame(
                {
                    "atwork_subtour_frequency_category": ["no_subtours", "eat"],
                    "atwork_subtour_count": [6.0, 4.0],
                    "pct": [60.0, 40.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    individual_page = IndividualChoicesPage(state, config)
    individual_page.refresh(force=True)
    individual_plots = _collect_plotly_panes(individual_page.view)
    assert list(individual_plots[0].object.data[0].x) == ["Has License", "No License"]
    assert list(individual_plots[2].object.data[0].x) == [
        "Has Transit Pass",
        "No Transit Pass",
    ]

    mandatory_page = MandatoryLocationChoicePage(state, config)
    mandatory_page.refresh(force=True)
    mandatory_plots = _collect_plotly_panes(mandatory_page.view)
    assert list(mandatory_plots[-1].object.data[0].x) == [
        "No Telecommute",
        "1 Day per Week",
    ]

    joint_page = JointTravelPage(state, config)
    joint_page.refresh(force=True)
    joint_plots = _collect_plotly_panes(joint_page.view)
    assert list(joint_plots[3].object.data[0].x) == ["Adults Only", "Mixed Group"]

    purpose_page = TourPurposePage(state, config)
    purpose_page.refresh(force=True)
    purpose_plots = _collect_plotly_panes(purpose_page.view)
    assert list(purpose_plots[0].object.data[0].x) == ["Mandatory", "Non-Mandatory"]

    stop_frequency_page = TourStopFrequencyPage(state, config)
    stop_frequency_page.refresh(force=True)
    stop_plots = _collect_plotly_panes(stop_frequency_page.view)
    assert list(stop_plots[-1].object.data[0].x) == ["None", "1 Eating Out"]


def test_trip_stop_distance_live_page_uses_shared_summary_helpers(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    location_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "trip_distance_by_purpose": pl.DataFrame(
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
                    "trip_count": [14.0, 12.0, 8.0, 4.0, 5.0, 7.0],
                }
            ),
            "stop_out_of_direction_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "eatout",
                        "eatout",
                        "social",
                        "social",
                    ],
                    "distance_bin": [0, 1, 40, 0, 1, 0, 1],
                    "stop_count": [13.0, 6.0, 5.0, 8.0, 4.0, 5.0, 7.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[location_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TripStopDistancePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == [
        "All Tour Purposes",
        "eatout",
        "social",
    ]
    assert page.tour_purpose_sel.value == "All Tour Purposes"
    assert page.view.objects
    all_titles = [
        plot.object.layout.title.text for plot in _collect_plotly_panes(page._body)
    ]
    assert "Trip Distance Distribution for All Tours" in all_titles
    assert "Stop Out-of-Direction Distance Distribution for All Tours" in all_titles
    stop_ood_plot = next(
        plot
        for plot in _collect_plotly_panes(page._body)
        if str(plot.object.layout.title.text)
        == "Stop Out-of-Direction Distance Distribution for All Tours"
    )
    assert page.trip_stop_distance_range.current_range() == (0.0, 40.0)
    assert list(stop_ood_plot.object.data[0].x) == [0.0, 1.0, 40.0]
    assert list(stop_ood_plot.object.layout.xaxis.ticktext) == [
        *[str(value) for value in range(0, 40, 2)],
        "40+",
    ]
    assert list(stop_ood_plot.object.layout.xaxis.range) == [0.0, 40.0]
    assert list(stop_ood_plot.object.data[0].y) == pytest.approx(
        [54.166666666666664, 25.0, 20.833333333333336]
    )
    page.trip_stop_distance_range.min_widget.value = 0.25
    page.trip_stop_distance_range.max_widget.value = "2"
    page.refresh(force=True)
    ranged_plot = next(
        plot
        for plot in _collect_plotly_panes(page._body)
        if str(plot.object.layout.title.text)
        == "Stop Out-of-Direction Distance Distribution for All Tours"
    )
    assert list(ranged_plot.object.layout.xaxis.range) == [0.25, 2.0]
    page.trip_stop_distance_range.reset()
    page.refresh(force=True)
    reset_plot = next(
        plot
        for plot in _collect_plotly_panes(page._body)
        if str(plot.object.layout.title.text)
        == "Stop Out-of-Direction Distance Distribution for All Tours"
    )
    assert list(reset_plot.object.layout.xaxis.range) == [0.0, 40.0]
    page.trip_stop_distance_range.min_widget.value = 2.0
    page.trip_stop_distance_range.max_widget.value = "1"
    page.refresh(force=True)
    assert any(
        card.title == "Trip and Stop Distance Data Not Available"
        for card in _collect_cards(page._body)
    )
    page.trip_stop_distance_range.reset()
    page.refresh(force=True)

    page.tour_purpose_sel.value = "social"
    page.refresh(force=True)

    assert page.view.objects
    social_titles = [
        plot.object.layout.title.text for plot in _collect_plotly_panes(page._body)
    ]
    assert "Trip Distance Distribution for social Tours" in social_titles
    assert (
        "Stop Out-of-Direction Distance Distribution for social Tours" in social_titles
    )


def test_tour_stop_frequency_chart_data_caps_directional_stop_counts() -> None:
    data = [
        (
            "Base",
            pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"] * 6,
                    "total_stop_count": [0, 6, 7, 1, 0, 6],
                    "outbound_stop_count": [0, 3, 4, 1, 0, 3],
                    "inbound_stop_count": [0, 2, 3, 4, 1, 3],
                    "tour_count": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                }
            ),
        )
    ]

    both = stop_frequency_chart_data(data, None, "Both")[0][1]
    outbound = stop_frequency_chart_data(data, None, "Outbound")[0][1]

    assert both.to_dict(as_series=False) == {
        "stop_frequency": ["0", "1", "6+"],
        "tour_count": [6.0, 4.0, 11.0],
    }
    assert outbound.to_dict(as_series=False) == {
        "stop_frequency": ["0", "1", "3+"],
        "tour_count": [6.0, 4.0, 11.0],
    }


def test_daily_activity_pattern_live_page_uses_shared_summary_helpers(
    tmp_path: Path,
) -> None:
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
            "tour_rates_by_person_type_and_tour_purpose": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "tour_purpose": ["work", "shop", "work", "shop"],
                    "tour_rate": [1.8, 0.7, 2.0, 0.5],
                }
            ),
            "trip_rates_by_person_type_and_trip_purpose": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "trip_purpose": ["work", "shop", "work", "shop"],
                    "trip_rate": [2.4, 1.1, 2.8, 0.9],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[tour_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = DailyActivityPatternPage(state, config)
    page.refresh(force=True)

    assert list(page.person_type_sel.options) == ["All Person Types", "worker"]
    page.person_type_sel.value = "worker"
    page.refresh(force=True)
    assert page.view.objects


def test_daily_activity_pattern_page_renders_available_charts_when_one_summary_is_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {
                "daily_activity_pattern_by_person_type": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "daily_activity_pattern": ["M", "N"],
                        "person_count": [10.0, 6.0],
                    }
                ),
                "mandatory_tour_frequency_by_person_type": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "mandatory_tour_frequency": [1, 2],
                        "person_count": [7.0, 4.0],
                    }
                ),
                "nonmandatory_tour_frequency_by_person_type": pl.DataFrame(
                    schema={
                        "person_type": pl.Utf8,
                        "nonmandatory_tour_frequency": pl.Utf8,
                        "person_count": pl.Float64,
                    }
                ),
                "tour_rates_by_person_type_and_tour_purpose": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "tour_purpose": ["work", "shop"],
                        "tour_rate": [1.8, 0.5],
                    }
                ),
                "trip_rates_by_person_type_and_trip_purpose": pl.DataFrame(
                    {
                        "person_type": ["all_person_types", "worker"],
                        "trip_purpose": ["work", "shop"],
                        "trip_rate": [2.4, 0.9],
                    }
                ),
            },
        },
        summary_metadata_by_mode={
            "weighted": {
                "nonmandatory_tour_frequency_by_person_type": {
                    "state": "unavailable",
                    "detail": "joint_participants (missing required columns: person_id)",
                },
            }
        },
        source_run_dir="C:/runs/base",
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = DailyActivityPatternPage(state, config)
    page.refresh(force=True)

    plots = _collect_plotly_panes(page._body)
    cards = _collect_cards(page._body)

    assert len(plots) == 4
    card_markdown = [
        str(card.objects[0].object) for card in cards if getattr(card, "objects", None)
    ]
    assert any(
        getattr(card, "title", "") == "Data Not Available"
        and "nonmandatory_tour_frequency_by_person_type" in markdown
        for card, markdown in zip(cards, card_markdown)
    )
    assert not any(
        getattr(card, "title", "") == "Data Not Available"
        and "This page only renders from precomputed summary tables." in markdown
        for card in cards
        for markdown in [str(card.objects[0].object)]
        if getattr(card, "objects", None)
    )


def test_joint_travel_participation_page_uses_counts_and_runtime_percent_mode(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "jtf_distribution": pl.DataFrame(
                {
                    "jtf_code": [1],
                    "jtf_label": ["No Joint Tours"],
                    "household_count": [5.0],
                }
            ),
            "joint_tours_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "household_count": [6.0],
                    "joint_tour_hh_count": [3.0],
                }
            ),
            "joint_tour_party_size_distribution": pl.DataFrame(
                {
                    "party_size": [2],
                    "joint_tour_count": [3.0],
                }
            ),
            "joint_tour_composition_by_party_size": pl.DataFrame(
                {
                    "tour_composition": ["adults"],
                    "party_size": [2],
                    "joint_tour_count": [3.0],
                }
            ),
            "person_jtp_by_household_size": pl.DataFrame(
                {
                    "household_size": [2, 3],
                    "joint_tour_person_count": [2.0, 3.0],
                    "total_person_count": [4.0, 3.0],
                }
            ),
            "household_jtp_by_household_size_and_jtf": pl.DataFrame(
                {
                    "jtf": ["0", "1", "0", "1"],
                    "household_size": ["2", "2", "3", "3"],
                    "household_percent": [50.0, 50.0, 25.0, 75.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = JointTravelPage(state, config)
    page.refresh(force=True)

    plots = _collect_plotly_panes(page._participation_section)
    people_plot = next(
        plot
        for plot in plots
        if str(plot.object.layout.title.text)
        == "People Taking Part in a Joint Tour by Household Size"
    )
    household_plot = next(
        plot
        for plot in plots
        if str(plot.object.layout.title.text)
        == "Households Taking Part in a Joint Tour - All"
    )
    assert list(people_plot.object.layout.xaxis.categoryarray) == ["2", "3", "4", "5+"]
    assert list(household_plot.object.layout.xaxis.categoryarray) == ["0", "1"]
    assert list(household_plot.object.data[0].x) == ["0", "1"]
    assert list(people_plot.object.data[0].y) == [50.0, 100.0, 0.0, 0.0]

    state.value_mode = "Count"
    page.refresh(force=True)
    plots = _collect_plotly_panes(page._participation_section)
    people_plot = next(
        plot
        for plot in plots
        if str(plot.object.layout.title.text)
        == "People Taking Part in a Joint Tour by Household Size"
    )
    assert list(people_plot.object.layout.xaxis.categoryarray) == ["2", "3", "4", "5+"]
    assert list(people_plot.object.data[0].y) == [2.0, 3.0, 0.0, 0.0]


def test_joint_travel_frequency_can_hide_no_joint_tours_without_renormalizing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "jtf_distribution": pl.DataFrame(
                {
                    "jtf_code": [0, 1],
                    "jtf_label": ["No Joint Tours", "One Joint Tour"],
                    "household_count": [5.0, 3.0],
                }
            ),
            "joint_tours_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "household_count": [6.0],
                    "joint_tour_hh_count": [3.0],
                }
            ),
            "joint_tour_party_size_distribution": pl.DataFrame(
                {
                    "party_size": [2],
                    "joint_tour_count": [3.0],
                }
            ),
            "joint_tour_composition_by_party_size": pl.DataFrame(
                {
                    "tour_composition": ["adults"],
                    "party_size": [2],
                    "joint_tour_count": [3.0],
                }
            ),
            "person_jtp_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "joint_tour_person_count": [2.0],
                    "total_person_count": [4.0],
                }
            ),
            "household_jtp_by_household_size_and_jtf": pl.DataFrame(
                {
                    "jtf": ["0", "1"],
                    "household_size": ["2", "2"],
                    "household_percent": [50.0, 50.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = JointTravelPage(state, config)
    page.refresh(force=True)

    assert any(
        isinstance(obj, pn.pane.Markdown)
        and obj.object == "### Joint Tour Frequency"
        for obj in page.view.objects
    )
    assert page._frequency_section.objects[0].objects == [page.hide_no_joint_tours]
    frequency_plot = _collect_plotly_panes(page._frequency_section)[0]
    trace = frequency_plot.object.data[0]
    assert list(trace.x) == ["No Joint Tours", "One Joint Tour"]
    assert list(trace.y) == pytest.approx([62.5, 37.5])

    page.hide_no_joint_tours.value = True
    checked_plot = _collect_plotly_panes(page.render_frequency()[-1])[0]
    checked_trace = checked_plot.object.data[0]

    assert list(checked_trace.x) == ["One Joint Tour"]
    assert list(checked_trace.y) == pytest.approx([37.5])


def test_joint_travel_composition_plot_keeps_category_axis_when_party_size_filters_out_bars(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "jtf_distribution": pl.DataFrame(
                {
                    "jtf_code": [1],
                    "jtf_label": ["No Joint Tours"],
                    "household_count": [5.0],
                }
            ),
            "joint_tours_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "household_count": [6.0],
                    "joint_tour_hh_count": [3.0],
                }
            ),
            "joint_tour_party_size_distribution": pl.DataFrame(
                {
                    "party_size": [2, 3],
                    "joint_tour_count": [3.0, 4.0],
                }
            ),
            "joint_tour_composition_by_party_size": pl.DataFrame(
                {
                    "tour_composition": ["adults", "mixed"],
                    "party_size": [2, 3],
                    "joint_tour_count": [3.0, 4.0],
                }
            ),
            "person_jtp_by_household_size": pl.DataFrame(
                {
                    "household_size": [2],
                    "joint_tour_person_count": [2.0],
                    "total_person_count": [4.0],
                }
            ),
            "household_jtp_by_household_size_and_jtf": pl.DataFrame(
                {
                    "jtf": ["0"],
                    "household_size": ["2"],
                    "household_percent": [50.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = JointTravelPage(state, config)
    page.refresh(force=True)
    assert list(page.party_size_sel.options) == [
        "All Party Sizes",
        "2",
        "3",
        "4",
        "5+",
    ]
    page.party_size_sel.value = "2"
    page.refresh(force=True)

    composition_plot = next(
        plot
        for plot in _collect_plotly_panes(page._joint_tour_detail_section)
        if str(plot.object.layout.title.text)
        == "Joint Tour Composition by Party Size - 2"
    )
    assert list(composition_plot.object.layout.xaxis.categoryarray) == [
        "adults",
        "mixed",
    ]
    assert list(composition_plot.object.data[0].x) == ["adults", "mixed"]
    assert len(composition_plot.object.data[0].y) == 2
    assert composition_plot.object.data[0].y[0] > 0
    assert composition_plot.object.data[0].y[1] == 0.0


def test_skim_summaries_group_lists_tour_skims_before_trip_skims() -> None:
    definitions = page_definitions_for_group("skim_summaries")

    assert [definition.page_id for definition in definitions] == [
        "tour_skims",
        "trip_skims",
    ]


def test_trip_skims_page_uses_family_selector_and_two_digit_precision_summary_table(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    _attach_test_skimjoin_config(config)
    state = DashboardState(
        summary_runs=[_skim_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    page = TripSkimsPage(state, config)
    page.refresh(force=True)

    assert list(page.trip_family_sel.options[:4]) == [
        "Auto Skims",
        "Transit Skims",
        "Walk Skims",
        "Bike Skims",
    ]
    assert "skim_auto_time" in list(page.trip_component_sel.options)
    assert page.view.objects.index(page._summary_section) < page.view.objects.index(
        page._distribution_section
    )

    tables = _collect_tabulators(page._summary_section)
    assert len(tables) == 1
    table = tables[0]
    assert list(table.value.columns[:2]) == ["skim_name", "trip_mode"]
    assert set(table.value["trip_mode"].tolist()) == {"SOV", "HOV2", "HOV3"}
    assert "Bonus" not in table.value["skim_name"].tolist()
    assert table.value["mean"].tolist() == ["3.5", "7", "15"]
    assert table.value["n_valid"].tolist() == ["11", "10", "9"]

    if "Other Skims" in page.trip_family_sel.options:
        page.trip_family_sel.value = "Other Skims"
        page.refresh(force=True)
        other_table = _collect_tabulators(page._summary_section)[0]
        assert set(other_table.value["trip_mode"].tolist()) == {"SCHOOLBUS"}


def test_trip_walk_skims_use_explicit_walk_distance_and_time_labels(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    _attach_test_skimjoin_config(config)
    state = DashboardState(
        summary_runs=[_skim_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    page = TripSkimsPage(state, config)
    page.refresh(force=True)
    page.trip_family_sel.value = "Walk Skims"
    page.refresh(force=True)

    table = _collect_tabulators(page._summary_section)[0]
    assert table.value["skim_name"].tolist() == [
        "MAZ Actual Walk Time (min)",
        "MAZ Network Walk Distance (mi)",
        "TAZ Skim Walk Distance (mi)",
        "Total Walk Access/Egress Time (min)",
    ]


def test_trip_skim_family_respects_skimjoin_ignored_modes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    ignored_modes = ["EBIKE", "ESCOOTER", "BIKE_TRANSIT"]
    _attach_test_skimjoin_config(config, ignore_modes=ignored_modes)
    weighted, unweighted = _skim_summary_tables()
    ignored_mode_rows = pl.DataFrame(
        {
            "component": ["skim_walk_time", "skim_walk_time", "skim_walk_time"],
            "trip_mode": ignored_modes,
            "n_total": [4.0, 3.0, 2.0],
            "n_valid": [4.0, 3.0, 2.0],
            "mean": [6.0, 7.0, 8.0],
            "std": [1.0, 1.0, 1.0],
            "min": [5.0, 6.0, 7.0],
            "max": [7.0, 8.0, 9.0],
            "median": [6.0, 7.0, 8.0],
            "mode": [6.0, 7.0, 8.0],
            "zero_share": [0.0, 0.0, 0.0],
            "missing_share": [0.0, 0.0, 0.0],
        }
    )
    weighted["skimjoin_trip_component_stats"] = pl.concat(
        [weighted["skimjoin_trip_component_stats"], ignored_mode_rows],
        how="vertical",
    )
    unweighted["skimjoin_trip_component_stats"] = pl.concat(
        [unweighted["skimjoin_trip_component_stats"], ignored_mode_rows],
        how="vertical",
    )
    state = DashboardState(
        summary_runs=[
            _summary_run_with_tables(
                label="Base",
                weighted=weighted,
                unweighted=unweighted,
            )
        ],
        weighting_modes=config.weighting_modes,
    )

    page = TripSkimsPage(state, config)
    page.refresh(force=True)
    page.trip_family_sel.value = "Bike Skims"
    page.refresh(force=True)

    table = _collect_tabulators(page._summary_section)[0]
    assert set(table.value["trip_mode"].tolist()) == {"BIKE"}
    for ignored_mode in ignored_modes:
        assert ignored_mode not in table.value["trip_mode"].tolist()


def test_tour_skims_page_uses_family_and_direction_selectors_for_summary_table(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    _attach_test_skimjoin_config(config)
    state = DashboardState(
        summary_runs=[_skim_summary_run()],
        weighting_modes=config.weighting_modes,
    )

    page = TourSkimsPage(state, config)
    page.refresh(force=True)

    assert list(page.tour_family_sel.options) == [
        "Auto Skims",
        "Transit Skims",
        "Walk Skims",
    ]
    assert list(page.tour_direction_sel.options) == ["Outbound", "Inbound"]
    assert page.view.objects.index(page._summary_section) < page.view.objects.index(
        page._distribution_section
    )

    tables = _collect_tabulators(page._summary_section)
    assert len(tables) == 1
    table = tables[0]
    assert list(table.value.columns[:2]) == ["skim_name", "tour_mode"]
    assert set(table.value["tour_mode"].tolist()) == {"SOV", "HOV2"}
    assert set(table.value["skim_name"].tolist()) == {"Cost ($)", "Time (min)"}
    assert "Outbound" == page.tour_direction_sel.value

    page.tour_family_sel.value = "Transit Skims"
    page.tour_direction_sel.value = "Inbound"
    page.refresh(force=True)
    inbound_table = _collect_tabulators(page._summary_section)[0]
    assert set(inbound_table.value["tour_mode"].tolist()) == {"KNR_TRANSIT"}
    assert "Transit In-Vehicle Time (min)" in inbound_table.value["skim_name"].tolist()


def test_tour_purpose_labels_render_consistently_across_pages(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    tour_purpose:",
            "      mapping:",
            "        all_tour_purposes: All Tour Purposes",
            "        work: Work Trips",
            "        shop: Shopping",
            "        eatout: Eat Out",
            "        social: Social Time",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "daily_activity_pattern_by_person_type": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "daily_activity_pattern": ["M", "N", "M", "N"],
                    "person_count": [10.0, 8.0, 6.0, 4.0],
                }
            ),
            "mandatory_tour_frequency_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "worker"],
                    "mandatory_tour_frequency": [1, 1],
                    "person_count": [7.0, 4.0],
                }
            ),
            "nonmandatory_tour_frequency_by_person_type": pl.DataFrame(
                {
                    "person_type": ["all_person_types", "worker"],
                    "nonmandatory_tour_frequency": ["0", "1"],
                    "person_count": [3.0, 6.0],
                }
            ),
            "tour_rates_by_person_type_and_tour_purpose": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "tour_purpose": ["work", "shop", "work", "shop"],
                    "tour_rate": [1.8, 0.7, 2.0, 0.5],
                }
            ),
            "trip_rates_by_person_type_and_trip_purpose": pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "worker",
                    ],
                    "trip_purpose": ["work", "shop", "work", "shop"],
                    "trip_rate": [2.4, 1.1, 2.8, 0.9],
                }
            ),
            "tour_category_distribution": pl.DataFrame(
                {
                    "tour_category": ["mandatory", "non_mandatory"],
                    "tour_count": [10.0, 8.0],
                }
            ),
            "tour_purpose_distribution": pl.DataFrame(
                {
                    "tour_purpose": ["work", "shop"],
                    "tour_count": [12.0, 6.0],
                }
            ),
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes", "work", "shop"],
                    "distance_bin": ["10", "10", "20"],
                    "tour_count": [5.0, 3.0, 2.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.5],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["eatout", "social"],
                    "geography_level": ["Region", "Region"],
                    "average_tour_distance": [4.2, 6.1],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    daily_activity_page = DailyActivityPatternPage(state, config)
    daily_activity_page.refresh(force=True)
    daily_activity_plots = _collect_plotly_panes(daily_activity_page._body)
    daily_tour_rate_chart = next(
        plot
        for plot in daily_activity_plots
        if plot.object.layout.title.text
        == "Daily Tour Rate per Person by Tour Purpose - All Person Types"
    )
    assert list(daily_tour_rate_chart.object.layout.xaxis.categoryarray) == [
        "Work Trips",
        "Shopping",
    ]
    assert list(daily_tour_rate_chart.object.data[0].x) == ["Work Trips", "Shopping"]

    tour_purpose_page = TourPurposePage(state, config)
    tour_purpose_page.refresh(force=True)
    tour_purpose_plots = _collect_plotly_panes(tour_purpose_page._body)
    purpose_chart = next(
        plot
        for plot in tour_purpose_plots
        if plot.object.layout.title.text == "Tour Purpose"
    )
    assert list(purpose_chart.object.layout.xaxis.categoryarray) == [
        "Work Trips",
        "Shopping",
    ]
    assert list(purpose_chart.object.data[0].x) == ["Work Trips", "Shopping"]

    tour_distance_page = TourDistancePage(state, config)
    tour_distance_page.refresh(force=True)
    assert not hasattr(tour_distance_page, "nonmandatory_purpose_sel")
    tour_distance_page.geo_level_sel.value = "Region"
    tour_distance_page.refresh(force=True)
    tabulators = _collect_tabulators(tour_distance_page._average_section)
    nonmandatory_table = tabulators[0].value
    assert nonmandatory_table["Non-Mandatory Tour Purpose"].tolist() == [
        "Eat Out",
        "Social Time",
    ]


def test_trip_stop_purpose_page_uses_trip_and_stop_purpose_dashboard_labels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    tour_purpose:",
            "      mapping:",
            "        work: Work Tours",
            "        shop: Shopping Tours",
            "    trip_purpose:",
            "      mapping:",
            "        work: Work Trips",
            "        shop: Shopping Trips",
            "    stop_purpose:",
            "      mapping:",
            "        work: Work Stops",
            "        shop: Shopping Stops",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "trip_purpose_distribution": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "work",
                        "work",
                        "shop",
                    ],
                    "trip_purpose": ["work", "shop", "work", "shop", "shop"],
                    "trip_count": [8.0, 6.0, 5.0, 3.0, 4.0],
                    "pct": [57.1, 42.9, 62.5, 37.5, 100.0],
                }
            ),
            "stop_destination_purpose_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["work", "work", "shop"],
                    "stop_destination_purpose": ["work", "shop", "shop"],
                    "stop_count": [3.0, 5.0, 4.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TripStopPurposePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == [
        "All Tour Purposes",
        "Work Tours",
        "Shopping Tours",
    ]

    plots = _collect_plotly_panes(page._body)
    trip_chart = next(
        plot
        for plot in plots
        if plot.object.layout.title.text == "Trip Purpose for All Tours"
    )
    stop_chart = next(
        plot
        for plot in plots
        if plot.object.layout.title.text == "Stop Destination Purpose for All Tours"
    )
    assert list(trip_chart.object.layout.xaxis.categoryarray) == [
        "Work Trips",
        "Shopping Trips",
    ]
    assert list(trip_chart.object.data[0].x) == ["Work Trips", "Shopping Trips"]
    page.tour_purpose_sel.value = "Work Tours"
    page.refresh(force=True)
    plots = _collect_plotly_panes(page._body)
    filtered_trip_chart = next(
        plot
        for plot in plots
        if plot.object.layout.title.text == "Trip Purpose for Work Tours"
    )
    filtered_stop_chart = next(
        plot
        for plot in plots
        if plot.object.layout.title.text == "Stop Destination Purpose for Work Tours"
    )
    assert list(filtered_trip_chart.object.data[0].x) == [
        "Work Trips",
        "Shopping Trips",
    ]
    assert list(filtered_trip_chart.object.data[0].y) == [62.5, 37.5]
    assert list(filtered_stop_chart.object.layout.xaxis.categoryarray) == [
        "Work Stops",
        "Shopping Stops",
    ]
    assert list(filtered_stop_chart.object.data[0].x) == [
        "Work Stops",
        "Shopping Stops",
    ]


def test_escorted_tours_live_page_renders_stop_distribution_controls_and_charts(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    escorted_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "escorted_tour_totals": pl.DataFrame({"tour_count": [5.0]}),
            "school_escorted_tours_by_escort_type_and_direction": pl.DataFrame(
                {
                    "escort_type": ["pure_escort", "pure_escort", "ride_share"],
                    "direction": ["all_directions", "outbound", "all_directions"],
                    "tour_count": [6.0, 3.0, 2.0],
                }
            ),
            "adult_escort_event_stop_distribution": pl.DataFrame(
                {
                    "segment": [
                        "outbound_before_dropoff",
                        "outbound_before_dropoff",
                        "outbound_after_dropoff",
                        "inbound_before_pickup",
                        "inbound_after_pickup",
                    ],
                    "stop_count": [1, 4, 0, 0, 1],
                    "tour_count": [2.0, 5.0, 3.0, 4.0, 1.0],
                }
            ),
            "adult_escorted_tours_by_person_type_and_direction": pl.DataFrame(
                {
                    "person_type": ["2", "2", "4"],
                    "direction": ["both", "outbound", "both"],
                    "tour_count": [6.0, 3.0, 2.0],
                }
            ),
            "student_school_escort_status_by_direction": pl.DataFrame(
                {
                    "direction": [
                        "outbound",
                        "outbound",
                        "inbound",
                        "both",
                    ],
                    "escort_type": [
                        "not_escorted",
                        "pure_escort",
                        "ride_share",
                        "ride_share",
                    ],
                    "tour_count": [4.0, 3.0, 2.0, 1.0],
                }
            ),
            "student_households_by_student_count": pl.DataFrame(
                {
                    "student_count": [1, 2, 6, 7],
                    "household_count": [10.0, 5.0, 3.0, 2.0],
                }
            ),
            "households_with_school_escorting_by_student_count_and_direction": pl.DataFrame(
                {
                    "student_count": [1, 2, 7, 1, 2, 1, 2],
                    "direction": [
                        "outbound",
                        "outbound",
                        "outbound",
                        "inbound",
                        "inbound",
                        "both",
                        "both",
                    ],
                    "household_count": [4.0, 1.0, 2.0, 3.0, 0.0, 2.0, 1.0],
                }
            ),
            "schoolkids_per_escorted_tour_by_student_count_and_direction": pl.DataFrame(
                {
                    "student_count": [1, 2, 7, 1, 2, 1, 2],
                    "direction": [
                        "outbound",
                        "outbound",
                        "outbound",
                        "inbound",
                        "inbound",
                        "both",
                        "both",
                    ],
                    "avg_schoolkids_per_tour": [1.5, 2.0, 4.0, 1.0, 2.5, 1.0, 2.0],
                    "tour_count": [4.0, 2.0, 3.0, 3.0, 1.0, 2.0, 1.0],
                }
            ),
            "adult_escorted_tour_distance_distribution_by_direction": pl.DataFrame(
                {
                    "distance_bin": ["12", "40+", "12"],
                    "direction": ["both", "both", "outbound"],
                    "tour_count": [2.0, 3.0, 2.0],
                }
            ),
            "adult_escorted_trip_distance_distribution_by_direction": pl.DataFrame(
                {
                    "distance_bin": ["5", "6", "5"],
                    "direction": ["both", "both", "outbound"],
                    "trip_count": [2.0, 2.0, 2.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[escorted_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = EscortedToursPage(state, config)
    page.refresh(force=True)

    assert list(page.direction_sel.options) == ["Both Directions", "Outbound"]
    assert page.view.objects
    render_calls = {section_id: 0 for section_id in page._registered_sections}
    for section_id, section in page._registered_sections.items():
        original_render = section.render

        def counted_render(section_id=section_id, original_render=original_render):
            render_calls[section_id] += 1
            return original_render()

        section.render = counted_render
    page.direction_sel.value = "Both Directions"
    page.refresh(force=False)
    assert page.view.objects
    assert render_calls == {
        "school_escort.body": 0,
        "adult_escort.body": 0,
        "direction.body": 1,
        "distance.body": 1,
    }
    student_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page.view)
        if "Student School Escort Status" in str(plot.object.layout.title.text)
    ]
    assert sorted(student_titles) == [
        "Student School Escort Status - Both Directions",
        "Student School Escort Status - Inbound",
        "Student School Escort Status - Outbound",
    ]
    household_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page.view)
        if "Households With School Escorting" in str(plot.object.layout.title.text)
    ]
    assert sorted(household_titles) == [
        "Households With School Escorting - Both Directions",
        "Households With School Escorting - Inbound",
        "Households With School Escorting - Outbound",
    ]
    schoolkids_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page.view)
        if "Schoolkids Per Adult Chauffeur Tour" in str(plot.object.layout.title.text)
    ]
    assert sorted(schoolkids_titles) == [
        "Schoolkids Per Adult Chauffeur Tour - Both Directions",
        "Schoolkids Per Adult Chauffeur Tour - Inbound",
        "Schoolkids Per Adult Chauffeur Tour - Outbound",
    ]
    stop_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page.view)
        if "Adult Escort Stops" in str(plot.object.layout.title.text)
    ]
    assert sorted(stop_titles) == [
        "Adult Escort Stops After Dropoff - Outbound",
        "Adult Escort Stops After Pickup - Inbound",
        "Adult Escort Stops Before Dropoff - Outbound",
        "Adult Escort Stops Before Pickup - Inbound",
    ]
    household_plot = next(
        plot
        for plot in _collect_plotly_panes(page.view)
        if str(plot.object.layout.title.text)
        == "Households With School Escorting - Outbound"
    )
    assert list(household_plot.object.layout.xaxis.categoryarray) == ["1", "2", "6+"]
    schoolkids_plot = next(
        plot
        for plot in _collect_plotly_panes(page.view)
        if str(plot.object.layout.title.text)
        == "Schoolkids Per Adult Chauffeur Tour - Outbound"
    )
    assert list(schoolkids_plot.object.layout.xaxis.categoryarray) == ["1", "2", "6+"]
    assert list(schoolkids_plot.object.data[0].y) == [1.5, 2.0, 4.0]
    stop_plot = next(
        plot
        for plot in _collect_plotly_panes(page.view)
        if str(plot.object.layout.title.text)
        == "Adult Escort Stops Before Dropoff - Outbound"
    )
    assert list(stop_plot.object.layout.xaxis.categoryarray) == ["0", "1", "3+"]
    assert list(stop_plot.object.data[0].y) == pytest.approx(
        [0.0, 28.57142857142857, 71.42857142857143]
    )
    distance_plot = next(
        plot
        for plot in _collect_plotly_panes(page.view)
        if str(plot.object.layout.title.text)
        == "Chauffeur Tour Distance Distribution - Both Directions"
    )
    assert page.escort_distance_range.current_range() == (0.0, 40.0)
    assert list(distance_plot.object.layout.xaxis.range) == [0.0, 40.0]
    assert list(distance_plot.object.layout.xaxis.ticktext) == [
        *[str(value) for value in range(0, 40, 2)],
        "40+",
    ]
    page.escort_distance_range.min_widget.value = 10.0
    page.escort_distance_range.max_widget.value = "20"
    page.refresh(force=True)
    ranged_distance_plot = next(
        plot
        for plot in _collect_plotly_panes(page.view)
        if str(plot.object.layout.title.text)
        == "Chauffeur Tour Distance Distribution - Both Directions"
    )
    assert list(ranged_distance_plot.object.layout.xaxis.range) == [10.0, 20.0]
    page.escort_distance_range.reset()
    page.refresh(force=True)
    reset_distance_plot = next(
        plot
        for plot in _collect_plotly_panes(page.view)
        if str(plot.object.layout.title.text)
        == "Chauffeur Tour Distance Distribution - Both Directions"
    )
    assert list(reset_distance_plot.object.layout.xaxis.range) == [0.0, 40.0]
    page.escort_distance_range.min_widget.value = 20.0
    page.escort_distance_range.max_widget.value = "10"
    page.refresh(force=True)
    assert any(
        card.title == "Chauffeur Distance Data Not Available"
        for card in _collect_cards(page.view)
    )


def test_escorted_tours_page_renders_core_charts_when_optional_summaries_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    escorted_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "escorted_tour_totals": pl.DataFrame({"tour_count": [5.0]}),
            "school_escorted_tours_by_escort_type_and_direction": pl.DataFrame(
                {
                    "escort_type": ["pure_escort", "ride_share"],
                    "direction": ["all_directions", "all_directions"],
                    "tour_count": [6.0, 2.0],
                }
            ),
            "adult_escort_event_stop_distribution": pl.DataFrame(
                {
                    "segment": ["outbound_before_dropoff"],
                    "stop_count": [1],
                    "tour_count": [2.0],
                }
            ),
            "adult_escorted_tours_by_person_type_and_direction": pl.DataFrame(
                {
                    "person_type": ["2", "4"],
                    "direction": ["both", "both"],
                    "tour_count": [6.0, 2.0],
                }
            ),
            "adult_escorted_tour_distance_distribution_by_direction": pl.DataFrame(
                {
                    "distance_bin": ["12", "40+"],
                    "direction": ["both", "both"],
                    "tour_count": [2.0, 3.0],
                }
            ),
            "adult_escorted_trip_distance_distribution_by_direction": pl.DataFrame(
                {
                    "distance_bin": ["5", "6"],
                    "direction": ["both", "both"],
                    "trip_count": [2.0, 2.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[escorted_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = EscortedToursPage(state, config)
    page.refresh(force=True)

    assert page.view.objects
    titles = [
        str(plot.object.layout.title.text) for plot in _collect_plotly_panes(page.view)
    ]
    assert "Chauffeur Tours by Person Type - Both Directions" in titles
    assert "Chauffeur Tour Distance Distribution - Both Directions" in titles
    assert "Chauffeur Trip Distance Distribution - Both Directions" in titles
    assert "Adult Escort Stops Before Dropoff - Outbound" in titles
    assert "Adult Escort Trip Stop Frequency - Both Directions" not in titles
    assert all("Schoolkids Per Escorted Tour" not in title for title in titles)


def test_escorted_tours_page_uses_configured_escort_labels_for_student_status(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    escort:",
            "      mapping:",
            "        not_escorted: Unescorted",
            "        pure_escort: Driven Solo",
            "        ride_share: Shared Ride",
        ],
    )
    escorted_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "escorted_tour_totals": pl.DataFrame({"tour_count": [5.0]}),
            "school_escorted_tours_by_escort_type_and_direction": pl.DataFrame(
                {
                    "escort_type": ["pure_escort", "ride_share"],
                    "direction": ["outbound", "outbound"],
                    "tour_count": [2.0, 3.0],
                }
            ),
            "adult_escort_event_stop_distribution": pl.DataFrame(
                {
                    "segment": ["outbound_before_dropoff"],
                    "stop_count": [1],
                    "tour_count": [2.0],
                }
            ),
            "adult_escorted_tours_by_person_type_and_direction": pl.DataFrame(
                {
                    "person_type": ["1"],
                    "direction": ["outbound"],
                    "tour_count": [2.0],
                }
            ),
            "adult_escorted_tour_distance_distribution_by_direction": pl.DataFrame(
                {
                    "distance_bin": ["5"],
                    "direction": ["outbound"],
                    "tour_count": [2.0],
                }
            ),
            "adult_escorted_trip_distance_distribution_by_direction": pl.DataFrame(
                {
                    "distance_bin": ["5"],
                    "direction": ["outbound"],
                    "trip_count": [2.0],
                }
            ),
            "student_school_escort_status_by_direction": pl.DataFrame(
                {
                    "direction": ["outbound", "outbound", "outbound"],
                    "escort_type": ["not_escorted", "pure_escort", "ride_share"],
                    "tour_count": [1.0, 2.0, 3.0],
                }
            ),
        },
    )

    state = DashboardState(
        summary_runs=[escorted_summary_run],
        weighting_modes=config.weighting_modes,
    )
    page = EscortedToursPage(state, config)
    page.refresh(force=True)
    plots = _collect_plotly_panes(page.view)

    student_plot = next(
        plot
        for plot in plots
        if str(plot.object.layout.title.text)
        == "Student School Escort Status - Outbound"
    )
    assert list(student_plot.object.layout.xaxis.categoryarray) == [
        "Unescorted",
        "Driven Solo",
        "Shared Ride",
    ]


def test_filter_person_type_rates_total_uses_full_person_denominator() -> None:
    data_list = [
        (
            "Base",
            pl.DataFrame(
                {
                    "person_type": ["worker", "student", "worker"],
                    "tour_purpose": ["school", "work", "work"],
                    "tour_rate": [0.5, 1.0, 2.0],
                }
            ),
        )
    ]
    person_weights = {
        "Base": pl.DataFrame(
            {
                "person_type": ["worker", "student"],
                "person_count": [10.0, 30.0],
            }
        )
    }

    filtered = filter_person_type_rates(
        data_list,
        "all_person_types",
        purpose_col="tour_purpose",
        rate_col="tour_rate",
        person_weights=person_weights,
    )

    assert len(filtered) == 1
    label, df = filtered[0]
    assert label == "Base"
    assert df.sort("tour_purpose").to_dict(as_series=False) == {
        "tour_purpose": ["school", "work"],
        "tour_rate": [0.125, 1.25],
    }


def test_filter_person_type_rates_total_prefers_existing_total_rows() -> None:
    data_list = [
        (
            "Base",
            pl.DataFrame(
                {
                    "person_type": [
                        "all_person_types",
                        "all_person_types",
                        "worker",
                        "student",
                    ],
                    "tour_purpose": ["school", "work", "work", "school"],
                    "tour_rate": [0.25, 1.5, 2.0, 1.0],
                }
            ),
        )
    ]

    filtered = filter_person_type_rates(
        data_list,
        "all_person_types",
        purpose_col="tour_purpose",
        rate_col="tour_rate",
        person_weights={},
    )

    assert len(filtered) == 1
    label, df = filtered[0]
    assert label == "Base"
    assert df.sort("tour_purpose").to_dict(as_series=False) == {
        "tour_purpose": ["school", "work"],
        "tour_rate": [0.25, 1.5],
    }


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
                    "household_size": [1, 5, 6],
                    "household_count": [15.0, 10.0, 15.0],
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

    assert page.view.objects
    household_plot = next(
        plot
        for plot in _collect_plotly_panes(page._demographics_section)
        if str(plot.object.layout.title.text) == "Household Size Distribution"
    )
    assert list(household_plot.object.data[0].x) == ["1", "5+"]
    assert list(household_plot.object.data[0].y) == [37.5, 62.5]


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

    assert _collect_plotly_panes(page.view)
    person_type_diag = next(
        diagnostic
        for diagnostic in page.visualization_diagnostics
        if diagnostic.visualization_id == "person_type_distribution"
    )
    assert person_type_diag.render_state == "partial"
    assert person_type_diag.usable_run_labels == ("Base",)
    assert person_type_diag.excluded_runs[0].label == "Build"
    assert person_type_diag.excluded_runs[0].status == "schema_mismatch"


def test_individual_choices_page_renders_partial_content_when_some_summaries_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "license_holding_status_distribution": empty_summary_frame(
                SUMMARY_BY_ID["license_holding_status_distribution"].builder
            ),
            "bicycle_comfort_level_distribution": empty_summary_frame(
                SUMMARY_BY_ID["bicycle_comfort_level_distribution"].builder
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

    assert isinstance(page.view, pn.Column)
    cards = _collect_cards(page.view)
    assert len(cards) == 2
    assert sorted(card.title for card in cards) == ["Data Empty", "Data Empty"]
    assert any(isinstance(obj, pn.Row) for obj in page.view.objects)


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
                SUMMARY_BY_ID["allocated_vehicle_age_by_occupancy"].builder
            ),
            "allocated_vehicle_fuel_type_by_occupancy": empty_summary_frame(
                SUMMARY_BY_ID["allocated_vehicle_fuel_type_by_occupancy"].builder
            ),
            "allocated_vehicle_body_type_by_occupancy": empty_summary_frame(
                SUMMARY_BY_ID["allocated_vehicle_body_type_by_occupancy"].builder
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourSummariesTourModePage(state, config)
    page.refresh(force=True)

    assert list(page.purpose_sel.options) == ["All Tour Purposes", "work"]
    assert len(page._mode_section.objects) == 5
    chart_titles = [
        plot.object.layout.title.text
        for plot in _collect_plotly_panes(page._mode_section)
    ]
    assert chart_titles == [
        "Tour Mode - All",
        "Tour Mode - Zero Auto",
        "Tour Mode - Fewer Vehicles Than Drivers",
        "Tour Mode - At Least As Many Vehicles as Drivers",
    ]
    vehicle_cards = _collect_cards(page._vehicle_section)
    assert len(vehicle_cards) == 3


def test_tour_summaries_tour_mode_page_uses_configured_mode_labels_on_plot_axes(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    mode:",
            "      mapping:",
            "        DRIVE: Drive Alone",
            "        HOV2: Shared Ride 2",
            "        HOV3: Shared Ride 3+",
            "        WALK: Walk",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_mode_by_tour_purpose_and_auto_sufficiency": pl.DataFrame(
                {
                    "tour_purpose": [
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "all_tour_purposes",
                        "all_tour_purposes",
                    ],
                    "tour_mode": ["DRIVE", "WALK", "HOV2", "HOV3"],
                    "tour_count_all_households": [10.0, 5.0, 3.0, 2.0],
                    "tour_count_zero_auto": [2.0, 4.0, 1.0, 1.0],
                    "tour_count_auto_deficient": [3.0, 1.0, 1.0, 1.0],
                    "tour_count_auto_sufficient": [5.0, 0.0, 1.0, 0.0],
                }
            ),
            "allocated_vehicle_age_by_occupancy": empty_summary_frame(
                SUMMARY_BY_ID["allocated_vehicle_age_by_occupancy"].builder
            ),
            "allocated_vehicle_fuel_type_by_occupancy": empty_summary_frame(
                SUMMARY_BY_ID["allocated_vehicle_fuel_type_by_occupancy"].builder
            ),
            "allocated_vehicle_body_type_by_occupancy": empty_summary_frame(
                SUMMARY_BY_ID["allocated_vehicle_body_type_by_occupancy"].builder
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourSummariesTourModePage(state, config)
    page.refresh(force=True)

    mode_chart = _collect_plotly_panes(page._mode_section)[0]
    trace = mode_chart.object.data[0]

    assert page.hide_drive_alone.value is False
    assert page.hide_drive_alone.name == "Hide Auto Modes"
    assert list(trace.x) == ["Drive Alone", "Shared Ride 2", "Shared Ride 3+", "Walk"]
    assert list(mode_chart.object.layout.xaxis.categoryarray) == [
        "Drive Alone",
        "Shared Ride 2",
        "Shared Ride 3+",
        "Walk",
    ]
    page.hide_drive_alone.value = True
    checked_chart = _collect_plotly_panes(
        pn.Column(*page.render_modes_section())
    )[0]
    checked_trace = checked_chart.object.data[0]

    assert list(checked_trace.x) == ["Walk"]
    assert list(checked_chart.object.layout.xaxis.categoryarray) == ["Walk"]
    assert list(checked_trace.y) == pytest.approx([25.0])


def test_tour_mode_auto_sufficiency_definitions_follow_configured_basis(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  auto_sufficiency_basis: workers",
        ],
    )

    markdown = auto_sufficiency_definitions_markdown(config)

    assert "**Fewer Vehicles Than Workers**" in markdown
    assert "**At Least As Many Vehicles as Workers**" in markdown
    assert "household has fewer vehicles than workers." in markdown
    assert "household has at least as many vehicles as workers." in markdown


def test_mandatory_location_choice_uses_union_of_available_geographies(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": empty_summary_frame(
                SUMMARY_BY_ID["internal_external_worker_by_geography"].builder
            ),
            "work_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 1, 1],
                    "geography_type": ["all_geographies", "district", "maz"],
                    "geography_id": ["all_geographies", "A", "10"],
                    "person_count": [12.0, 5.0, 7.0],
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

    assert list(page.geo_level_sel.options) == [
        "All Geography Types",
        "District",
    ]


def test_mandatory_location_choice_can_show_maz_when_enabled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_lines=["enable_maz_geographies: true"],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": empty_summary_frame(
                SUMMARY_BY_ID["internal_external_worker_by_geography"].builder
            ),
            "work_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 1, 1],
                    "geography_type": ["all_geographies", "maz", "maz"],
                    "geography_id": ["all_geographies", "10", "20"],
                    "person_count": [12.0, 5.0, 7.0],
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

    assert list(page.geo_level_sel.options) == [
        "All Geography Types",
        "MAZ",
    ]


def test_tour_mode_vehicle_filters_sort_categories_stably() -> None:
    filtered = vehicle_attribute_data(
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
        "All",
        category="fuel_type",
    )

    assert filtered[0][1]["fuel_type"].to_list() == [
        "Battery EV",
        "Gasoline",
        "Hybrid",
    ]


def test_tour_mode_occupancy_selector_uses_common_values_across_vehicle_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_mode_by_tour_purpose_and_auto_sufficiency": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "tour_mode": ["DRIVE"],
                    "tour_count_all_households": [10.0],
                    "tour_count_zero_auto": [2.0],
                    "tour_count_auto_deficient": [3.0],
                    "tour_count_auto_sufficient": [5.0],
                }
            ),
            "allocated_vehicle_age_by_occupancy": pl.DataFrame(
                {
                    "occupancy": ["All", "1", "2+"],
                    "age": ["1", "1", "1"],
                    "vehicle_count": [3.0, 2.0, 1.0],
                }
            ),
            "allocated_vehicle_fuel_type_by_occupancy": pl.DataFrame(
                {
                    "occupancy": ["All", "1"],
                    "fuel_type": ["Gas", "Gas"],
                    "vehicle_count": [3.0, 2.0],
                }
            ),
            "allocated_vehicle_body_type_by_occupancy": pl.DataFrame(
                {
                    "occupancy": ["All", "1", "3+"],
                    "body_type": ["Sedan", "Sedan", "Van"],
                    "vehicle_count": [3.0, 2.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourSummariesTourModePage(state, config)
    page.refresh(force=True)

    assert list(page.occupancy_sel.options) == ["All", "1"]


def test_internal_external_tours_geo_selector_uses_union_levels_across_tables(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_lines=["enable_maz_geographies: true"])
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_nonmandatory_tour_frequency_by_home_geography": pl.DataFrame(
                {
                    "geography_level": ["all_geographies", "maz", "district"],
                    "home_geography": ["all_geographies", "1", "A"],
                    "internal_tour_count": [5.0, 2.0, 3.0],
                    "external_tour_count": [2.0, 1.0, 1.0],
                }
            ),
            "external_nonmandatory_tour_locations": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "maz"],
                    "geography_id": ["all_geographies", "1"],
                    "tour_count": [4.0, 4.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = InternalExternalToursPage(state, config)
    page.refresh(force=True)

    assert list(page.geo_level_sel.options) == [
        "All Geography Types",
        "District",
        "MAZ",
    ]
    tables = _collect_tabulators(page._body)
    assert len(tables) == 2
    frequency_table = tables[0].value
    location_table = tables[1].value
    assert frequency_table.columns[:2].tolist() == ["Geography Type", "Geography Name"]
    assert location_table.columns[:2].tolist() == ["Geography Type", "Geography Name"]
    assert frequency_table["Geography Type"].tolist() == ["All Geographies"]
    assert frequency_table["Geography Name"].tolist() == ["All Geographies"]
    assert location_table["Geography Type"].tolist() == ["All Geographies"]
    assert location_table["Geography Name"].tolist() == ["All Geographies"]

    page.geo_level_sel.value = "District"
    page.refresh(force=True)
    tables = _collect_tabulators(page._body)
    assert len(tables) == 1
    frequency_table = tables[0].value
    assert frequency_table.columns[:2].tolist() == ["Geography Type", "Geography Name"]
    assert frequency_table["Geography Type"].tolist() == ["District"]
    assert frequency_table["Geography Name"].tolist() == ["A"]
    cards = _collect_cards(page._body)
    assert any(card.title == "Data Not Available" for card in cards)


def test_internal_external_tours_geo_selector_hides_only_maz_when_disabled(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_nonmandatory_tour_frequency_by_home_geography": pl.DataFrame(
                {
                    "geography_level": ["all_geographies", "district", "maz"],
                    "home_geography": ["all_geographies", "A", "1"],
                    "internal_tour_count": [5.0, 3.0, 2.0],
                    "external_tour_count": [2.0, 1.0, 1.0],
                }
            ),
            "external_nonmandatory_tour_locations": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "geography_id": ["all_geographies", "A", "1"],
                    "tour_count": [4.0, 4.0, 4.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = InternalExternalToursPage(state, config)
    page.refresh(force=True)

    assert list(page.geo_level_sel.options) == ["All Geography Types", "District"]


def test_shadow_pricing_geo_selector_keeps_maz_available_when_disabled(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "geography_id": ["all_geographies", "A", "1"],
                    "target_count": [20.0, 10.0, 4.0],
                    "modeled_count": [18.0, 9.0, 3.0],
                    "residual_count": [-2.0, -1.0, -1.0],
                    "absolute_residual_count": [2.0, 1.0, 1.0],
                    "percent_error": [-10.0, -10.0, -25.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "bin_start": [-5.0, -3.0, -2.0],
                    "bin_end": [0.0, 0.0, 0.0],
                    "geography_count": [1.0, 1.0, 1.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "geography_id": ["all_geographies", "A", "1"],
                    "student_type": ["University", "University", "University"],
                    "target_count": [12.0, 6.0, 2.0],
                    "modeled_count": [11.0, 5.0, 2.0],
                    "residual_count": [-1.0, -1.0, 0.0],
                    "absolute_residual_count": [1.0, 1.0, 0.0],
                    "percent_error": [-8.3333, -16.6667, 0.0],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "student_type": ["University", "University", "University"],
                    "bin_start": [-2.0, -2.0, -1.0],
                    "bin_end": [0.0, 0.0, 1.0],
                    "geography_count": [1.0, 1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = ShadowPricingPage(state, config)
    page.refresh(force=True)

    assert list(page.geo_level_sel.options) == [
        "All Geography Types",
        "District",
        "MAZ",
    ]


def test_shadow_pricing_geo_selector_shows_detailed_levels_when_enabled(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path, dashboard_lines=["enable_maz_geographies: true"])
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "geography_id": ["all_geographies", "A", "1"],
                    "target_count": [20.0, 10.0, 4.0],
                    "modeled_count": [18.0, 9.0, 3.0],
                    "residual_count": [-2.0, -1.0, -1.0],
                    "absolute_residual_count": [2.0, 1.0, 1.0],
                    "percent_error": [-10.0, -10.0, -25.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "bin_start": [-5.0, -3.0, -2.0],
                    "bin_end": [0.0, 0.0, 0.0],
                    "geography_count": [1.0, 1.0, 1.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "geography_id": ["all_geographies", "A", "1"],
                    "student_type": ["University", "University", "University"],
                    "target_count": [12.0, 6.0, 2.0],
                    "modeled_count": [11.0, 5.0, 2.0],
                    "residual_count": [-1.0, -1.0, 0.0],
                    "absolute_residual_count": [1.0, 1.0, 0.0],
                    "percent_error": [-8.3333, -16.6667, 0.0],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "maz"],
                    "student_type": ["University", "University", "University"],
                    "bin_start": [-2.0, -2.0, -1.0],
                    "bin_end": [0.0, 0.0, 1.0],
                    "geography_count": [1.0, 1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = ShadowPricingPage(state, config)
    page.refresh(force=True)

    assert list(page.geo_level_sel.options) == [
        "All Geography Types",
        "District",
        "MAZ",
    ]


def test_shadow_pricing_page_uses_residual_histograms_and_filters_school_student_type(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    base_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "district"],
                    "geography_id": ["all_geographies", "A", "B"],
                    "target_count": [30.0, 10.0, 20.0],
                    "modeled_count": [28.0, 12.0, 16.0],
                    "residual_count": [-2.0, 2.0, -4.0],
                    "absolute_residual_count": [2.0, 2.0, 4.0],
                    "percent_error": [-6.6667, 20.0, -20.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "district"],
                    "bin_start": [-4.0, -4.0, 0.0],
                    "bin_end": [0.0, 0.0, 2.0],
                    "geography_count": [2.0, 1.0, 1.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": [
                        "all_geographies",
                        "district",
                        "district",
                        "district",
                    ],
                    "geography_id": ["all_geographies", "A", "A", "B"],
                    "student_type": ["All", "School", "University", "University"],
                    "target_count": [15.0, 8.0, 4.0, 3.0],
                    "modeled_count": [13.0, 7.0, 5.0, 1.0],
                    "residual_count": [-2.0, -1.0, 1.0, -2.0],
                    "absolute_residual_count": [2.0, 1.0, 1.0, 2.0],
                    "percent_error": [-13.3333, -12.5, 25.0, -66.6667],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": [
                        "all_geographies",
                        "district",
                        "district",
                        "district",
                    ],
                    "student_type": [
                        "All",
                        "School",
                        "University",
                        "University",
                    ],
                    "bin_start": [-5.0, -2.0, -2.0, 0.0],
                    "bin_end": [0.0, 0.0, 0.0, 2.0],
                    "geography_count": [1.0, 1.0, 1.0, 1.0],
                }
            ),
        },
    )
    alt_run = _summary_run_with_tables(
        label="Alt",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "district"],
                    "geography_id": ["all_geographies", "A", "B"],
                    "target_count": [30.0, 10.0, 20.0],
                    "modeled_count": [35.0, 13.0, 22.0],
                    "residual_count": [5.0, 3.0, 2.0],
                    "absolute_residual_count": [5.0, 3.0, 2.0],
                    "percent_error": [16.6667, 30.0, 10.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district"],
                    "bin_start": [1.0, 1.0],
                    "bin_end": [5.0, 5.0],
                    "geography_count": [1.0, 2.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": [
                        "all_geographies",
                        "district",
                        "district",
                        "district",
                    ],
                    "geography_id": ["all_geographies", "A", "A", "B"],
                    "student_type": ["All", "School", "University", "University"],
                    "target_count": [15.0, 8.0, 4.0, 3.0],
                    "modeled_count": [16.0, 9.0, 4.0, 4.0],
                    "residual_count": [1.0, 1.0, 0.0, 1.0],
                    "absolute_residual_count": [1.0, 1.0, 0.0, 1.0],
                    "percent_error": [6.6667, 12.5, 0.0, 33.3333],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": [
                        "all_geographies",
                        "district",
                        "district",
                        "district",
                    ],
                    "student_type": [
                        "All",
                        "School",
                        "University",
                        "University",
                    ],
                    "bin_start": [0.0, 0.0, -1.0, 1.0],
                    "bin_end": [2.0, 2.0, 1.0, 3.0],
                    "geography_count": [1.0, 1.0, 1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[base_run, alt_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Count"

    page = ShadowPricingPage(state, config)
    page.refresh(force=True)
    page.geo_level_sel.value = "District"
    page.refresh(force=True)

    workplace_plot = next(
        plot
        for plot in _collect_plotly_panes(page._workplace_plot_section)
        if plot.object.layout.title.text == "Workplace Residual Distribution"
    )
    initial_x = [list(trace.x) for trace in workplace_plot.object.data]

    workplace_plot = next(
        plot
        for plot in _collect_plotly_panes(page._workplace_plot_section)
        if plot.object.layout.title.text == "Workplace Residual Distribution"
    )
    district_x = [list(trace.x) for trace in workplace_plot.object.data]
    assert district_x != []

    state.value_mode = "Percent"
    page.refresh(force=True)

    workplace_plot = next(
        plot
        for plot in _collect_plotly_panes(page._workplace_plot_section)
        if plot.object.layout.title.text == "Workplace Residual Distribution"
    )
    assert (
        workplace_plot.object.layout.xaxis.title.text == "Residual (Modeled - Target)"
    )
    assert [list(trace.x) for trace in workplace_plot.object.data] == district_x
    assert workplace_plot.object.layout.yaxis.title.text == "Percent of Geographies (%)"

    page.student_type_sel.value = "University"
    page.refresh(force=True)

    school_tables = _collect_tabulators(page._school_table_section)
    school_df = pl.from_pandas(school_tables[0].value)
    assert set(school_df["student_type"].to_list()) == {"University"}
    assert school_df["percent_error"].to_list()[0].endswith("%")


def test_shadow_pricing_school_all_student_type_uses_upstream_rollup_histogram(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["district"],
                    "geography_id": ["A"],
                    "target_count": [10.0],
                    "modeled_count": [9.0],
                    "residual_count": [-1.0],
                    "absolute_residual_count": [1.0],
                    "percent_error": [-10.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["district"],
                    "bin_start": [-2.0],
                    "bin_end": [0.0],
                    "geography_count": [1.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["district", "district"],
                    "geography_id": ["A", "A"],
                    "student_type": ["School", "University"],
                    "target_count": [8.0, 4.0],
                    "modeled_count": [7.0, 5.0],
                    "residual_count": [-1.0, 1.0],
                    "absolute_residual_count": [1.0, 1.0],
                    "percent_error": [-12.5, 25.0],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": [
                        "district",
                        "district",
                        "district",
                        "district",
                        "district",
                        "district",
                    ],
                    "student_type": [
                        "School",
                        "School",
                        "University",
                        "University",
                        "All",
                        "All",
                    ],
                    "bin_start": [-2.0, 0.0, -2.0, 0.0, -2.0, 0.0],
                    "bin_end": [0.0, 2.0, 0.0, 2.0, 0.0, 2.0],
                    "geography_count": [3.0, 1.0, 2.0, 4.0, 5.0, 5.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Count"

    page = ShadowPricingPage(state, config)
    page.refresh(force=True)
    page.geo_level_sel.value = "District"
    page.student_type_sel.value = "All"
    page.refresh(force=True)

    school_plot = next(
        plot
        for plot in _collect_plotly_panes(page._school_plot_section)
        if plot.object.layout.title.text == "School Residual Distribution"
    )
    assert list(school_plot.object.data[0].x) == [-2.0, 0.0]
    assert list(school_plot.object.data[0].y) == [5.0, 5.0]


def test_shadow_pricing_tables_display_friendly_geography_columns(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district"],
                    "geography_id": ["all_geographies", "north_zone"],
                    "target_count": [10.0, 4.0],
                    "modeled_count": [9.0, 5.0],
                    "residual_count": [-1.0, 1.0],
                    "absolute_residual_count": [1.0, 1.0],
                    "percent_error": [-10.0, 25.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["district"],
                    "bin_start": [-2.0],
                    "bin_end": [0.0],
                    "geography_count": [1.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["district"],
                    "geography_id": ["school_zone"],
                    "student_type": ["School"],
                    "target_count": [8.0],
                    "modeled_count": [7.0],
                    "residual_count": [-1.0],
                    "absolute_residual_count": [1.0],
                    "percent_error": [-12.5],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["district"],
                    "student_type": ["School"],
                    "bin_start": [-2.0],
                    "bin_end": [0.0],
                    "geography_count": [1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    page = ShadowPricingPage(state, config)
    page.refresh(force=True)

    workplace = page.render_workplace_table(
        summary_run.summaries_by_mode["weighted"]["workplace_shadow_pricing_residuals"]
    )
    school = page.render_school_table(
        summary_run.summaries_by_mode["weighted"]["school_shadow_pricing_residuals"]
    )

    assert workplace.columns[:2] == ["Geography Type", "Geography Name"]
    assert workplace["Geography Type"].to_list() == ["All Geographies", "District"]
    assert workplace["Geography Name"].to_list() == ["All Geographies", "North Zone"]
    assert school.columns[:2] == ["Geography Type", "Geography Name"]
    assert school["Geography Type"].to_list() == ["District"]
    assert school["Geography Name"].to_list() == ["School Zone"]


def test_shadow_pricing_all_geographies_shows_point_mass_cards_instead_of_plots(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "workplace_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district"],
                    "geography_id": ["all_geographies", "A"],
                    "target_count": [30.0, 10.0],
                    "modeled_count": [28.0, 12.0],
                    "residual_count": [-2.0, 2.0],
                    "absolute_residual_count": [2.0, 2.0],
                    "percent_error": [-6.6667, 20.0],
                }
            ),
            "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district"],
                    "bin_start": [-4.0, -4.0],
                    "bin_end": [0.0, 0.0],
                    "geography_count": [1.0, 1.0],
                }
            ),
            "school_shadow_pricing_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district"],
                    "geography_id": ["all_geographies", "A"],
                    "student_type": ["All", "All"],
                    "target_count": [15.0, 8.0],
                    "modeled_count": [13.0, 7.0],
                    "residual_count": [-2.0, -1.0],
                    "absolute_residual_count": [2.0, 1.0],
                    "percent_error": [-13.3333, -12.5],
                }
            ),
            "school_shadow_pricing_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district"],
                    "student_type": ["All", "All"],
                    "bin_start": [-5.0, -2.0],
                    "bin_end": [0.0, 0.0],
                    "geography_count": [1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = ShadowPricingPage(state, config)
    page.refresh(force=True)

    workplace_cards = _collect_cards(page._workplace_plot_section)
    school_cards = _collect_cards(page._school_plot_section)
    assert any(
        getattr(card, "title", "") == "Workplace Residual Distribution Unavailable"
        and "point mass" in str(card.objects[0].object)
        for card in workplace_cards
        if getattr(card, "objects", None)
    )
    assert any(
        getattr(card, "title", "") == "School Residual Distribution Unavailable"
        and "point mass" in str(card.objects[0].object)
        for card in school_cards
        if getattr(card, "objects", None)
    )
    assert _collect_plotly_panes(page._workplace_plot_section) == []
    assert _collect_plotly_panes(page._school_plot_section) == []
    assert _collect_tabulators(page._workplace_table_section) != []
    assert _collect_tabulators(page._school_table_section) != []


def test_park_and_ride_location_page_uses_residual_plot_and_table(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "park_and_ride_location_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "district"],
                    "geography_id": ["all_geographies", "North", "South"],
                    "pnr_tour_count": [50.0, 5.0, 45.0],
                    "pnr_lot_capacity": [100.0, 30.0, 70.0],
                    "residual_count": [-50.0, -25.0, -25.0],
                    "absolute_residual_count": [50.0, 25.0, 25.0],
                    "percent_error": [-50.0, -83.3333, -35.7143],
                }
            ),
            "park_and_ride_location_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "district", "district"],
                    "bin_start": [-50.0, -30.0, 0.0],
                    "bin_end": [0.0, 0.0, 0.0],
                    "geography_count": [1.0, 1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Percent"

    page = ParkAndRideLocationPage(state, config)
    page.refresh(force=True)
    page.geo_level_sel.value = "District"
    page.refresh(force=True)

    plot = next(
        plot
        for plot in _collect_plotly_panes(page._plot_section)
        if plot.object.layout.title.text == "Park-and-Ride Residual Distribution"
    )
    assert plot.object.layout.xaxis.title.text == "Residual (Modeled - Capacity)"
    assert plot.object.layout.yaxis.title.text == "Percent of Geographies (%)"
    tables = _collect_tabulators(page._table_section)
    assert tables != []
    table_df = pl.from_pandas(tables[0].value)
    assert table_df.columns[:2] == ["Geography Type", "Geography Name"]
    assert table_df["Geography Type"].to_list() == ["District", "District"]
    assert table_df["Geography Name"].to_list() == ["North", "South"]
    assert table_df["percent_error"].to_list()[0].endswith("%")


def test_park_and_ride_location_all_geographies_and_maz_table_behavior(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "park_and_ride_location_residuals": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "maz"],
                    "geography_id": ["all_geographies", "1"],
                    "pnr_tour_count": [50.0, 10.0],
                    "pnr_lot_capacity": [100.0, 12.0],
                    "residual_count": [-50.0, -2.0],
                    "absolute_residual_count": [50.0, 2.0],
                    "percent_error": [-50.0, -16.6667],
                }
            ),
            "park_and_ride_location_residual_histogram": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "maz"],
                    "bin_start": [-50.0, -2.0],
                    "bin_end": [0.0, 0.0],
                    "geography_count": [1.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = ParkAndRideLocationPage(state, config)
    page.refresh(force=True)

    cards = _collect_cards(page._plot_section)
    assert any(
        getattr(card, "title", "") == "Park-and-Ride Residual Distribution Unavailable"
        and "point mass" in str(card.objects[0].object)
        for card in cards
        if getattr(card, "objects", None)
    )
    assert _collect_plotly_panes(page._plot_section) == []
    assert _collect_tabulators(page._table_section) != []

    page.geo_level_sel.value = "MAZ"
    page.refresh(force=True)

    cards = _collect_cards(page._table_section)
    assert any(
        getattr(card, "title", "") == "Park-and-Ride Residuals by Geography"
        and "enable_maz_geographies is false" in str(card.objects[0].object)
        for card in cards
        if getattr(card, "objects", None)
    )
    plots = _collect_plotly_panes(page._plot_section)
    assert any(
        plot.object.layout.title.text == "Park-and-Ride Residual Distribution"
        for plot in plots
    )


def test_mandatory_location_choice_external_workplace_aggregate_percent_uses_all_workers(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies"],
                    "geography_id": ["all_geographies"],
                    "internal_worker_count": [3.0],
                    "external_worker_count": [1.0],
                }
            ),
            "external_worker_workplace_locations": pl.DataFrame(
                {
                    "geography_type": ["all_geographies"],
                    "geography_id": ["all_geographies"],
                    "external_worker_count": [1.0],
                    "all_worker_count": [4.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )
    state.value_mode = "Percent"

    page = MandatoryLocationChoicePage(state, config)
    page.refresh(force=True)

    plots = _collect_plotly_panes(page._worker_section)
    external_plot = next(
        plot
        for plot in plots
        if plot.object.layout.title.text == "External Worker Workplace Location"
    )
    assert list(external_plot.object.data[0].x) == ["All Geographies"]
    assert list(external_plot.object.data[0].y) == [25.0]


def test_mandatory_location_choice_reorders_sections_and_shows_all_distance_plots(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies"],
                    "geography_id": ["all_geographies"],
                    "internal_worker_count": [3.0],
                    "external_worker_count": [1.0],
                }
            ),
            "external_worker_workplace_locations": pl.DataFrame(
                {
                    "geography_type": ["all_geographies"],
                    "geography_id": ["all_geographies"],
                    "external_worker_count": [1.0],
                    "all_worker_count": [4.0],
                }
            ),
            "work_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 40, 41],
                    "geography_type": [
                        "all_geographies",
                        "all_geographies",
                        "all_geographies",
                    ],
                    "geography_id": [
                        "all_geographies",
                        "all_geographies",
                        "all_geographies",
                    ],
                    "person_count": [6.0, 1.0, 3.0],
                }
            ),
            "school_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["all_geographies", "all_geographies"],
                    "geography_id": ["all_geographies", "all_geographies"],
                    "person_count": [5.0, 1.0],
                }
            ),
            "university_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["all_geographies", "all_geographies"],
                    "geography_id": ["all_geographies", "all_geographies"],
                    "person_count": [3.0, 2.0],
                }
            ),
            "work_from_home_rate_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies"],
                    "geography_id": ["all_geographies"],
                    "worker_count": [20.0],
                    "work_from_home_worker_count": [11.0],
                }
            ),
            "telecommute_frequency_distribution": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "all_geographies"],
                    "geography_id": ["all_geographies", "all_geographies"],
                    "telecommute_frequency": ["never", "often"],
                    "person_count": [7.0, 5.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work", "school", "university"],
                    "geography_type": [
                        "all_geographies",
                        "all_geographies",
                        "all_geographies",
                    ],
                    "geography_id": [
                        "all_geographies",
                        "all_geographies",
                        "all_geographies",
                    ],
                    "average_tour_distance": [8.0, 4.0, 10.0],
                    "person_count": [5.0, 3.0, 2.0],
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

    assert not hasattr(page, "location_type_sel")
    assert hasattr(page, "geography_sel")
    assert list(page.geography_sel.options) == ["All Geographies"]
    assert page.view.objects.index(page._remote_work_section) < page.view.objects.index(
        page._distance_section
    )
    assert page.view.objects.index(page._distance_section) < page.view.objects.index(
        page._worker_section
    )
    assert page.view.objects.index(page._worker_section) < page.view.objects.index(
        page._mandatory_distance_table_section
    )

    distance_plots = _collect_plotly_panes(page._distance_section)
    assert [plot.object.layout.title.text for plot in distance_plots] == [
        "Workplace Location Distance Distribution",
        "School Location Distance Distribution",
        "University Location Distance Distribution",
    ]
    worker_table = _collect_tabulators(page._worker_section)[0].value
    assert worker_table.columns.tolist()[:2] == [
        "Geography Type",
        "Geography Name",
    ]
    assert worker_table["Geography Type"].tolist() == ["All Geographies"]
    assert worker_table["Geography Name"].tolist() == ["All Geographies"]
    assert page.mandatory_distance_range.min_widget.disabled is False
    assert page.mandatory_distance_range.max_widget.disabled is False
    assert page.mandatory_distance_range.current_range() == (0.0, 40.0)
    assert list(distance_plots[0].object.data[0].x) == [1.0, 40.0]
    assert list(distance_plots[0].object.layout.xaxis.ticktext) == [
        "0",
        "2",
        "4",
        "6",
        "8",
        "10",
        "12",
        "14",
        "16",
        "18",
        "20",
        "22",
        "24",
        "26",
        "28",
        "30",
        "32",
        "34",
        "36",
        "38",
        "40+",
    ]
    assert list(distance_plots[0].object.layout.xaxis.range) == [0.0, 40.0]
    assert list(distance_plots[0].object.data[0].y) == [60.0, 40.0]
    page.mandatory_distance_range.min_widget.value = 2.0
    page.mandatory_distance_range.max_widget.value = "10"
    page.refresh(force=True)
    ranged_plot = _collect_plotly_panes(page._distance_section)[0]
    assert list(ranged_plot.object.layout.xaxis.range) == [2.0, 10.0]
    page.mandatory_distance_range.reset()
    page.refresh(force=True)
    reset_plot = _collect_plotly_panes(page._distance_section)[0]
    assert list(reset_plot.object.layout.xaxis.range) == [0.0, 40.0]
    page.mandatory_distance_range.min_widget.value = 10.0
    page.mandatory_distance_range.max_widget.value = "2"
    page.refresh(force=True)
    assert any(
        card.title == "Mandatory Location Distance Data Not Available"
        for card in _collect_cards(page._distance_section)
    )
    comparison_table = _collect_tabulators(page._mandatory_distance_table_section)[
        0
    ].value
    comparison_tabs = _collect_tabs(page._mandatory_distance_table_section)[0]
    assert list(comparison_tabs._names) == ["Base"]
    assert comparison_table.columns.tolist() == [
        "Mandatory Tour Purpose",
        "Average Mandatory Tour Distance",
        "Base Run Average Mandatory Tour Distance",
        "Difference",
        "% Difference",
    ]
    assert comparison_table["Mandatory Tour Purpose"].tolist() == [
        "work",
        "school",
        "university",
    ]
    assert comparison_table["Average Mandatory Tour Distance"].tolist() == [
        "8",
        "4",
        "10",
    ]
    assert comparison_table["Base Run Average Mandatory Tour Distance"].tolist() == [
        "8",
        "4",
        "10",
    ]
    assert comparison_table["Difference"].tolist() == ["0", "0", "0"]
    assert comparison_table["% Difference"].tolist() == ["0.00%", "0.00%", "0.00%"]


def test_mandatory_location_choice_supports_configured_geography_levels_for_distance_sections(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "school_district"],
                    "geography_id": ["all_geographies", "North"],
                    "internal_worker_count": [3.0, 2.0],
                    "external_worker_count": [1.0, 1.0],
                }
            ),
            "external_worker_workplace_locations": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "school_district"],
                    "geography_id": ["all_geographies", "North"],
                    "external_worker_count": [1.0, 1.0],
                    "all_worker_count": [4.0, 3.0],
                }
            ),
            "work_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 1, 2, 2],
                    "geography_type": [
                        "school_district",
                        "school_district",
                        "school_district",
                        "school_district",
                    ],
                    "geography_id": ["North", "South", "North", "South"],
                    "person_count": [2.0, 3.0, 1.0, 4.0],
                }
            ),
            "school_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["school_district", "school_district"],
                    "geography_id": ["North", "North"],
                    "person_count": [5.0, 1.0],
                }
            ),
            "university_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["school_district", "school_district"],
                    "geography_id": ["North", "North"],
                    "person_count": [3.0, 2.0],
                }
            ),
            "work_from_home_rate_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "school_district"],
                    "geography_id": ["all_geographies", "North"],
                    "worker_count": [20.0, 8.0],
                    "work_from_home_worker_count": [11.0, 5.0],
                }
            ),
            "telecommute_frequency_distribution": pl.DataFrame(
                {
                    "geography_type": [
                        "school_district",
                        "school_district",
                        "school_district",
                    ],
                    "geography_id": ["North", "North", "South"],
                    "telecommute_frequency": ["never", "often", "never"],
                    "person_count": [7.0, 5.0, 4.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work", "work", "school", "university"],
                    "geography_type": [
                        "school_district",
                        "school_district",
                        "school_district",
                        "school_district",
                    ],
                    "geography_id": ["North", "South", "North", "North"],
                    "average_tour_distance": [8.0, 12.0, 4.0, 10.0],
                    "person_count": [2.0, 3.0, 3.0, 2.0],
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

    assert "School District" in list(page.geo_level_sel.options)
    assert list(page.geography_sel.options) == ["All Geographies"]
    page.geo_level_sel.value = "School District"
    page.refresh(force=True)
    assert list(page.geography_sel.options) == [
        "All School Districts",
        "North",
        "South",
    ]
    page.geography_sel.value = "North"
    page.refresh(force=True)

    distance_cards = _collect_cards(page._distance_section)
    assert distance_cards == []
    distance_plots = _collect_plotly_panes(page._distance_section)
    assert len(distance_plots) == 3
    work_distance_plot = next(
        plot
        for plot in distance_plots
        if plot.object.layout.title.text == "Workplace Location Distance Distribution"
    )
    assert list(work_distance_plot.object.data[0].x) == [1.0, 2.0]
    assert list(work_distance_plot.object.data[0].y) == pytest.approx(
        [66.66666666666666, 33.33333333333333]
    )

    worker_table = _collect_tabulators(page._worker_section)[0].value
    assert worker_table["Geography Type"].tolist() == ["School District"]
    assert worker_table["Geography Name"].tolist() == ["North"]

    worker_plots = _collect_plotly_panes(page._worker_section)
    external_workplace_plot = next(
        plot
        for plot in worker_plots
        if plot.object.layout.title.text == "External Worker Workplace Location"
    )
    assert list(external_workplace_plot.object.data[0].x) == ["North"]

    remote_work_plots = _collect_plotly_panes(page._remote_work_section)
    wfh_plot = next(
        plot
        for plot in remote_work_plots
        if plot.object.layout.title.text
        in {
            "Work From Home Rate by Geography",
            "Workers Working From Home by Geography",
        }
    )
    assert list(wfh_plot.object.data[0].x) == ["North"]
    telecommute_plot = next(
        plot
        for plot in remote_work_plots
        if plot.object.layout.title.text == "Telecommute Rate"
    )
    assert list(telecommute_plot.object.data[0].x) == ["never", "often"]

    comparison_table = _collect_tabulators(page._mandatory_distance_table_section)[
        0
    ].value
    comparison_tabs = _collect_tabs(page._mandatory_distance_table_section)[0]
    assert list(comparison_tabs._names) == ["Base"]
    assert comparison_table.columns.tolist() == [
        "Mandatory Tour Purpose",
        "Average Mandatory Tour Distance",
        "Base Run Average Mandatory Tour Distance",
        "Difference",
        "% Difference",
    ]
    assert comparison_table["Average Mandatory Tour Distance"].tolist() == [
        "8",
        "4",
        "10",
    ]
    assert comparison_table["Base Run Average Mandatory Tour Distance"].tolist() == [
        "8",
        "4",
        "10",
    ]
    assert comparison_table["Difference"].tolist() == ["0", "0", "0"]
    assert comparison_table["% Difference"].tolist() == ["0.00%", "0.00%", "0.00%"]

    page.geography_sel.value = "South"
    page.refresh(force=True)
    south_remote_work_plots = _collect_plotly_panes(page._remote_work_section)
    south_telecommute_plot = next(
        plot
        for plot in south_remote_work_plots
        if plot.object.layout.title.text == "Telecommute Rate"
    )
    assert list(south_telecommute_plot.object.data[0].x) == ["never", "often"]
    assert list(south_telecommute_plot.object.data[0].y) == [100.0, 0.0]


def test_mandatory_location_choice_reuses_collected_data_on_selector_changes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "internal_external_worker_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "school_district"],
                    "geography_id": ["all_geographies", "North"],
                    "internal_worker_count": [3.0, 2.0],
                    "external_worker_count": [1.0, 1.0],
                }
            ),
            "external_worker_workplace_locations": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "school_district"],
                    "geography_id": ["all_geographies", "North"],
                    "external_worker_count": [1.0, 1.0],
                    "all_worker_count": [4.0, 3.0],
                }
            ),
            "commuting_flows": pl.DataFrame(
                {
                    "origin_geography_type": ["all_geographies", "school_district"],
                    "origin_geography_id": ["all_geographies", "North"],
                    "destination_geography_type": [
                        "all_geographies",
                        "school_district",
                    ],
                    "destination_geography_id": ["all_geographies", "North"],
                    "commuter_count": [4.0, 3.0],
                }
            ),
            "work_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["school_district", "school_district"],
                    "geography_id": ["North", "North"],
                    "person_count": [2.0, 1.0],
                }
            ),
            "school_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["school_district", "school_district"],
                    "geography_id": ["North", "North"],
                    "person_count": [5.0, 1.0],
                }
            ),
            "university_location_distance_distribution_by_geography": pl.DataFrame(
                {
                    "distance_bin": [1, 2],
                    "geography_type": ["school_district", "school_district"],
                    "geography_id": ["North", "North"],
                    "person_count": [3.0, 2.0],
                }
            ),
            "work_from_home_rate_by_geography": pl.DataFrame(
                {
                    "geography_type": ["all_geographies", "school_district"],
                    "geography_id": ["all_geographies", "North"],
                    "worker_count": [20.0, 8.0],
                    "work_from_home_worker_count": [11.0, 5.0],
                }
            ),
            "telecommute_frequency_distribution": pl.DataFrame(
                {
                    "geography_type": ["school_district"],
                    "geography_id": ["North"],
                    "telecommute_frequency": ["never"],
                    "person_count": [7.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_type": ["school_district"],
                    "geography_id": ["North"],
                    "average_tour_distance": [8.0],
                    "person_count": [2.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = MandatoryLocationChoicePage(state, config)
    original_collect = page._collect_data
    call_count = 0

    def _counted_collect_data():
        nonlocal call_count
        call_count += 1
        return original_collect()

    page._collect_data = _counted_collect_data  # type: ignore[method-assign]

    page.refresh(force=True)
    assert call_count == 1

    page.geo_level_sel.value = "School District"
    assert call_count == 1

    page.geography_sel.value = "North"
    assert call_count == 1


def test_traffic_validation_removes_direction_period_selectors_and_count_card(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "traffic_count_comparisons": pl.DataFrame(
                {
                    "direction": ["outbound", "inbound"],
                    "count_period": ["AM", "PM"],
                    "count_location_id": ["1", "2"],
                    "observed_volume": [10.0, 20.0],
                    "modeled_volume": [11.0, 19.0],
                }
            ),
            "screenline_flow_comparisons": pl.DataFrame(
                {
                    "direction": ["outbound"],
                    "count_period": ["AM"],
                    "screenline_id": ["A"],
                    "facility_type": [3],
                    "observed_volume": [15.0],
                    "modeled_volume": [14.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TrafficValidationPage(state, config)
    page.refresh(force=True)

    assert [selector.selector_id for selector in page.registered_selectors] == [
        "demo_period",
        "demo_facility_type",
        "demo_top_period",
        "demo_top_n",
        "screenline_period",
        "screenline_facility_type",
    ]
    assert page.demo_period_sel.name == "Period"
    assert page.demo_top_period_sel.name == "Period"
    assert not hasattr(page, "direction_sel")
    assert not hasattr(page, "count_period_sel")
    assert page.view.objects[2].object == "### Traffic Volume Summaries"
    assert list(page.view.objects[3].objects) == [
        page.demo_period_sel,
        page.demo_facility_sel,
    ]
    sections = {section.section_id: section for section in page.registered_sections}
    assert sections["facility_summaries.body"].selector_ids == ()
    assert sections["observed_model_fit.body"].selector_ids == (
        "demo_period",
        "demo_facility_type",
    )
    assert sections["link_tables.volume"].selector_ids == ("demo_period",)
    assert sections["screenlines.body"].selector_ids == (
        "screenline_period",
        "screenline_facility_type",
    )
    assert page.view.objects[-3].object == "### Screenline Flow Summaries"
    assert list(page.view.objects[-2].objects) == [
        page.screenline_period_sel,
        page.screenline_facility_sel,
    ]
    plot_titles = [
        plot.object.layout.title.text
        for plot in _collect_plotly_panes(page._screenline_body)
    ]
    assert plot_titles == ["Screenline Observed vs Modeled - Day"]


def test_traffic_validation_external_volume_table_compares_observed_and_modeled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "display:",
            "  labels:",
            "    facility_type:",
            "      mapping:",
            "        4: Minor Arterial",
            "        3: Principal Arterial",
        ],
    )
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "traffic_count_comparisons": pl.DataFrame(
                {
                    "direction": ["outbound"],
                    "count_period": ["AM"],
                    "count_location_id": ["1"],
                    "observed_volume": [10.0],
                    "modeled_volume": [11.0],
                }
            ),
            "screenline_flow_comparisons": pl.DataFrame(
                {
                    "direction": ["outbound", "outbound", "inbound"],
                    "count_period": ["AM", "AM", "AM"],
                    "screenline_id": ["A", "B", "C"],
                    "facility_type": [3, 3, 4],
                    "observed_volume": [15.0, 25.0, 35.0],
                    "modeled_volume": [14.0, 27.0, 30.0],
                }
            ),
            "link_validation_summary": pl.DataFrame(
                {
                    "id": [1, 2],
                    "From_Node": [100, 101],
                    "To_Node": [200, 201],
                    "FACTYPE": [3, 4],
                    "am_vol": [10.0, 20.0],
                    "md_vol": [0.0, 0.0],
                    "pm_vol": [0.0, 0.0],
                    "day_vol": [100.0, 200.0],
                }
            ),
            "count_location_counts_validation_summary": pl.DataFrame(
                {
                    "id": [1, 2],
                    "FACTYPE": [3, 4],
                    "am_vol": [10.0, 20.0],
                    "md_vol": [0.0, 0.0],
                    "pm_vol": [0.0, 0.0],
                    "day_vol": [100.0, 200.0],
                }
            ),
            "count_location_volumes_validation_summary": pl.DataFrame(
                {
                    "id": [1, 2],
                    "FACTYPE": [3, 4],
                    "am_vol": [11.0, 21.0],
                    "md_vol": [0.0, 0.0],
                    "pm_vol": [0.0, 0.0],
                    "day_vol": [110.0, 210.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TrafficValidationPage(state, config)
    page.refresh(force=True)
    assert list(page.demo_facility_sel.options) == [
        "All",
        "Minor Arterial",
        "Principal Arterial",
    ]
    assert page.demo_top_n_sel.name == "Top N by Modeled Volume"
    page.demo_period_sel.value = "AM"
    page.demo_facility_sel.value = "Principal Arterial"
    page.screenline_period_sel.value = "AM"
    page.screenline_facility_sel.value = "Principal Arterial"
    page.refresh(force=True)

    tables = _collect_tabulators(page._external_top_body)
    tabs = _collect_tabs(page._external_top_body)
    assert len(tables) == 1
    assert list(tabs[-1]._names) == ["Base"]
    table = tables[0].value
    assert table.columns.tolist() == [
        "link_id",
        "facility_type",
        "From_Node",
        "To_Node",
        "Observed Link Volume",
        "Modeled Link Volume",
        "Difference",
        "% Difference",
    ]
    assert tables[0].titles["link_id"] == "Link ID"
    assert table.to_dict("records") == [
        {
            "link_id": "1",
            "facility_type": "Principal Arterial",
            "From_Node": "100",
            "To_Node": "200",
            "Observed Link Volume": "100",
            "Modeled Link Volume": "110",
            "Difference": "10",
            "% Difference": "10.00%",
        }
    ]
    assert tables[0]._configuration == {
        "columns": [{"field": "Difference", "sorter": "number"}]
    }
    assert page.view.objects[2].object == "### Traffic Volume Summaries"
    assert list(page.view.objects[3].objects) == [
        page.demo_period_sel,
        page.demo_facility_sel,
    ]
    facility_tables = _collect_tabulators(page._facility_summary_body)
    assert len(facility_tables) == 1
    facility_table = facility_tables[0].value
    assert facility_table.columns.tolist() == [
        "Facility Type",
        "n",
        "Total Observed Count",
        "Total Modeled Count",
        "% Difference",
        "RMSE",
        "RMSPE",
        "R²",
    ]
    assert facility_table.to_dict("records") == [
        {
            "Facility Type": "Minor Arterial",
            "n": "1",
            "Total Observed Count": "200",
            "Total Modeled Count": "210",
            "% Difference": "5.00%",
            "RMSE": "10",
            "RMSPE": "5.00%",
            "R²": None,
        },
        {
            "Facility Type": "Principal Arterial",
            "n": "1",
            "Total Observed Count": "100",
            "Total Modeled Count": "110",
            "% Difference": "10.00%",
            "RMSE": "10",
            "RMSPE": "10.00%",
            "R²": None,
        },
    ]
    assert facility_tables[0]._configuration == {
        "columns": [
            {"field": "n", "sorter": "number"},
            {"field": "RMSE", "sorter": "number"},
            {"field": "R²", "sorter": "number"},
        ]
    }
    assert any(
        isinstance(obj, pn.pane.Markdown)
        and obj.object == "### Top Count Locations by Modeled Volume"
        for obj in page.view.objects
    )
    top_count_section = page._external_top_body
    assert (
        top_count_section.objects[0].object
        == "#### Observed vs Modeled Volumes - Day (Top 25 by Modeled Volume)"
    )
    plot_titles = [
        plot.object.layout.title.text
        for plot in _collect_plotly_panes(page._external_volume_body)
        + _collect_plotly_panes(page._link_volume_body)
        + _collect_plotly_panes(page._screenline_body)
    ]
    bar_plot = next(
        plot
        for plot in _collect_plotly_panes(page._link_volume_body)
        if plot.object.layout.title.text == "Link Volume by Facility Type - AM"
    )
    count_plot = next(
        plot
        for plot in _collect_plotly_panes(page._external_volume_body)
        if plot.object.layout.title.text == "Count Location Observed vs Modeled - AM"
    )
    reference_line = count_plot.object.data[-1]

    assert reference_line.name == "1:1 line"
    assert list(reference_line.x) == [10.0, 11.0]
    assert list(reference_line.y) == [10.0, 11.0]
    assert reference_line.line.color == "#BDBDBD"
    assert reference_line.line.dash == "dash"
    assert reference_line.showlegend is True
    assert list(count_plot.object.layout.xaxis.range) == [10.0, 11.0]
    assert list(count_plot.object.layout.yaxis.range) == [10.0, 11.0]
    assert count_plot.object.layout.xaxis.constrain == "domain"
    assert count_plot.object.layout.yaxis.constrain == "domain"
    assert count_plot.object.layout.yaxis.scaleanchor == "x"
    assert count_plot.object.layout.legend.orientation == "v"
    assert count_plot.object.layout.legend.x == 1.02
    assert count_plot.sizing_mode == "scale_width"
    assert count_plot.aspect_ratio == 1.0
    assert "Observed Count (vehicles): %{x}" in count_plot.object.data[0].hovertemplate
    assert "Modeled Volume (vehicles): %{y}" in count_plot.object.data[0].hovertemplate
    assert list(bar_plot.object.data[0].x) == [
        "Minor Arterial",
        "Principal Arterial",
    ]
    assert bar_plot.object.layout.showlegend is True
    assert bar_plot.object.data[0].name == "Base"
    assert plot_titles[-1] == "Screenline Observed vs Modeled - AM"
    screenline_plot = _collect_plotly_panes(page._screenline_body)[0]
    assert screenline_plot.object.data[0].name == "Base"
    assert screenline_plot.object.data[-1].name == "1:1 line"
    assert screenline_plot.object.data[1].name == "Base fit"
    assert len(screenline_plot.object.data[1].x) == 101
    assert "R²" in screenline_plot.object.data[1].hovertemplate
    assert "y = 1.30x - 5.50" in screenline_plot.object.data[1].hovertemplate
    assert not screenline_plot.object.layout.annotations
    assert (
        "Observed Screenline Flow (vehicles): %{x}"
        in screenline_plot.object.data[0].hovertemplate
    )
    assert (
        "Modeled Screenline Flow (vehicles): %{y}"
        in screenline_plot.object.data[0].hovertemplate
    )
    assert screenline_plot.object.layout.yaxis.scaleanchor == "x"
    assert screenline_plot.object.layout.legend.x == 1.02
    assert "Traffic Count Comparisons" not in plot_titles
    assert "Demo Link Volume by Facility Type - Day" not in plot_titles
    assert "Link Volume by Facility Type - AM" in plot_titles


def test_transit_validation_places_each_selector_with_its_plot(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "transit_boardings_by_operator_and_technology": pl.DataFrame(
                {
                    "technology": ["bus", "rail"],
                    "operator": ["A", "B"],
                    "boardings": [10.0, 20.0],
                }
            ),
            "transit_transfer_rate": pl.DataFrame(
                {
                    "technology": ["bus"],
                    "access_mode": ["walk"],
                    "operator": ["A"],
                    "transfer_rate": [1.2],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TransitValidationPage(state, config)
    page.refresh(force=True)

    assert list(page.technology_sel.options) == ["All", "bus", "rail"]
    assert list(page.view.objects[2].objects) == [page.technology_sel]
    assert list(page.view.objects[6].objects) == [page.access_mode_sel]
    sections = {section.section_id: section for section in page.registered_sections}
    assert sections["transit_boardings_body"].selector_ids == ("technology",)
    assert sections["transit_transfer_body"].selector_ids == ("access_mode",)

    page.technology_sel.value = "rail"
    page.access_mode_sel.value = "walk"
    page.refresh(force=True)
    transfer_plot = _collect_plotly_panes(page._transfer_body)[0]
    assert transfer_plot.object.layout.title.text == "Transit Transfer Rate - walk"


@pytest.mark.parametrize(
    ("page_type", "section_names"),
    [
        (
            TrafficValidationPage,
            (
                "_facility_summary_body",
                "_external_volume_body",
                "_link_volume_body",
                "_external_top_body",
                "_screenline_body",
            ),
        ),
        (
            TransitValidationPage,
            ("_boardings_body", "_transfer_body"),
        ),
        (
            VMTValidationPage,
            (
                "_vmt_overview_body",
                "_personal_vmt_body",
                "_non_motorized_vmt_body",
                "_external_vmt_body",
                "_body",
                "_bicycle_body",
            ),
        ),
        (RegionalValidationPage, ("_body",)),
    ],
)
def test_validation_visualizations_render_cards_when_data_is_unavailable(
    tmp_path: Path,
    page_type: type,
    section_names: tuple[str, ...],
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(label="Base", weighted={})
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = page_type(state, config)
    page.refresh(force=True)

    for section_name in section_names:
        cards = _collect_cards(getattr(page, section_name))
        assert len(cards) == 1, section_name
        assert cards[0].title == "Data Not Available"


def test_tour_distance_chart_casts_distance_bins_consistently_across_runs(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run_a = _summary_run_with_tables(
        label="A",
        weighted={
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes", "all_tour_purposes"],
                    "distance_bin": ["0", "1"],
                    "tour_count": [5.0, 2.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.0],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["shopping"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [4.0],
                }
            ),
        },
    )
    summary_run_b = _summary_run_with_tables(
        label="B",
        weighted={
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "distance_bin": [0],
                    "tour_count": [7.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.0],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["shopping"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [4.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run_a, summary_run_b],
        weighting_modes=config.weighting_modes,
    )

    page = TourDistancePage(state, config)
    page.refresh(force=True)

    plot = next(
        obj for obj in page._distance_section.objects if isinstance(obj, pn.pane.Plotly)
    )
    traces = {trace.name: list(trace.x) for trace in plot.object.data}
    assert traces["A"] == [0.0, 1.0]
    assert traces["B"] == [0.0]
    assert list(plot.object.layout.xaxis.ticktext) == [
        *[str(value) for value in range(0, 40, 2)],
        "40+",
    ]
    assert list(plot.object.layout.xaxis.range) == [0.0, 40.0]
    page.tour_distance_range.min_widget.value = 0.25
    page.tour_distance_range.max_widget.value = "1"
    page.refresh(force=True)
    ranged_plot = next(
        obj for obj in page._distance_section.objects if isinstance(obj, pn.pane.Plotly)
    )
    assert list(ranged_plot.object.layout.xaxis.range) == [0.25, 1.0]
    page.tour_distance_range.reset()
    page.refresh(force=True)
    reset_plot = next(
        obj for obj in page._distance_section.objects if isinstance(obj, pn.pane.Plotly)
    )
    assert list(reset_plot.object.layout.xaxis.range) == [0.0, 40.0]
    page.tour_distance_range.min_widget.value = 1.0
    page.tour_distance_range.max_widget.value = "1"
    page.refresh(force=True)
    assert any(
        card.title == "Tour Distance Data Not Available"
        for card in _collect_cards(page._distance_section)
    )


def test_tour_distance_nonmandatory_average_table_compares_to_base_run(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run_a = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "distance_bin": [0],
                    "tour_count": [5.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.0],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["shopping", "eatout"],
                    "geography_type": ["district", "district"],
                    "geography_id": ["North", "North"],
                    "average_tour_distance": [4.0, 8.0],
                    "tour_count": [2.0, 1.0],
                }
            ),
        },
    )
    summary_run_b = _summary_run_with_tables(
        label="Build",
        weighted={
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "distance_bin": [0],
                    "tour_count": [7.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.0],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["shopping", "eatout"],
                    "geography_type": ["district", "district"],
                    "geography_id": ["North", "North"],
                    "average_tour_distance": [5.0, 6.0],
                    "tour_count": [2.0, 1.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run_a, summary_run_b],
        weighting_modes=config.weighting_modes,
    )

    page = TourDistancePage(state, config)
    page.refresh(force=True)

    page.geo_level_sel.value = "District"
    page.refresh(force=True)
    assert list(page.geography_sel.options) == ["All Districts", "North"]
    page.geography_sel.value = "North"
    page.refresh(force=True)

    tables = _collect_tabulators(page._average_section)
    comparison_tabs = _collect_tabs(page._average_section)[0]
    assert list(comparison_tabs._names) == ["Base", "Build"]
    assert len(tables) == 2
    base_table = tables[0].value
    build_table = tables[1].value
    expected_columns = [
        "Non-Mandatory Tour Purpose",
        "Average Non-Mandatory Tour Distance",
        "Base Run Average Non-Mandatory Tour Distance",
        "Difference",
        "% Difference",
    ]
    assert base_table.columns.tolist() == expected_columns
    assert build_table.columns.tolist() == expected_columns
    assert base_table["Non-Mandatory Tour Purpose"].tolist() == [
        "shopping",
        "eatout",
    ]
    assert build_table["Non-Mandatory Tour Purpose"].tolist() == [
        "shopping",
        "eatout",
    ]
    assert base_table["Average Non-Mandatory Tour Distance"].tolist() == ["4", "8"]
    assert base_table["Base Run Average Non-Mandatory Tour Distance"].tolist() == [
        "4",
        "8",
    ]
    assert base_table["Difference"].tolist() == ["0", "0"]
    assert base_table["% Difference"].tolist() == ["0.00%", "0.00%"]
    assert build_table["Average Non-Mandatory Tour Distance"].tolist() == ["5", "6"]
    assert build_table["Base Run Average Non-Mandatory Tour Distance"].tolist() == [
        "4",
        "8",
    ]
    assert build_table["Difference"].tolist() == ["1", "2"]
    assert build_table["% Difference"].tolist() == ["25.00%", "-25.00%"]


def test_tour_distance_nonmandatory_average_table_filters_to_selected_geography(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run_a = _summary_run_with_tables(
        label="Base",
        weighted={
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "distance_bin": [0],
                    "tour_count": [5.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.0],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["shopping", "shopping"],
                    "geography_type": ["district", "district"],
                    "geography_id": ["North", "South"],
                    "average_tour_distance": [4.0, 8.0],
                    "tour_count": [2.0, 3.0],
                }
            ),
        },
    )
    summary_run_b = _summary_run_with_tables(
        label="Build",
        weighted={
            "tour_distance_by_tour_purpose": pl.DataFrame(
                {
                    "tour_purpose": ["all_tour_purposes"],
                    "distance_bin": [0],
                    "tour_count": [7.0],
                }
            ),
            "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "mandatory_tour_purpose": ["work"],
                    "geography_level": ["Region"],
                    "average_tour_distance": [8.0],
                }
            ),
            "average_nonmandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
                {
                    "nonmandatory_tour_purpose": ["shopping", "shopping"],
                    "geography_type": ["district", "district"],
                    "geography_id": ["North", "South"],
                    "average_tour_distance": [5.0, 12.0],
                    "tour_count": [2.0, 3.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run_a, summary_run_b],
        weighting_modes=config.weighting_modes,
    )

    page = TourDistancePage(state, config)
    page.refresh(force=True)
    page.geo_level_sel.value = "District"
    page.refresh(force=True)
    assert list(page.geography_sel.options) == ["All Districts", "North", "South"]

    page.geography_sel.value = "South"
    page.refresh(force=True)

    comparison_tabs = _collect_tabs(page._average_section)[0]
    assert list(comparison_tabs._names) == ["Base", "Build"]
    tables = _collect_tabulators(page._average_section)
    base_table = tables[0].value
    build_table = tables[1].value
    assert base_table["Non-Mandatory Tour Purpose"].tolist() == ["shopping"]
    assert build_table["Non-Mandatory Tour Purpose"].tolist() == ["shopping"]
    assert base_table["Average Non-Mandatory Tour Distance"].tolist() == ["8"]
    assert base_table["Base Run Average Non-Mandatory Tour Distance"].tolist() == ["8"]
    assert base_table["Difference"].tolist() == ["0"]
    assert base_table["% Difference"].tolist() == ["0.00%"]
    assert build_table["Average Non-Mandatory Tour Distance"].tolist() == ["12"]
    assert build_table["Base Run Average Non-Mandatory Tour Distance"].tolist() == ["8"]
    assert build_table["Difference"].tolist() == ["4"]
    assert build_table["% Difference"].tolist() == ["50.00%"]


def test_bar_chart_pins_category_order_from_input_sequence() -> None:
    chart = Plotter(RenderContext()).bar(
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
        x="fuel_type",
        y="vehicle_count",
    )

    category_array = list(chart.object.layout.xaxis.categoryarray)
    assert category_array == ["Hybrid", "Battery EV", "Gasoline"]


def test_tour_time_live_page_uses_shared_summary_helpers(tmp_path: Path) -> None:
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
                        "work",
                    ],
                    "time_bin": [1, 2, 1, 2, 48],
                    "departure_tour_count": [5.0, 6.0, 3.0, 4.0, 0.0],
                    "arrival_tour_count": [4.0, 5.0, 2.0, 3.0, 0.0],
                    "duration_tour_count": [2.0, 3.0, 1.0, 2.0, 0.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[tod_summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = TourTimePage(state, config)
    page.refresh(force=True)

    assert list(page.purpose_sel.options) == ["All Tour Purposes", "work"]
    page.purpose_sel.value = "work"
    page.refresh(force=True)
    assert page._body.objects
    departure_chart = _collect_plotly_panes(page._body)[0]
    assert list(departure_chart.object.data[0].x)[:2] == ["03:00", "03:30"]
    assert list(departure_chart.object.layout.xaxis.tickvals) == ["03:00"]
    assert list(departure_chart.object.layout.xaxis.ticktext) == ["3:00"]
    departure_hover = str(departure_chart.object.data[0].customdata[0])
    assert "Clock Time: 03:00" in departure_hover
    assert "start at 03:00" not in departure_hover


def test_vehicle_ownership_type_live_page_uses_shared_summary_helpers(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    long_term_summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "auto_ownership_distribution": pl.DataFrame(
                {
                    "household_size": ["1", "1", "5+", "5+"],
                    "household_vehicle_count": [0, 5, 4, 5],
                    "household_count": [12.0, 6.0, 8.0, 10.0],
                }
            ),
            "autonomous_vehicle_ownership_totals": pl.DataFrame(
                {
                    "household_with_autonomous_vehicle_count": [4.0],
                }
            ),
            "vehicle_age_distribution": pl.DataFrame(
                {
                    "age": ["1", "20+"],
                    "vehicle_count": [8.0, 2.0],
                }
            ),
            "vehicle_fuel_type_distribution": pl.DataFrame(
                {
                    "fuel_type": ["Gas", "Hybrid"],
                    "vehicle_count": [7.0, 3.0],
                }
            ),
            "vehicle_body_type_distribution": pl.DataFrame(
                {
                    "body_type": ["Car", "SUV"],
                    "vehicle_count": [6.0, 4.0],
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
    state.value_mode = "Count"

    page = VehicleOwnershipTypePage(state, config)
    page.refresh(force=True)

    assert page.view.objects
    assert list(page.hhsize_sel.options) == ["All", "1", "2", "3", "4", "5+"]
    auto_plot = next(
        plot
        for plot in _collect_plotly_panes(page._ownership_section)
        if str(plot.object.layout.title.text)
        == "Auto Ownership by Household Size - All"
    )
    assert list(auto_plot.object.data[0].x) == ["0", "4+"]
    assert list(auto_plot.object.data[0].y) == [12.0, 24.0]

    page.hhsize_sel.value = "5+"
    page.refresh(force=True)
    filtered_plot = next(
        plot
        for plot in _collect_plotly_panes(page._ownership_section)
        if str(plot.object.layout.title.text) == "Auto Ownership by Household Size - 5+"
    )
    assert list(filtered_plot.object.data[0].x) == ["4+"]
    assert list(filtered_plot.object.data[0].y) == [18.0]


def test_vehicle_ownership_type_renders_cards_for_empty_attribute_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    summary_run = _summary_run_with_tables(
        label="Base",
        weighted={
            "auto_ownership_distribution": pl.DataFrame(
                {
                    "household_vehicle_count": [1],
                    "household_count": [12.0],
                }
            ),
        },
    )
    state = DashboardState(
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = VehicleOwnershipTypePage(state, config)
    page.refresh(force=True)

    assert not _collect_plotly_panes(page._vehicle_mix_section)
    cards = _collect_cards(page._vehicle_mix_section)
    assert len(cards) == 3
    card_text = "\n".join(str(card.objects[0].object) for card in cards if card.objects)
    assert "vehicle_age_distribution" in card_text
    assert "vehicle_fuel_type_distribution" in card_text
    assert "vehicle_body_type_distribution" in card_text
