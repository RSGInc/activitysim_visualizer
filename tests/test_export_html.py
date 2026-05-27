from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dashboard_expectations import EXPECTED_DEFAULT_LEAF_PAGES, EXPECTED_DEFAULT_PAGES
from dashboard.export.html import (
    ExportBuildError,
    build_export_html_document,
    write_export_html_document,
)
from dashboard.export.types import EXPORT_CLIENT_RUNTIME, EXPORT_SCHEMA_VERSION
from processor.models import RunData
from processor.summarize.cache import create_summary_run
from runtime.config import Config


def _write_config(
    tmp_path: Path,
    *,
    dashboard_pages: list[object] | None | object = ...,
    weighting_modes: list[str] | None = None,
    modes_lines: list[str] | None = None,
    geography_lines: list[str] | None = None,
    export_html_lines: list[str] | None = None,
    visualizer_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
) -> Config:
    weighting_modes = weighting_modes or ["weighted", "unweighted"]
    tmp_path.mkdir(parents=True, exist_ok=True)
    lines = [
        'name: "Test Config"',
        "runs: []",
        "summaries:",
        "  root: summary_cache",
        "  weighting_modes:",
    ]
    lines.extend(f"    - {mode}" for mode in weighting_modes)
    lines.extend(
        [
            "visualizer:",
            '  dashboard_title: "Test Dashboard"',
        ]
    )
    if visualizer_lines:
        lines.extend(f"  {line}" for line in visualizer_lines)
    if dashboard_pages is ...:
        dashboard_pages = [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
    if dashboard_pages is not None:
        lines.append("  dashboard_pages:")
        for entry in dashboard_pages:
            if isinstance(entry, str):
                lines.append(f"    - {entry}")
                continue
            if isinstance(entry, dict) and len(entry) == 1:
                page_id, children = next(iter(entry.items()))
                lines.append(f"    - {page_id}:")
                for child_id in children:
                    lines.append(f"      - {child_id}")
                continue
            raise ValueError("dashboard_pages test helper only supports strings or single-key child mappings.")
    if export_html_lines:
        lines.append("  export_html:")
        lines.extend(f"    {line}" for line in export_html_lines)
    if modes_lines:
        lines.append("modes:")
        lines.extend(f"  {line}" for line in modes_lines)
    else:
        lines.append("modes: {}")
    if geography_lines:
        lines.append("geography:")
        lines.extend(f"  {line}" for line in geography_lines)
    if extra_lines:
        lines.extend(extra_lines)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _scale_table(df: pl.DataFrame, factor: float) -> pl.DataFrame:
    metric_columns = {
        "person_count",
        "household_count",
        "tour_count",
        "trip_count",
        "stop_count",
        "auto_vmt",
        "worker_count",
        "work_from_home_worker_count",
        "household_percent",
        "joint_tour_count",
    }
    exprs = [
        (pl.col(column) * factor).alias(column)
        for column in df.columns
        if column in metric_columns
        or column.startswith("freq")
        or column.startswith("pct")
        or column.startswith("avg")
        or column.endswith(("_count", "_distance", "_percent"))
    ]
    return df.with_columns(exprs) if exprs else df.clone()


def _full_summary_run():
    weighted = {
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
        "auto_ownership_distribution": pl.DataFrame(
            {
                "household_vehicle_count": [0, 1],
                "household_count": [12.0, 18.0],
            }
        ),
        "work_location_distance_distribution_by_geography": pl.DataFrame(
            {
                "distance_bin": [1, 2, 1, 2, 1, 2],
                "geography": [
                    "all_geographies",
                    "all_geographies",
                    "Urban",
                    "Urban",
                    "Suburban",
                    "Suburban",
                ],
                "person_count": [6.0, 4.0, 4.0, 2.5, 2.0, 1.5],
            }
        ),
        "university_location_distance_distribution_by_geography": pl.DataFrame(
            {
                "distance_bin": [1, 2, 1, 2, 1, 2],
                "geography": [
                    "all_geographies",
                    "all_geographies",
                    "Urban",
                    "Urban",
                    "Suburban",
                    "Suburban",
                ],
                "person_count": [3.0, 2.0, 1.5, 1.0, 1.5, 1.0],
            }
        ),
        "school_location_distance_distribution_by_geography": pl.DataFrame(
            {
                "distance_bin": [1, 2, 1, 2, 1, 2],
                "geography": [
                    "all_geographies",
                    "all_geographies",
                    "Urban",
                    "Urban",
                    "Suburban",
                    "Suburban",
                ],
                "person_count": [5.0, 1.0, 3.0, 0.5, 2.0, 0.5],
            }
        ),
        "geo_flows": pl.DataFrame(
            {
                "Home Geography": ["Urban", "Suburban"],
                "Work Geography": ["Urban", "Suburban"],
                "Workers": [7.0, 4.0],
            }
        ),
        "internal_external_worker_by_geography": pl.DataFrame(
            {
                "geography_level": ["Urban", "Suburban"],
                "geography": ["Internal", "External"],
                "person_count": [12.0, 8.0],
            }
        ),
        "external_worker_workplace_locations": pl.DataFrame(
            {
                "geography_level": ["Urban", "Suburban"],
                "geography": ["Downtown", "Campus"],
                "external_worker_count": [5.0, 3.0],
            }
        ),
        "commuting_flows": pl.DataFrame(
            {
                "origin_geography_level": ["Urban", "Suburban"],
                "destination_geography_level": ["Urban", "Suburban"],
                "Home Geography": ["Urban", "Suburban"],
                "Work Geography": ["Urban", "Suburban"],
                "Workers": [7.0, 4.0],
            }
        ),
        "work_from_home_rate_by_geography": pl.DataFrame(
            {
                "geography_level": ["All", "Urban", "Suburban"],
                "geography_type": ["All", "Urban", "Suburban"],
                "geography": ["all_geographies", "Urban", "Suburban"],
                "geography_id": ["all_geographies", "Urban", "Suburban"],
                "worker_count": [20.0, 12.0, 8.0],
                "work_from_home_worker_count": [11.0, 7.0, 4.0],
            }
        ),
        "telecommute_frequency_distribution": pl.DataFrame(
            {
                "telecommute_frequency": ["never", "often"],
                "person_count": [7.0, 5.0],
            }
        ),
        "workplace_shadow_pricing_residuals": pl.DataFrame(
            {
                "geography_type": ["all_geographies", "district", "district"],
                "geography_id": ["all_geographies", "Urban", "Suburban"],
                "target_count": [20.0, 12.0, 8.0],
                "modeled_count": [18.0, 11.0, 7.0],
                "residual_count": [-2.0, -1.0, -1.0],
                "absolute_residual_count": [2.0, 1.0, 1.0],
                "percent_error": [-10.0, -8.3333, -12.5],
            }
        ),
        "workplace_shadow_pricing_residual_histogram": pl.DataFrame(
            {
                "geography_type": ["all_geographies", "district"],
                "bin_start": [-5.0, -3.0],
                "bin_end": [0.0, 0.0],
                "geography_count": [2.0, 2.0],
            }
        ),
        "school_shadow_pricing_residuals": pl.DataFrame(
            {
                "geography_type": ["all_geographies", "district", "district"],
                "geography_id": ["all_geographies", "Urban", "Suburban"],
                "student_type": ["University", "University", "School"],
                "target_count": [12.0, 6.0, 4.0],
                "modeled_count": [11.0, 5.0, 3.0],
                "residual_count": [-1.0, -1.0, -1.0],
                "absolute_residual_count": [1.0, 1.0, 1.0],
                "percent_error": [-8.3333, -16.6667, -25.0],
            }
        ),
        "school_shadow_pricing_residual_histogram": pl.DataFrame(
            {
                "geography_type": ["all_geographies", "district", "district"],
                "student_type": ["University", "University", "School"],
                "bin_start": [-2.0, -2.0, -2.0],
                "bin_end": [0.0, 0.0, 0.0],
                "geography_count": [1.0, 1.0, 1.0],
            }
        ),
        "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
            {
                "mandatory_tour_purpose": ["work", "work", "work"],
                "geography": ["all_geographies", "Urban", "Suburban"],
                "average_tour_distance": [8.5, 7.5, 9.5],
            }
        ),
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
        "jtf_distribution": pl.DataFrame(
            {
                "jtf_code": [1, 2, 3],
                "jtf_label": ["No Joint Tours", "1 Shopping", "1 Maintenance"],
                "household_count": [12.0, 5.0, 3.0],
            }
        ),
        "joint_tour_composition_distribution": pl.DataFrame(
            {
                "tour_composition": ["adults", "mixed", "children"],
                "joint_tour_count": [4.0, 3.0, 1.0],
            }
        ),
        "joint_tour_party_size_distribution": pl.DataFrame(
            {"party_size": [2, 3], "joint_tour_count": [5.0, 3.0]}
        ),
        "household_jtp_by_household_size_and_jtf": pl.DataFrame(
            {
                "household_size": ["2", "2", "3", "3"],
                "jtf": ["0", "1", "0", "2+"],
                "household_percent": [40.0, 60.0, 37.5, 62.5],
            }
        ),
        "destination_distance": pl.DataFrame(
            {
                "purpose": ["All NM", "All NM", "eatout", "eatout", "social", "social"],
                "distbin": [0, 1, 0, 1, 0, 1],
                "freq": [5.0, 7.5, 2.0, 4.0, 3.0, 2.0],
            }
        ),
        "destination_average_distance": pl.DataFrame(
            {
                "purpose": ["eatout", "social"],
                "avg_distance": [3.25, 4.5],
            }
        ),
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
        "grouped_tour_mode_profile": pl.DataFrame(
            {
                "mode_group": ["Auto", "Active", "Auto", "Active"],
                "purpose": ["Total", "Total", "work", "work"],
                "freq_all": [10.0, 5.0, 7.0, 3.0],
                "freq_as0": [2.0, 4.0, 1.0, 2.0],
                "freq_as1": [3.0, 1.0, 2.0, 1.0],
                "freq_as2": [5.0, 0.0, 4.0, 0.0],
            }
        ),
        "tour_stop_frequency_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                ],
                "outbound_stop_count": [0, 1, 0, 1, 0],
                "inbound_stop_count": [0, 1, 0, 0, 1],
                "total_stop_count": [0, 2, 0, 1, 1],
                "tour_count": [18.0, 5.0, 10.0, 5.0, 8.0],
            }
        ),
        "stop_destination_purpose_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                ],
                "stop_destination_purpose": ["shop", "eat", "shop", "eat", "visit"],
                "stop_count": [4.0, 14.0, 4.0, 6.0, 8.0],
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
        "trip_departure_time_by_purpose": pl.DataFrame(
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
                "departure_stop_count": [8.0, 10.0, 3.0, 4.0, 5.0, 6.0],
                "departure_trip_count": [6.0, 8.0, 2.0, 3.0, 4.0, 5.0],
            }
        ),
        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                    "social",
                    "all_tour_purposes",
                    "eatout",
                    "social",
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
                    "DRIVEALONE",
                    "WALK",
                    "SHARED",
                    "WALK",
                    "WALK",
                    "DRIVEALONE",
                    "SHARED",
                ],
                "trip_count": [15.0, 5.0, 10.0, 2.0, 5.0, 3.0, 5.0, 10.0, 5.0],
            }
        ),
    }
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": unweighted,
        },
        source_run_dir=str(Path("C:/runs/base")),
    )


