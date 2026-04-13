from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.config import Config
from runtime.models import RunData
from runtime.run_data import prepare_data
from summarize import destination, stops, totals, tour_mode, tour_tod, trips
from summarize.schema import SUMMARY_OUTPUT_COLUMNS


def _write_config(tmp_path: Path, *, column_lines: list[str] | None = None) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        'name: "Canonical Test Config"',
        "runs: []",
        "summaries:",
        "  root: summary_cache",
        "visualizer:",
        '  dashboard_title: "Canonical Test Dashboard"',
    ]
    if column_lines:
        lines.append("columns:")
        lines.extend(f"  {line}" for line in column_lines)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _raw_run_with_alternate_columns() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "hh_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [2],
                "hhsize": [3],
                "num_workers": [1],
                "num_adults": [2],
            }
        ),
        per=pl.DataFrame(
            {
                "pid": [101],
                "hh_id": [1],
                "ptype": [1],
                "home_zone_id": [10],
                "workplace_zone_id": [20],
                "school_zone_id": [0],
                "cdap_activity": ["M"],
            }
        ),
        tours=pl.DataFrame(
            {
                "tid": [1001],
                "pid": [101],
                "hh_id": [1],
                "tour_label": ["eatout"],
                "tour_mode_src": ["DRIVE"],
                "tour_cat_src": ["non-mandatory"],
                "start_period": [8],
                "end_period": [10],
                "duration_periods": [2],
                "origin": [10],
                "destination": [20],
                "stop_frequency": ["1out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id_src": [5001, 5002],
                "tid": [1001, 1001],
                "pid": [101, 101],
                "hh_id": [1, 1],
                "trip_mode_src": ["DRIVEALONE", "WALK"],
                "stop_label": ["shop", "home"],
                "depart_period": [8, 9],
                "outbound": [True, True],
                "trip_num": [1, 2],
                "origin": [10, 20],
                "destination": [20, 30],
            }
        ),
        joint_participants=pl.DataFrame({"tid": [], "pid": []}),
        land_use=pl.DataFrame({"zone_id": [10, 20, 30], "TAZ": [10, 20, 30], "jobs": [7, 8, 9]}),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_default_fallback_columns() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [2],
                "hhsize": [3],
                "num_workers": [1],
                "num_adults": [2],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
                "home_zone_id": [10],
                "workplace_zone_id": [20],
                "school_zone_id": [0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": [1],
                "tour_type": ["eatout"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
                "start": [8],
                "end": [10],
                "duration": [2],
                "origin": [10],
                "destination": [20],
                "stop_frequency": ["1out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001, 5002],
                "tour_id": [1001, 1001],
                "person_id": [101, 101],
                "household_id": [1, 1],
                "trip_mode": ["DRIVEALONE", "WALK"],
                "purpose": ["shop", "home"],
                "depart": [8, 9],
                "outbound": [True, True],
                "trip_num": [1, 2],
                "origin": [10, 20],
                "destination": [20, 30],
            }
        ),
        joint_participants=pl.DataFrame({"tour_id": [], "person_id": []}, schema={"tour_id": pl.Int64, "person_id": pl.Int64}),
        land_use=pl.DataFrame({"zone_id": [10, 20, 30], "TAZ": [10, 20, 30], "EMPLOY_TOT": [7, 8, 9]}),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_tour_type_only(*, label: str = "Base") -> RunData:
    return RunData(
        label=label,
        run_dir=f"C:/runs/{label.lower()}",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "home_zone_id": [10]}),
        per=pl.DataFrame({"person_id": [101], "household_id": [1], "ptype": [1]}),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": [1],
                "tour_type": ["eatout"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
            }
        ),
        trips=pl.DataFrame({"tour_id": [1001], "person_id": [101], "household_id": [1]}),
        joint_participants=pl.DataFrame({"tour_id": [], "person_id": []}, schema={"tour_id": pl.Int64, "person_id": pl.Int64}),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_primary_purpose_only(*, label: str = "Build") -> RunData:
    return RunData(
        label=label,
        run_dir=f"C:/runs/{label.lower()}",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "home_zone_id": [10]}),
        per=pl.DataFrame({"person_id": [101], "household_id": [1], "ptype": [1]}),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": ["shopping"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
            }
        ),
        trips=pl.DataFrame({"tour_id": [1001], "person_id": [101], "household_id": [1]}),
        joint_participants=pl.DataFrame({"tour_id": [], "person_id": []}, schema={"tour_id": pl.Int64, "person_id": pl.Int64}),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _raw_run_with_numeric_tour_purpose_and_string_tour_type() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "home_zone_id": [10]}),
        per=pl.DataFrame({"person_id": [101], "household_id": [1], "ptype": [1]}),
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
            }
        ),
        trips=pl.DataFrame({"tour_id": [1001], "person_id": [101], "household_id": [1]}),
        joint_participants=pl.DataFrame({"tour_id": [], "person_id": []}, schema={"tour_id": pl.Int64, "person_id": pl.Int64}),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_config_normalizes_column_alias_values_and_preserves_order(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        column_lines=[
            "tour_purpose:",
            "  - primary_purpose",
            "  - tour_type",
            "  - primary_purpose",
            "  - '   '",
            "trip_mode: trip_mode_src",
        ],
    )

    assert config.col_tour_purpose == ["primary_purpose", "tour_type"]
    assert config.col_trip_mode == ["trip_mode_src"]


