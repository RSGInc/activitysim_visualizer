from __future__ import annotations

from pathlib import Path
import sys
import time

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.components import bar_chart
from dashboard.pages.long_term_choices.individual_choices import (
    IndividualChoicesPage,
)
from dashboard.pages.long_term_choices.mandatory_location_choice import (
    MandatoryLocationChoicePage,
)
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
from dashboard.pages.tour_summaries.tour_mode import (
    TourModePage as TourSummariesTourModePage,
)
from dashboard.pages.tour_summaries.tour_mode import _filter_col
from dashboard.pages.tour_summaries.tour_distance import TourDistancePage
from dashboard.pages.tour_summaries.tour_purpose import TourPurposePage
from dashboard.pages.tour_summaries.tour_stop_frequency import (
    TourStopFrequencyPage,
)
from dashboard.pages.tour_summaries.tour_time import TourTimePage
from dashboard.pages.trip_summaries.trip_mode import TripModePage
from dashboard.pages.trip_summaries.trip_stop_distance import TripStopDistancePage
from dashboard.pages.trip_summaries.trip_stop_time import TripStopTimePage
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.state import DashboardState
from processor.models import RunData
from processor.prepare.cache import build_prepared_manifest_identity
from processor.prepare.enrichment.pipeline import prepare_data
from processor.summarize import cache as summary_cache_module
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.cache import (
    SummaryCacheError,
    build_run_fingerprint,
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


def _write_config(
    tmp_path: Path,
    *,
    visualizer_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
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
    if extra_lines:
        config_path.write_text(
            config_path.read_text(encoding="utf-8")
            + "\n"
            + "\n".join(extra_lines),
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
        "persons": pl.DataFrame({"person_id": [10], "household_id": [1], "finalweight": [1.0]}),
        "tours": pl.DataFrame({"tour_id": [100], "person_id": [10], "household_id": [1], "finalweight": [1.0]}),
        "trips": pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10], "finalweight": [1.0]}),
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
                "destination_distance",
                "destination_average_distance",
                "geo_flows",
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

    with pytest.raises(
        SummaryCacheError, match="prepared manifest identity mismatch"
    ):
        load_summary_run_cache(
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

    with pytest.raises(
        SummaryCacheError, match="prepared manifest identity mismatch"
    ):
        load_summary_run_cache(
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
    allowed_missing = {
        "traffic_count_comparisons",
        "screenline_flow_comparisons",
        "transit_boardings_by_operator_and_technology",
        "transit_transfer_rate",
        "commercial_vmt_totals",
        "bicycle_vmt_by_facility_type",
    }
    missing = [
        spec.summary_id
        for spec in SUMMARY_SPECS
        if not hasattr(spec.builder, "_summary_contract")
    ]
    assert set(missing) == allowed_missing


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


def test_summary_cache_writes_sentinel_csvs_for_empty_unavailable_and_failed_summaries(
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
                    "state": "empty",
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

    assert (
        cache_dir / "weighted" / "destinationDistByPurpose.csv"
    ).read_text(encoding="utf-8") == "__empty__\n"
    assert (
        cache_dir / "weighted" / "destinationAvgDistance.csv"
    ).read_text(encoding="utf-8") == "__empty__\n"

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
        loaded.summaries_by_mode["weighted"]["destination_distance"].schema
        == empty_summary_frame(legacy.distance_distribution).schema
    )
    assert (
        loaded.summaries_by_mode["weighted"]["destination_average_distance"].schema
        == empty_summary_frame(legacy.average_distance).schema
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

    assert list(page.purpose_sel.options) == ["All", "eatout", "social"]
    assert list(page.direction_sel.options) == ["Both", "Outbound", "Inbound"]
    page.purpose_sel.value = "social"
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

    assert list(page.tour_purpose_sel.options) == ["All", "eatout", "social"]
    page.tour_purpose_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects


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

    assert list(page.tour_purpose_sel.options) == ["All", "eatout", "social"]
    page.tour_purpose_sel.value = "social"
    charts = page.render_body()
    overall_chart = charts[0]
    traces = {trace.name: trace for trace in overall_chart.object.data}

    assert set(traces) == {"Base", "Build"}
    assert list(traces["Base"].x) == ["WALK", "SHARED2"]
    assert list(traces["Base"].y) == [0.0, 0.0]
    assert list(traces["Build"].x) == ["WALK", "SHARED2"]
    assert list(traces["Build"].y) == [1.0, 5.0]


def test_tour_purpose_selectors_use_category_labels_from_config(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "categories:",
            "  tour_purpose:",
            "    mapping:",
            "      all_tour_purposes: Total",
            "      eatout: Eat Out",
            "      social: Social Time",
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
    assert list(tour_time_page.purpose_sel.options) == ["Total", "Eat Out", "Social Time"]

    trip_stop_time_page = TripStopTimePage(state, config)
    trip_stop_time_page.refresh(force=True)
    assert list(trip_stop_time_page.tour_purpose_sel.options) == [
        "Total",
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

    page = TripStopTimePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == ["Total", "eatout", "social"]
    page.tour_purpose_sel.value = "social"
    page.refresh(force=True)
    assert page._body.objects


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

    page = TripStopDistancePage(state, config)
    page.refresh(force=True)

    assert list(page.tour_purpose_sel.options) == ["Total", "eatout", "social"]
    assert page.tour_purpose_sel.value == "Total"
    assert len(page._body.objects) == 2

    page.tour_purpose_sel.value = "social"
    page.refresh(force=True)

    assert len(page._body.objects) == 2


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

    assert list(page.person_type_sel.options) == ["Total", "worker"]
    page.person_type_sel.value = "worker"
    page.refresh(force=True)
    assert page._body.objects


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
        str(card.objects[0].object)
        for card in cards
        if getattr(card, "objects", None)
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
    assert list(people_plot.object.data[0].y) == [50.0, 100.0]

    state.value_mode = "Count"
    page.refresh(force=True)
    plots = _collect_plotly_panes(page._participation_section)
    people_plot = next(
        plot
        for plot in plots
        if str(plot.object.layout.title.text)
        == "People Taking Part in a Joint Tour by Household Size"
    )
    assert list(people_plot.object.data[0].y) == [2.0, 3.0]


def test_tour_purpose_labels_render_consistently_across_pages(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "categories:",
            "  tour_purpose:",
            "    mapping:",
            "      all_tour_purposes: Total",
            "      work: Work Trips",
            "      shop: Shopping",
            "      eatout: Eat Out",
            "      social: Social Time",
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
        == "Daily Tour Rate per Person by Tour Purpose - Total"
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
        plot for plot in tour_purpose_plots if plot.object.layout.title.text == "Tour Purpose"
    )
    assert list(purpose_chart.object.layout.xaxis.categoryarray) == [
        "Work Trips",
        "Shopping",
    ]
    assert list(purpose_chart.object.data[0].x) == ["Work Trips", "Shopping"]

    tour_distance_page = TourDistancePage(state, config)
    tour_distance_page.refresh(force=True)
    assert list(tour_distance_page.mand_purpose_sel.options) == ["All", "Work Trips"]
    assert list(tour_distance_page.nonmand_purpose_sel.options) == [
        "All",
        "Eat Out",
        "Social Time",
    ]
    tabulators = _collect_tabulators(tour_distance_page._average_section)
    mandatory_table = tabulators[0].value
    nonmandatory_table = tabulators[1].value
    assert mandatory_table["mandatory_tour_purpose"].tolist() == ["Work Trips"]
    assert nonmandatory_table["nonmandatory_tour_purpose"].tolist() == [
        "Eat Out",
        "Social Time",
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
                        "outbound_after_dropoff",
                        "inbound_before_pickup",
                        "inbound_after_pickup",
                    ],
                    "stop_count": [1, 0, 0, 1],
                    "tour_count": [2.0, 3.0, 4.0, 1.0],
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
                    "student_count": [1, 2],
                    "household_count": [10.0, 5.0],
                }
            ),
            "households_with_school_escorting_by_student_count_and_direction": pl.DataFrame(
                {
                    "student_count": [1, 2, 1, 2, 1, 2],
                    "direction": [
                        "outbound",
                        "outbound",
                        "inbound",
                        "inbound",
                        "both",
                        "both",
                    ],
                    "household_count": [4.0, 1.0, 3.0, 0.0, 2.0, 1.0],
                }
            ),
            "schoolkids_per_escorted_tour_by_student_count_and_direction": pl.DataFrame(
                {
                    "student_count": [1, 2, 1, 2, 1, 2],
                    "direction": [
                        "outbound",
                        "outbound",
                        "inbound",
                        "inbound",
                        "both",
                        "both",
                    ],
                    "avg_schoolkids_per_tour": [1.5, 2.0, 1.0, 2.5, 1.0, 2.0],
                    "tour_count": [4.0, 2.0, 3.0, 1.0, 2.0, 1.0],
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
    assert len(page._body.objects) == 2
    render_calls = {"static": 0, "directional": 0}
    static_section = page._registered_sections["escorted_tours_static_body"]
    directional_section = page._registered_sections["escorted_tours_directional_body"]
    original_static_render = static_section.render
    original_directional_render = directional_section.render

    def counted_static_render():
        render_calls["static"] += 1
        return original_static_render()

    def counted_directional_render():
        render_calls["directional"] += 1
        return original_directional_render()

    static_section.render = counted_static_render
    directional_section.render = counted_directional_render
    page.direction_sel.value = "Both Directions"
    page.refresh(force=False)
    assert page._body.objects
    assert render_calls == {"static": 0, "directional": 1}
    student_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page._body)
        if "Student School Escort Status" in str(plot.object.layout.title.text)
    ]
    assert sorted(student_titles) == [
        "Student School Escort Status - Both Directions",
        "Student School Escort Status - Inbound",
        "Student School Escort Status - Outbound",
    ]
    household_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page._body)
        if "Households With School Escorting" in str(plot.object.layout.title.text)
    ]
    assert sorted(household_titles) == [
        "Households With School Escorting - Both Directions",
        "Households With School Escorting - Inbound",
        "Households With School Escorting - Outbound",
    ]
    schoolkids_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page._body)
        if "Schoolkids Per Escorted Tour" in str(plot.object.layout.title.text)
    ]
    assert sorted(schoolkids_titles) == [
        "Schoolkids Per Escorted Tour - Both Directions",
        "Schoolkids Per Escorted Tour - Inbound",
        "Schoolkids Per Escorted Tour - Outbound",
    ]
    stop_titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page._body)
        if "Adult Escort Stops" in str(plot.object.layout.title.text)
    ]
    assert sorted(stop_titles) == [
        "Adult Escort Stops After Dropoff - Outbound",
        "Adult Escort Stops After Pickup - Inbound",
        "Adult Escort Stops Before Dropoff - Outbound",
        "Adult Escort Stops Before Pickup - Inbound",
    ]


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

    assert page._body.objects
    titles = [
        str(plot.object.layout.title.text)
        for plot in _collect_plotly_panes(page._body)
    ]
    assert "Chauffer Escorting Tours by Person Type - Both Directions" in titles
    assert "Chauffer Escorting Tour Distance Distribution - Both Directions" in titles
    assert "Chauffer Escorting Trip Distance Distribution - Both Directions" in titles
    assert "Adult Escort Stops Before Dropoff - Outbound" in titles
    assert "Adult Escort Trip Stop Frequency - Both Directions" not in titles
    assert all("Schoolkids Per Escorted Tour" not in title for title in titles)


def test_escorted_tours_page_uses_configured_escort_labels_for_student_status(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "categories:",
            "  escort:",
            "    mapping:",
            "      not_escorted: Unescorted",
            "      pure_escort: Driven Solo",
            "      ride_share: Shared Ride",
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
    plots = _collect_plotly_panes(page._body)

    student_plot = next(
        plot
        for plot in plots
        if str(plot.object.layout.title.text) == "Student School Escort Status - Outbound"
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

    assert list(page.geo_level_sel.options) == ["Total"]
    commuting_widget = page._commuting_flows_section.objects[0]
    assert not isinstance(commuting_widget, pn.Card)


def test_mandatory_location_choice_can_show_maz_when_enabled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        visualizer_lines=["enable_maz_geographies: true"],
    )
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

    page = TourTimePage(state, config)
    page.refresh(force=True)

    assert list(page.purpose_sel.options) == ["Total", "work"]
    page.purpose_sel.value = "work"
    page.refresh(force=True)
    assert page._body.objects


def test_vehicle_ownership_type_live_page_uses_shared_summary_helpers(
    tmp_path: Path,
) -> None:
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

    page = VehicleOwnershipTypePage(state, config)
    page.refresh(force=True)

    assert page._body.objects