def _full_summary_run_with_vehicle_allocations():
    base_run = _full_summary_run()
    weighted = dict(base_run.summaries_by_mode["weighted"])
    weighted["allocated_vehicle_age_by_occupancy"] = pl.DataFrame(
        {
            "occupancy": ["All", "All", "Low", "Low", "High", "High"],
            "age": ["0", "20+", "0", "20+", "0", "20+"],
            "vehicle_count": [10.0, 20.0, 3.0, 7.0, 7.0, 13.0],
        }
    )
    weighted["allocated_vehicle_fuel_type_by_occupancy"] = pl.DataFrame(
        {
            "occupancy": ["All", "All", "Low", "Low", "High", "High"],
            "fuel_type": ["Gas", "EV", "Gas", "EV", "Gas", "EV"],
            "vehicle_count": [21.0, 9.0, 8.0, 2.0, 13.0, 7.0],
        }
    )
    weighted["allocated_vehicle_body_type_by_occupancy"] = pl.DataFrame(
        {
            "occupancy": ["All", "All", "Low", "Low", "High", "High"],
            "body_type": ["Sedan", "SUV", "Sedan", "SUV", "Sedan", "SUV"],
            "vehicle_count": [11.0, 19.0, 2.0, 8.0, 9.0, 11.0],
        }
    )
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": unweighted,
        },
        source_run_dir=base_run.source_run_dir,
    )


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