def test_config_summary_signature_changes_when_alias_lists_change(tmp_path: Path) -> None:
    config_a = _write_config(
        tmp_path / "a",
        column_lines=["tour_purpose: [primary_purpose, tour_type]"],
    )
    config_b = _write_config(
        tmp_path / "b",
        column_lines=["tour_purpose: [tour_type, primary_purpose]"],
    )

    assert config_a.summary_config_digest != config_b.summary_config_digest


def test_prepare_data_uses_default_fallbacks_for_purpose_timing_and_employment(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    assert config.col_tour_purpose == [
        "tour_purpose",
        "primary_purpose",
        "tour_type",
        "purpose",
    ]
    assert config.col_trip_purpose == ["trip_purpose", "purpose"]

    prepared = prepare_data(_raw_run_with_default_fallback_columns(), config)

    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]
    assert prepared.tours["start_hour"].to_list() == [8]
    assert prepared.tours["end_hour"].to_list() == [10]
    assert prepared.tours["tourdur"].to_list() == [2]
    assert prepared.trips["tour_purpose"].to_list() == ["eatout", "eatout"]
    assert prepared.trips["trip_purpose"].to_list() == ["shop", "home"]
    assert prepared.trips["depart_hour"].to_list() == [8, 9]
    assert prepared.land_use["EMPLOYMENT"].to_list() == [7, 8, 9]


def test_prepare_data_resolves_shared_alias_lists_independently_per_run(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        column_lines=["tour_purpose: [primary_purpose, tour_type, purpose]"],
    )

    prepared_a = prepare_data(_raw_run_with_tour_type_only(label="Base"), config)
    prepared_b = prepare_data(_raw_run_with_primary_purpose_only(label="Build"), config)

    assert prepared_a.tours["tour_purpose"].to_list() == ["eatout"]
    assert prepared_b.tours["tour_purpose"].to_list() == ["shopping"]


def test_prepare_data_prefers_non_numeric_purpose_alias_when_multiple_candidates_exist(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        column_lines=["tour_purpose: [primary_purpose, tour_type]"],
    )

    prepared = prepare_data(_raw_run_with_default_fallback_columns(), config)

    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]


def test_prepare_data_overwrites_numeric_raw_tour_purpose_with_readable_alias(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)

    prepared = prepare_data(_raw_run_with_numeric_tour_purpose_and_string_tour_type(), config)

    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]