def _skim_summary_run():
    weighted = {
        "skimjoin_trip_component_stats": pl.DataFrame(
            {
                "component": ["TIME", "TIME", "DIST"],
                "trip_mode": ["DRIVE", "WALK", "DRIVE"],
                "n_valid": [10.0, 8.0, 12.0],
                "mean": [15.0, 20.0, 7.0],
                "std": [1.5, 2.0, 0.7],
                "min": [10.0, 15.0, 5.0],
                "max": [20.0, 30.0, 9.0],
                "median": [15.0, 20.0, 7.0],
                "mode": [14.0, 19.0, 7.0],
                "zero_share": [0.0, 0.0, 0.0],
                "missing_share": [0.0, 0.0, 0.0],
            }
        ),
        "skimjoin_tour_component_stats": pl.DataFrame(
            {
                "component": ["TIME", "TIME", "DIST"],
                "tour_mode": ["DRIVE", "WALK", "DRIVE"],
                "n_valid": [6.0, 5.0, 7.0],
                "mean": [25.0, 18.0, 11.0],
                "std": [2.5, 1.8, 1.1],
                "min": [21.0, 14.0, 9.0],
                "max": [30.0, 22.0, 13.0],
                "median": [25.0, 18.0, 11.0],
                "mode": [24.0, 18.0, 11.0],
                "zero_share": [0.0, 0.0, 0.0],
                "missing_share": [0.0, 0.0, 0.0],
            }
        ),
    }
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": unweighted,
        },
        source_run_dir="C:/runs/base",
    )


def _segmented_summary_runs():
    full_run = _full_summary_run()
    return [
        full_run,
        create_summary_run(
            label="Base",
            run_key="base",
            summaries_by_mode=full_run.summaries_by_mode,
            summary_metadata_by_mode=full_run.summary_metadata_by_mode,
            segmentation_type="signup_platform",
            segment_id="browser",
            segment_label="Browser",
            is_full_segment=False,
            source_run_dir=full_run.source_run_dir,
            manifest=full_run.manifest,
        ),
        create_summary_run(
            label="Base",
            run_key="base",
            summaries_by_mode=full_run.summaries_by_mode,
            summary_metadata_by_mode=full_run.summary_metadata_by_mode,
            segmentation_type="signup_platform",
            segment_id="call",
            segment_label="Call",
            is_full_segment=False,
            source_run_dir=full_run.source_run_dir,
            manifest=full_run.manifest,
        ),
        create_summary_run(
            label="Base",
            run_key="base",
            summaries_by_mode=full_run.summaries_by_mode,
            summary_metadata_by_mode=full_run.summary_metadata_by_mode,
            segmentation_type="person_sex",
            segment_id="male",
            segment_label="Male",
            is_full_segment=False,
            source_run_dir=full_run.source_run_dir,
            manifest=full_run.manifest,
        ),
    ]


def test_export_html_config_defaults_to_all_dashboard_states_and_selector_values(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    assert config.export_html.enabled is False
    assert config.export_html.weighting == ["weighted", "unweighted"]
    assert config.export_html.values == ["percent", "count"]
    assert _configured_page_ids(config) == [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
    assert config.export_html.dashboard.weighting == ["weighted", "unweighted"]
    assert config.export_html.dashboard.values == ["percent", "count"]
    assert config.export_html.pages == {}
    assert config.export_html.selector_request("tour_mode", "tour_purpose").mode == "all"
    assert config.export_html.panel_weighting_values() == ["Weighted", "Unweighted"]
    assert config.export_html.panel_value_values() == ["Percent", "Count"]
    assert config.export_html.dashboard.segmentation_type is None
    assert config.export_html.dashboard.segmentation_visibility is None


def test_export_html_config_segmentation_defaults_to_live_dashboard_settings(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: signup_platform",
            "    visibility: segments_only",
            "  definitions:",
            "    signup_platform:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: signup_platform",
            "      segments:",
            "        - id: browser",
            "          label: Browser",
            "          values: [browser]",
            "    person_sex:",
            "      source:",
            "        type: prepared_column",
            "        source_table: per",
            "        column: sex",
            "      segments:",
            "        - id: male",
            "          label: Male",
            "          values: [1]",
        ],
        export_html_lines=[
            "enabled: true",
        ],
    )

    assert config.export_html.dashboard.segmentation_type == "signup_platform"
    assert config.export_html.dashboard.segmentation_visibility == "segments_only"


def test_export_html_config_supports_segmentation_overrides(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "segmentation:",
            "  enabled: true",
            "  dashboard:",
            "    segmentation_type: signup_platform",
            "    visibility: segments_only",
            "  definitions:",
            "    signup_platform:",
            "      source:",
            "        type: prepared_column",
            "        source_table: hh",
            "        column: signup_platform",
            "      segments:",
            "        - id: browser",
            "          label: Browser",
            "          values: [browser]",
            "    person_sex:",
            "      source:",
            "        type: prepared_column",
            "        source_table: per",
            "        column: sex",
            "      segments:",
            "        - id: male",
            "          label: Male",
            "          values: [1]",
        ],
        export_html_lines=[
            "dashboard:",
            "  segmentation_type: person_sex",
            "  segmentation_visibility: full_only",
        ],
    )

    assert config.export_html.dashboard.segmentation_type == "person_sex"
    assert config.export_html.dashboard.segmentation_visibility == "full_only"


def test_export_html_config_supports_new_summaries_and_visualizer_sections(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview", "trip_mode"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "pages:",
            "  trip_mode:",
            "    tour_mode: all",
            "  overview: {}",
        ],
    )

    assert config.summary_root.endswith("summary_cache")
    assert _configured_page_ids(config) == ["overview", "trip_mode"]
    assert config.export_html.enabled is True
    assert list(config.export_html.pages) == ["trip_mode"]
    assert config.export_html.pages_configured is True


def test_export_html_enabled_without_pages_uses_all_dashboard_states_and_all_selectors(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview", "trip_mode"],
        export_html_lines=[
            "enabled: true",
        ],
    )

    assert config.export_html.enabled is True
    assert config.export_html.pages_configured is False
    assert config.export_html.weighting == ["weighted", "unweighted"]
    assert config.export_html.values == ["percent", "count"]
    assert config.export_html.selector_request("trip_mode", "tour_mode").mode == "all"


def test_export_html_config_resolves_nested_dashboard_and_page_requests(
    tmp_path: Path,
) -> None:
    config_all = _write_config(
        tmp_path / "all",
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  daily_travel:",
            "    daily_activity_pattern:",
            "      person_type: all",
            "  trip_mode:",
            "    tour_purpose:",
            "      - all",
            "      - eatout",
        ],
    )
    config_list = _write_config(
        tmp_path / "list",
        export_html_lines=[
            "dashboard:",
            "  weighting:",
            "    - Unweighted",
            "    - weighted",
            "    - UNWEIGHTED",
            "  values:",
            "    - COUNT",
            "    - percent",
            "    - count",
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose:",
            "      - all",
            "      - eatout",
        ],
    )

    assert config_all.export_html.weighting == ["weighted", "unweighted"]
    assert config_all.export_html.values == ["percent", "count"]
    assert (
        config_all.export_html.selector_request(
            "daily_activity_pattern",
            "person_type",
            group_id="daily_travel",
        ).mode
        == "all"
    )
    assert (
        config_all.export_html.selector_request("trip_mode", "tour_purpose").mode
        == "explicit"
    )
    assert config_all.export_html.selector_request("trip_mode", "tour_purpose").values == (
        "all",
        "eatout",
    )
    assert config_list.export_html.weighting == ["unweighted", "weighted"]
    assert config_list.export_html.values == ["count", "percent"]
    assert (
        config_list.export_html.selector_request(
            "trip_mode",
            "tour_purpose",
            group_id="trip_summaries",
        ).mode
        == "explicit"
    )
    assert config_list.export_html.selector_request(
        "trip_mode",
        "tour_purpose",
        group_id="trip_summaries",
    ).values == (
        "all",
        "eatout",
    )


def test_export_html_config_supports_nested_group_children_requests(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  tour_summaries:",
            "    children:",
            "      tour_purpose: {}",
            "      tour_mode:",
                "        tour_purpose:",
                "          - total",
                "          - work",
        ],
    )

    assert (
        config.export_html.selector_request(
            "tour_mode",
            "tour_purpose",
            group_id="tour_summaries",
        ).values
        == ("total", "work")
    )


def test_config_allows_missing_dashboard_pages(tmp_path: Path) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)

    assert config.dashboard_pages is None