def test_prepare_data_materializes_canonical_summary_columns_from_config_overrides(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        column_lines=[
            "household_id: hh_id",
            "person_id: pid",
            "tour_id: tid",
            "trip_id: trip_id_src",
            "tour_purpose: tour_label",
            "trip_purpose: stop_label",
            "tour_mode: tour_mode_src",
            "trip_mode: trip_mode_src",
            "tour_category: tour_cat_src",
            "tour_start: start_period",
            "tour_end: end_period",
            "tour_duration: duration_periods",
            "trip_depart: depart_period",
            "total_employment: jobs",
        ],
    )

    prepared = prepare_data(_raw_run_with_alternate_columns(), config)

    assert prepared.hh["household_id"].to_list() == [1]
    assert prepared.per["person_id"].to_list() == [101]
    assert prepared.tours["tour_id"].to_list() == [1001]
    assert prepared.trips["trip_id"].to_list() == [5001, 5002]
    assert prepared.tours["tour_purpose"].to_list() == ["eatout"]
    assert prepared.tours["tour_mode"].to_list() == ["DRIVE"]
    assert prepared.tours["tour_category"].to_list() == ["non-mandatory"]
    assert prepared.tours["start_hour"].to_list() == [8]
    assert prepared.tours["end_hour"].to_list() == [10]
    assert prepared.tours["tourdur"].to_list() == [2]
    assert prepared.trips["trip_purpose"].to_list() == ["shop", "home"]
    assert prepared.trips["trip_mode"].to_list() == ["DRIVEALONE", "WALK"]
    assert prepared.trips["tour_purpose"].to_list() == ["eatout", "eatout"]
    assert prepared.trips["depart_hour"].to_list() == [8, 9]
    assert prepared.land_use["EMPLOYMENT"].to_list() == [7, 8, 9]


def test_summaries_use_canonical_runtime_columns_and_preserve_output_shapes(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        column_lines=[
            "household_id: hh_id",
            "person_id: pid",
            "tour_id: tid",
            "trip_id: trip_id_src",
            "tour_purpose: tour_label",
            "trip_purpose: stop_label",
            "tour_mode: tour_mode_src",
            "trip_mode: trip_mode_src",
            "tour_category: tour_cat_src",
            "tour_start: start_period",
            "tour_end: end_period",
            "tour_duration: duration_periods",
            "trip_depart: depart_period",
            "total_employment: jobs",
        ],
    )
    prepared = prepare_data(_raw_run_with_alternate_columns(), config)

    trip_mode_profile = trips.trip_mode_profile(prepared, config)
    assert trip_mode_profile.columns == ["purpose", "tour_mode", "trip_mode", "freq"]
    assert trip_mode_profile["purpose"].to_list() == ["eatout", "eatout"]

    stop_purpose = stops.stop_purpose_by_tour_purpose(prepared)
    assert stop_purpose.columns == ["tour_purpose", "stop_purpose", "freq"]
    assert stop_purpose["tour_purpose"].to_list() == ["eatout"]
    assert stop_purpose["stop_purpose"].to_list() == ["shop"]

    stop_freq = stops.stop_freq(prepared)
    assert stop_freq.columns == list(SUMMARY_OUTPUT_COLUMNS["stop_freq"])

    stop_location = stops.stop_location(prepared)
    assert stop_location.columns == list(SUMMARY_OUTPUT_COLUMNS["stop_location"])

    stop_timing = stops.stop_timing(prepared)
    assert stop_timing.columns == list(SUMMARY_OUTPUT_COLUMNS["stop_timing"])

    tour_mode_profile = tour_mode.tour_mode_profile(prepared, config)
    assert tour_mode_profile.columns == list(SUMMARY_OUTPUT_COLUMNS["tour_mode_profile"])

    tour_tod_profiles = tour_tod.tod_profiles(prepared)
    assert tour_tod_profiles.columns == list(SUMMARY_OUTPUT_COLUMNS["tour_tod_profiles"])

    totals_df = totals.system_totals(prepared, config)
    assert totals_df["employment"].to_list() == [24.0]

    distance_df = destination.distance_distribution(prepared)
    assert "purpose" in distance_df.columns
    assert "All NM" in distance_df["purpose"].to_list()