def test_config_defaults_when_summaries_and_visualizer_sections_are_absent(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Legacy Layout"',
                'dashboard_title: "Ignored Legacy Title"',
                "run_colors:",
                '  - "#111111"',
                "outputs:",
                "  summary_root: ignored_summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "  export_html:",
                "    dashboard:",
                "      weighting: all",
                "dashboard_pages:",
                "  - raw_trip_demo",
                "runs: []",
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.summary_root == str(
        (tmp_path / "artifacts" / "summary_cache").resolve()
    )
    assert config.weighting_modes == ["weighted", "unweighted"]
    assert config.dashboard_title == "Ignored Legacy Title"
    assert config.dashboard_pages is None
    assert config.run_colors == [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
    ]
    assert config.export_html.dashboard.weighting == ["weighted", "unweighted"]
    assert config.export_html.dashboard.values == ["percent", "count"]
    assert config.export_html.pages == {}


def test_config_prefers_visualizer_dashboard_title_over_legacy_top_level_title(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Dashboard Title Precedence"',
                'dashboard_title: "Legacy Dashboard Title"',
                "runs: []",
                "visualizer:",
                '  dashboard_title: "Visualizer Dashboard Title"',
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.dashboard_title == "Visualizer Dashboard Title"


def test_config_ignores_flat_export_html_dashboard_aliases(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Flat Export Legacy"',
                "runs: []",
                "visualizer:",
                "  export_html:",
                "    weighting: all",
                "    values: all",
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.export_html.dashboard.weighting == ["weighted", "unweighted"]
    assert config.export_html.dashboard.values == ["percent", "count"]


def test_export_html_config_rejects_invalid_or_empty_values(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="Unsupported visualizer.export_html.dashboard.weighting"
    ):
        _write_config(
            tmp_path / "invalid",
            export_html_lines=[
                "dashboard:",
                "  weighting:",
                "    - weighted",
                "    - bogus",
            ],
        )

    with pytest.raises(
        ValueError,
        match="visualizer.export_html.dashboard.segmentation_type must name one configured segmentation definition",
    ):
        _write_config(
            tmp_path / "invalid_export_segmentation_type",
            extra_lines=[
                "segmentation:",
                "  enabled: true",
                "  definitions:",
                "    signup_platform:",
                "      source:",
                "        type: prepared_column",
                "        source_table: hh",
                "        column: signup_platform",
                "      segments:",
                "        - id: browser",
                "          label: Browser",
                "          values: [browser]",
            ],
            export_html_lines=[
                "dashboard:",
                "  segmentation_type: person_sex",
            ],
        )

    with pytest.raises(
        ValueError,
        match="visualizer.export_html.dashboard.segmentation_visibility must be one of full_only, segments_only, or full_and_segments",
    ):
        _write_config(
            tmp_path / "invalid_export_segmentation_visibility",
            extra_lines=[
                "segmentation:",
                "  enabled: true",
                "  definitions:",
                "    signup_platform:",
                "      source:",
                "        type: prepared_column",
                "        source_table: hh",
                "        column: signup_platform",
                "      segments:",
                "        - id: browser",
                "          label: Browser",
                "          values: [browser]",
            ],
            export_html_lines=[
                "dashboard:",
                "  segmentation_visibility: invalid",
            ],
        )


def test_config_rejects_duplicate_dashboard_pages(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="visualizer.dashboard_pages contains duplicate page id",
    ):
        _write_config(
            tmp_path,
            dashboard_pages=["overview", "overview"],
        )

    with pytest.raises(
        ValueError,
        match="visualizer.export_html.dashboard.values resolved to no values",
    ):
        _write_config(
            tmp_path / "empty",
            export_html_lines=[
                "dashboard:",
                "  values: []",
            ],
        )

    with pytest.raises(
        ValueError,
        match="visualizer\\.export_html\\.pages\\.trip_summaries(\\.children)?\\.trip_mode\\.tour_purpose resolved to no values",
    ):
        _write_config(
            tmp_path / "empty_page_values",
            export_html_lines=[
                "pages:",
                "  trip_summaries:",
                "    trip_mode:",
                "      tour_purpose: []",
            ],
        )


def test_export_html_config_ignores_segmentation_overrides_when_segmentation_is_disabled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  segmentation_type: signup_platform",
            "  segmentation_visibility: segments_only",
        ],
    )

    assert config.export_html.dashboard.segmentation_type is None
    assert config.export_html.dashboard.segmentation_visibility is None


def _extract_payload(html: str) -> dict:
    start_token = '<script id="activitysim-export-data" type="application/json">'
    start = html.index(start_token) + len(start_token)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def _configured_page_ids(config: Config) -> list[str] | None:
    if config.dashboard_pages is None:
        return None
    return [entry.page_id for entry in config.dashboard_pages]


def _flatten_page_descriptors(pages: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for page in pages:
        by_id[page["id"]] = page
        by_id.update(_flatten_page_descriptors(page.get("children", [])))
    return by_id


def _walk_nodes(node: dict) -> list[dict]:
    if node.get("kind") == "page":
        return _walk_nodes(node["content"])
    if node.get("kind") == "region":
        nodes: list[dict] = [node]
        nodes.extend(_walk_nodes(node.get("default_content", {})))
        for variant in node.get("variants", {}).values():
            nodes.extend(_walk_nodes(variant))
        return nodes
    nodes = [node]
    for child in node.get("children", []):
        nodes.extend(_walk_nodes(child))
    for tab in node.get("tabs", []):
        nodes.extend(_walk_nodes(tab["content"]))
    return nodes


def _region_nodes(node: dict) -> dict[str, dict]:
    return {
        region["region_id"]: region
        for region in _walk_nodes(node)
        if region.get("kind") == "region"
    }


def _plot_node_by_title(node: dict, title: str) -> dict:
    return next(
        plot
        for plot in _walk_nodes(node)
        if plot.get("kind") == "plotly"
        and plot.get("figure", {}).get("layout", {}).get("title", {}).get("text") == title
    )


def test_build_export_html_document_serializes_dashboard_states_and_pages(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    html = build_export_html_document(
        [],
        config,
        summary_runs=[_full_summary_run()],
    )
    payload = _extract_payload(html)

    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert payload["runs_loaded"] == [{"label": "Base", "color": "#1f77b4"}]
    assert payload["chrome"] == {
        "layout": "left_rail",
        "rail_sections": ["runs_loaded", "display_options"],
        "controls_enabled": {"weighting": True, "values": True},
    }
    assert payload["dashboard_controls"]["weighting"] == ["Weighted", "Unweighted"]
    assert payload["dashboard_controls"]["values"] == ["Percent", "Count"]
    assert payload["default_state"] == {"weighting": "Weighted", "values": "Percent"}
    assert [
        (page["id"], page["title"]) for page in payload["pages"]
    ] == EXPECTED_DEFAULT_PAGES
    assert (
        payload["page_export_support"]["client_side_runtime"]
        == "dashboard-and-page-selectors"
    )
    assert payload["client_runtime"] == EXPORT_CLIENT_RUNTIME
    enabled_selectors = payload["page_export_support"]["enabled_page_selectors"]
    assert {"page_id": "daily_activity_pattern", "selector_id": "person_type"} in enabled_selectors
    assert {"page_id": "joint_travel", "selector_id": "household_size"} in enabled_selectors
    assert {"page_id": "tour_stop_frequency", "selector_id": "tour_purpose"} in enabled_selectors
    assert {"page_id": "trip_mode", "selector_id": "tour_purpose"} in enabled_selectors
    assert sorted(payload["states"]) == [
        "Unweighted||Count",
        "Unweighted||Percent",
        "Weighted||Count",
        "Weighted||Percent",
    ]
    assert "export-layout" in html
    assert "export-rail" in html
    assert "Unsupported export schema version." in html
    assert "Offline export failed to load" in html
    assert "This HTML export encountered a runtime rendering error." in html
    assert "Plotly.react" in html
    assert ">undefined<" not in html

    page_defs = _flatten_page_descriptors(payload["pages"])
    assert page_defs["overview"]["selectors"] == []
    assert page_defs["daily_activity_pattern"]["selectors"][0]["id"] == "person_type"
    assert page_defs["daily_activity_pattern"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["daily_activity_pattern"]["selectors"][0]["resolved_values"] == [
        "Total",
        "worker",
    ]
    assert page_defs["daily_activity_pattern"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_time"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["tour_time"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_time"]["selectors"][0]["resolved_values"] == [
        "Total",
        "work",
    ]
    assert page_defs["tour_time"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_mode"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["tour_mode"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_mode"]["selectors"][0]["resolved_values"] == [
        "Total",
        "work",
    ]
    assert page_defs["tour_mode"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_stop_frequency"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["tour_stop_frequency"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_stop_frequency"]["selectors"][0]["resolved_values"] == [
        "All",
        "eatout",
        "social",
    ]
    assert page_defs["tour_stop_frequency"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_stop_time"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["trip_stop_time"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["trip_stop_time"]["selectors"][0]["resolved_values"] == [
        "Total",
        "eatout",
        "social",
    ]
    assert page_defs["trip_stop_time"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_mode"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["trip_mode"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["trip_mode"]["selectors"][0]["resolved_values"] == [
        "All",
        "eatout",
        "social",
    ]
    assert page_defs["trip_mode"]["selectors"][0]["export_enabled"] is True
    weighted_percent = payload["states"]["Weighted||Percent"]
    overview = weighted_percent["overview"]
    assert overview["kind"] == "page"
    daily_activity_pattern = weighted_percent["daily_activity_pattern"]
    assert daily_activity_pattern["kind"] == "page"
    assert _region_nodes(daily_activity_pattern)["activity_pattern_body"]["selector_ids"] == ["person_type"]
    assert sorted(_region_nodes(daily_activity_pattern)["activity_pattern_body"]["variants"]) == [
        '["Total"]',
        '["worker"]',
    ]
    tour_time = weighted_percent["tour_time"]
    assert tour_time["kind"] == "page"
    assert _region_nodes(tour_time)["tour_time_body"]["selector_ids"] == ["tour_purpose"]
    assert sorted(_region_nodes(tour_time)["tour_time_body"]["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    tour_mode = weighted_percent["tour_mode"]
    assert tour_mode["kind"] == "page"
    assert _region_nodes(tour_mode)["tour_mode_modes"]["selector_ids"] == [
        "tour_purpose",
    ]
    assert sorted(_region_nodes(tour_mode)["tour_mode_modes"]["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    tour_stop_frequency = weighted_percent["tour_stop_frequency"]
    assert tour_stop_frequency["kind"] == "page"
    assert _region_nodes(tour_stop_frequency)["tour_stop_frequency_body"]["selector_ids"] == [
        "tour_purpose",
    ]
    assert sorted(_region_nodes(tour_stop_frequency)["tour_stop_frequency_body"]["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]
    trip_stop_time = weighted_percent["trip_stop_time"]
    assert trip_stop_time["kind"] == "page"
    assert _region_nodes(trip_stop_time)["trip_stop_time_body"]["selector_ids"] == [
        "tour_purpose"
    ]
    assert sorted(_region_nodes(trip_stop_time)["trip_stop_time_body"]["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    trip_mode = weighted_percent["trip_mode"]
    assert trip_mode["kind"] == "page"
    assert _region_nodes(trip_mode)["trip_summary_mode_body"]["selector_ids"] == ["tour_purpose"]
    assert sorted(_region_nodes(trip_mode)["trip_summary_mode_body"]["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]
    widget_nodes = [
        node for node in _walk_nodes(daily_activity_pattern) if node.get("kind") == "widget"
    ]
    assert widget_nodes
    assert any(
        node.get("selector_id") == "person_type"
        and node.get("export_enabled")
        and not node.get("disabled")
        for node in widget_nodes
    )


def test_build_export_html_document_respects_configured_dashboard_page_subset_and_order(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview", "trip_summaries"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose: all",
            "  overview: {}",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)

    assert [(page["id"], page["title"]) for page in payload["pages"]] == [
        ("overview", "Overview"),
        ("trip_summaries", "Trip Summaries"),
    ]
    assert payload["pages"][1]["default_page_id"] == "trip_stop_purpose"
    assert [(child["id"], child["title"]) for child in payload["pages"][1]["children"]] == [
        ("trip_stop_purpose", "Trip and Stop Purpose"),
        ("trip_mode", "Trip Mode"),
        ("trip_stop_time", "Trip and Stop Time"),
        ("trip_stop_distance", "Trip and Stop Distance"),
    ]
    assert list(payload["states"]["Weighted||Percent"]) == [
        "overview",
        "trip_stop_purpose",
        "trip_mode",
        "trip_stop_time",
        "trip_stop_distance",
    ]


def test_build_export_html_document_inherits_live_page_order_when_export_pages_are_unset(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["trip_summaries", "overview"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)

    assert [
        (page["id"], page["title"]) for page in payload["pages"]
    ] == [
        ("trip_summaries", "Trip Summaries"),
        ("overview", "Overview"),
    ]


def test_build_export_html_document_omits_prepared_only_trip_demo_page_when_runs_are_loaded(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["raw_trip_demo"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )

    html = build_export_html_document([("Base", _raw_trip_run())], config)
    payload = _extract_payload(html)
    assert payload["pages"] == []
    assert payload["states"]["Weighted||Percent"] == {}


def test_build_export_html_document_omits_prepared_only_trip_demo_page_without_runs(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["raw_trip_demo"],
        export_html_lines=[
            "dashboard:",
            "  weighting: weighted",
            "  values: percent",
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )
    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    assert payload["pages"] == []
    assert payload["states"]["Weighted||Percent"] == {}


def test_build_export_html_document_keeps_summary_safe_skims_content_and_hides_prepared_only_controls(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["skims"],
        export_html_lines=[
            "pages:",
            "  skims: {}",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_skim_summary_run()])
    payload = _extract_payload(html)
    weighted_state = payload["states"]["Weighted||Percent"]
    nodes = _walk_nodes(weighted_state["tour_skims"]) + _walk_nodes(
        weighted_state["trip_skims"]
    )

    assert [(page["id"], page["title"]) for page in payload["pages"]] == [
        ("skims", "Skim Summaries")
    ]
    assert not any(
        node.get("selector_id") in {"trip_min", "trip_max", "tour_min", "tour_max"}
        for node in nodes
    )
    assert not any(node.get("widget_type") == "float_input" for node in nodes)
    assert not any(
        "Live Tour Distributions" in node.get("html", "")
        or "Live Trip Distributions" in node.get("html", "")
        for node in nodes
        if node.get("kind") == "html"
    )


def test_build_export_html_document_validates_page_selector_requests_against_registry(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  daily_travel:",
            "    children:",
            "      daily_activity_pattern:",
                "        person_type:",
                "          - total",
                "          - worker",
            "  tour_summaries:",
            "    children:",
            "      tour_time:",
                "        tour_purpose: all",
            "      tour_stop_frequency:",
                "        tour_purpose: all",
            "      tour_mode:",
                "        tour_purpose: all",
            "  trip_summaries:",
            "    children:",
                "      trip_mode:",
                "        tour_purpose: all",
            "      trip_stop_time:",
                "        tour_purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    page_defs = _flatten_page_descriptors(payload["pages"])

    assert page_defs["daily_activity_pattern"]["selectors"][0]["request_mode"] == "explicit"
    assert page_defs["daily_activity_pattern"]["selectors"][0]["resolved_values"] == [
        "Total",
        "worker",
    ]
    assert page_defs["daily_activity_pattern"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_stop_frequency"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_stop_frequency"]["selectors"][0]["resolved_values"] == [
        "All",
        "eatout",
        "social",
    ]
    assert page_defs["tour_stop_frequency"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_stop_time"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["trip_stop_time"]["selectors"][0]["resolved_values"] == [
        "Total",
        "eatout",
        "social",
    ]
    assert page_defs["trip_stop_time"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_time"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_time"]["selectors"][0]["resolved_values"] == [
        "Total",
        "work",
    ]
    assert page_defs["tour_time"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_mode"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_mode"]["selectors"][0]["resolved_values"] == [
        "Total",
        "work",
    ]
    assert page_defs["tour_mode"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_mode"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["trip_mode"]["selectors"][0]["resolved_values"] == [
        "All",
        "eatout",
        "social",
    ]
    assert page_defs["trip_mode"]["selectors"][0]["export_enabled"] is True

    weighted_percent = payload["states"]["Weighted||Percent"]["daily_activity_pattern"]
    assert weighted_percent["kind"] == "page"
    assert sorted(_region_nodes(weighted_percent)["activity_pattern_body"]["variants"]) == [
        '["Total"]',
        '["worker"]',
    ]
    daily_activity_pattern_weighted_percent = payload["states"]["Weighted||Percent"][
        "daily_activity_pattern"
    ]
    assert daily_activity_pattern_weighted_percent["kind"] == "page"
    assert sorted(
        _region_nodes(daily_activity_pattern_weighted_percent)["activity_pattern_body"]["variants"]
    ) == [
        '["Total"]',
        '["worker"]',
    ]
    tour_stop_frequency_weighted_percent = payload["states"]["Weighted||Percent"][
        "tour_stop_frequency"
    ]
    assert tour_stop_frequency_weighted_percent["kind"] == "page"
    assert sorted(_region_nodes(tour_stop_frequency_weighted_percent)["tour_stop_frequency_body"]["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]
    trip_stop_time_weighted_percent = payload["states"]["Weighted||Percent"]["trip_stop_time"]
    assert trip_stop_time_weighted_percent["kind"] == "page"
    assert sorted(_region_nodes(trip_stop_time_weighted_percent)["trip_stop_time_body"]["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    tour_time_weighted_percent = payload["states"]["Weighted||Percent"]["tour_time"]
    assert tour_time_weighted_percent["kind"] == "page"
    assert sorted(_region_nodes(tour_time_weighted_percent)["tour_time_body"]["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    tour_mode_weighted_percent = payload["states"]["Weighted||Percent"]["tour_mode"]
    assert tour_mode_weighted_percent["kind"] == "page"
    assert _region_nodes(tour_mode_weighted_percent)["tour_mode_modes"]["selector_ids"] == [
        "tour_purpose",
    ]
    assert sorted(_region_nodes(tour_mode_weighted_percent)["tour_mode_modes"]["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    trip_mode_weighted_percent = payload["states"]["Weighted||Percent"]["trip_mode"]
    assert trip_mode_weighted_percent["kind"] == "page"
    assert sorted(_region_nodes(trip_mode_weighted_percent)["trip_summary_mode_body"]["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]


def test_build_export_html_document_keeps_grouped_tour_mode_chart_when_mode_groups_enabled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        modes_lines=[
            "groups:",
            "  Auto:",
            "    - DRIVE",
            "  Active:",
            "    - WALK",
        ],
        export_html_lines=[
            "pages:",
            "  tour_summaries:",
            "    tour_mode:",
            "      tour_purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    tour_mode = payload["states"]["Weighted||Percent"]["tour_mode"]

    assert tour_mode["kind"] == "page"
    assert _region_nodes(tour_mode)["tour_mode_modes"]["selector_ids"] == [
        "tour_purpose",
    ]
    assert sorted(_region_nodes(tour_mode)["tour_mode_modes"]["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    region_nodes = _region_nodes(tour_mode)
    variant_nodes = _walk_nodes(
        region_nodes["tour_mode_modes"]["variants"]['["Total"]']
    )
    assert any(
        node.get("kind") == "plotly"
        and node.get("figure", {}).get("layout", {}).get("title", {}).get("text")
        == "Tour Mode - Zero Auto"
        for node in variant_nodes
    )
    vehicle_nodes = _walk_nodes(region_nodes["tour_mode_vehicles"]["default_content"])
    assert sum(1 for node in vehicle_nodes if node.get("kind") == "plotly") == 0
    assert any(
        node.get("kind") == "widget"
        and node.get("selector_id") == "vehicle_occupancy"
        and not node.get("export_enabled")
        for node in vehicle_nodes
    )


def test_build_export_html_document_serializes_vehicle_occupancy_variants_for_tour_mode(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["tour_summaries"],
        export_html_lines=[
            "pages:",
            "  tour_mode:",
            "    vehicle_occupancy: all",
        ],
    )

    html = build_export_html_document(
        [], config, summary_runs=[_full_summary_run_with_vehicle_allocations()]
    )
    payload = _extract_payload(html)
    tour_mode = payload["states"]["Weighted||Percent"]["tour_mode"]

    assert tour_mode["kind"] == "page"
    region = _region_nodes(tour_mode)["tour_mode_vehicles"]
    assert region["selector_ids"] == ["vehicle_occupancy"]
    assert sorted(region["variants"]) == ['["All"]', '["High"]', '["Low"]']

    age_all = _plot_node_by_title(
        region["variants"]['["All"]'],
        "Allocated Vehicle Age by Occupancy Level",
    )
    age_high = _plot_node_by_title(
        region["variants"]['["High"]'],
        "Allocated Vehicle Age by Occupancy Level",
    )
    age_low = _plot_node_by_title(
        region["variants"]['["Low"]'],
        "Allocated Vehicle Age by Occupancy Level",
    )

    assert age_all["figure"]["data"][0]["x"] == ["0", "20+"]
    assert age_high["figure"]["data"][0]["x"] == ["0", "20+"]
    assert age_low["figure"]["data"][0]["x"] == ["0", "20+"]
    assert age_all["figure"]["data"][0]["y"] != age_high["figure"]["data"][0]["y"]
    assert age_high["figure"]["data"][0]["y"] != age_low["figure"]["data"][0]["y"]


def test_build_export_html_document_serializes_long_term_geography_variants(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        geography_lines=[
            "enabled: true",
            "landuse_col: COUNTY",
        ],
        export_html_lines=[
            "pages:",
            "  long_term_choices:",
            "    mandatory_location_choice:",
            "      geography_level: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    page_defs = _flatten_page_descriptors(payload["pages"])

    assert page_defs["mandatory_location_choice"]["selectors"][0]["id"] == "geography_level"
    assert page_defs["mandatory_location_choice"]["selectors"][0]["request_mode"] == "all"
    assert set(page_defs["mandatory_location_choice"]["selectors"][0]["resolved_values"]) == {
        "All",
        "Suburban",
        "Urban",
    }
    assert page_defs["mandatory_location_choice"]["selectors"][0]["export_enabled"] is True
    assert page_defs["mandatory_location_choice"]["selectors"][1]["id"] == "geography"
    assert page_defs["mandatory_location_choice"]["selectors"][1]["export_enabled"] is True
    assert "All" in page_defs["mandatory_location_choice"]["selectors"][1]["resolved_values"]
    assert len(page_defs["mandatory_location_choice"]["selectors"][1]["resolved_values"]) > 1

    mandatory_location_choice = payload["states"]["Weighted||Percent"]["mandatory_location_choice"]
    assert mandatory_location_choice["kind"] == "page"
    commuting_variants = sorted(
        _region_nodes(mandatory_location_choice)["commuting_flows"]["variants"]
    )
    assert '["All","All"]' in commuting_variants
    assert any("Urban" in key for key in commuting_variants)
    assert any("Suburban" in key for key in commuting_variants)


def test_build_export_html_document_warns_and_falls_back_when_long_term_geography_is_unavailable(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  long_term_choices:",
            "    shadow_pricing:",
            "      student_type: all",
            "      parts:",
            "        school_plot:",
            "          enabled: false",
            "        school_table:",
            "          enabled: false",
        ],
    )
    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    page_defs = _flatten_page_descriptors(payload["pages"])

    assert [selector["id"] for selector in page_defs["shadow_pricing"]["selectors"]] == [
        "geography_level"
    ]
    assert payload["states"]["Weighted||Percent"]["shadow_pricing"]["kind"] == "page"


def test_build_export_html_document_serializes_stop_frequency_four_chart_variant(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  tour_stop_frequency:",
                "    tour_purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    tour_stop_frequency = payload["states"]["Weighted||Percent"]["tour_stop_frequency"]

    assert tour_stop_frequency["kind"] == "page"
    assert sorted(_region_nodes(tour_stop_frequency)["tour_stop_frequency_body"]["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]
    variant_nodes = _walk_nodes(
        _region_nodes(tour_stop_frequency)["tour_stop_frequency_body"]["variants"][
            '["eatout"]'
        ]
    )
    plotly_titles = {
        node.get("figure", {}).get("layout", {}).get("title", {}).get("text")
        for node in variant_nodes
        if node.get("kind") == "plotly"
    }
    assert {
        "Tour Stop Frequency - eatout, Both",
        "Tour Stop Frequency - eatout, Outbound",
        "Tour Stop Frequency - eatout, Inbound",
    }.issubset(plotly_titles)


def test_build_export_html_document_serializes_stop_timing_two_chart_variant(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  trip_stop_time:",
                "    tour_purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    trip_stop_time = payload["states"]["Weighted||Percent"]["trip_stop_time"]

    assert trip_stop_time["kind"] == "page"
    assert sorted(_region_nodes(trip_stop_time)["trip_stop_time_body"]["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    variant_nodes = _walk_nodes(
        _region_nodes(trip_stop_time)["trip_stop_time_body"]["variants"]['["Total"]']
    )
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 2


def test_build_export_html_document_serializes_joint_tours_hh_size_variants(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  daily_travel:",
            "    daily_activity_pattern:",
            "      person_type: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    daily_activity_pattern = payload["states"]["Weighted||Percent"]["daily_activity_pattern"]

    assert daily_activity_pattern["kind"] == "page"
    assert sorted(_region_nodes(daily_activity_pattern)["activity_pattern_body"]["variants"]) == [
        '["Total"]',
        '["worker"]',
    ]
    variant_nodes = _walk_nodes(
        _region_nodes(daily_activity_pattern)["activity_pattern_body"]["variants"]['["worker"]']
    )
    assert any(
        node.get("kind") in {"plotly", "card", "table"} for node in variant_nodes
    )


def test_build_export_html_document_serializes_trip_mode_tour_purpose_variants(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      tour_purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    trip_mode = payload["states"]["Weighted||Percent"]["trip_mode"]

    assert trip_mode["kind"] == "page"
    assert sorted(_region_nodes(trip_mode)["trip_summary_mode_body"]["variants"]) == [
        '["All"]',
        '["eatout"]',
        '["social"]',
    ]
    page_nodes = _walk_nodes(trip_mode)
    widget_nodes = [node for node in page_nodes if node.get("kind") == "widget"]
    assert any(
        node.get("selector_id") == "tour_purpose"
        and node.get("export_enabled")
        and not node.get("disabled")
        for node in widget_nodes
    )
    assert not any(node.get("selector_id") == "tour_mode" for node in widget_nodes)
    variant_nodes = _walk_nodes(
        _region_nodes(trip_mode)["trip_summary_mode_body"]["variants"]['["eatout"]']
    )
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 3


def test_build_export_html_document_rejects_unknown_page_and_selector_ids(
    tmp_path: Path,
) -> None:
    bad_page_config = _write_config(
        tmp_path / "bad_page",
        export_html_lines=[
            "pages:",
            "  unknown_page:",
            "    purpose: all",
        ],
    )
    with pytest.raises(
        ValueError, match="Unsupported visualizer.export_html.pages entries"
    ):
        build_export_html_document(
            [], bad_page_config, summary_runs=[_full_summary_run()]
        )

    bad_selector_config = _write_config(
        tmp_path / "bad_selector",
        export_html_lines=[
            "pages:",
            "  trip_summaries:",
            "    trip_mode:",
            "      unknown_selector: all",
        ],
    )
    with pytest.raises(
        ValueError,
        match="Unsupported visualizer.export_html.pages.trip_summaries.trip_mode entries",
    ):
        build_export_html_document(
            [],
            bad_selector_config,
            summary_runs=[_full_summary_run()],
        )


def test_export_html_save_writes_single_client_side_html_file(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )
    out_dir = tmp_path / "html_export"
    out_dir.mkdir()
    out_path = out_dir / "dashboard.html"

    write_export_html_document(
        out_path,
        [],
        config,
        summary_runs=[_full_summary_run()],
    )

    assert out_path.exists()
    diagnostics_path = out_dir / "dashboard.diagnostics.json"
    assert sorted(path.name for path in out_dir.iterdir()) == [
        "dashboard.diagnostics.json",
        "dashboard.html",
    ]

    html = out_path.read_text(encoding="utf-8")
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert "Weighting" in html
    assert "Unweighted" in html
    assert "Count" in html
    assert "activitysim-export-data" in html
    assert "Plotly.react" in html
    assert "export-layout" in html
    assert "Runs Loaded" in html
    assert "Tour Purpose" in html
    assert "panel.models.state.State" not in html
    assert diagnostics["schema_version"] == 1
    assert "Weighted||Percent" in diagnostics["states"]


def test_export_html_config_supports_missing_data_display(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        visualizer_lines=["missing_data_display: blank"],
    )

    assert config.missing_data_display == "blank"


def test_export_html_config_rejects_invalid_missing_data_display(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="visualizer.missing_data_display must be either 'card' or 'blank'",
    ):
        _write_config(
            tmp_path,
            visualizer_lines=["missing_data_display: loud"],
        )


def test_export_html_save_writes_visualization_diagnostics_sidecar(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["raw_trip_demo"],
        export_html_lines=[
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )
    out_path = tmp_path / "dashboard.html"

    write_export_html_document(out_path, [], config, summary_runs=[_full_summary_run()])

    diagnostics = json.loads(
        (tmp_path / "dashboard.diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics["states"]["Weighted||Percent"] == {}


def test_export_html_save_fails_fast_without_final_files_when_html_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path)
    out_path = tmp_path / "dashboard.html"

    def fail_html_temp_write(path: Path, contents: str) -> None:
        if "dashboard.html" in path.name and path.suffix == ".tmp":
            raise OSError("disk full")
        path.write_text(contents, encoding="utf-8")

    monkeypatch.setattr("dashboard.export.html._write_text_file", fail_html_temp_write)

    with pytest.raises(ExportBuildError, match="write HTML atomically"):
        write_export_html_document(out_path, [], config, summary_runs=[_full_summary_run()])

    assert not out_path.exists()
    assert not (tmp_path / "dashboard.diagnostics.json").exists()


def test_export_html_save_rejects_malformed_assembled_html_before_finalizing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _write_config(tmp_path)
    out_path = tmp_path / "dashboard.html"

    monkeypatch.setattr(
        "dashboard.export.html.build_export_html_shell",
        lambda **kwargs: "<html><body>broken export</body></html>",
    )

    with pytest.raises(ExportBuildError, match="validate assembled HTML"):
        write_export_html_document(out_path, [], config, summary_runs=[_full_summary_run()])

    assert not out_path.exists()
    assert not (tmp_path / "dashboard.diagnostics.json").exists()
