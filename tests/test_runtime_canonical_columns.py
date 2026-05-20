from __future__ import annotations

from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.config import Config
from processor.models import RunData
from processor.prepare.enrichment.pipeline import prepare_data
from processor.summarize.schema import SUMMARY_OUTPUT_COLUMNS
from processor.summarize.summaries import (
    daily_travel,
    joint_travel,
    legacy,
    long_term,
    tour,
    trip,
)
from processor.tour_purpose import with_summary_tour_purpose


def _write_config(
    tmp_path: Path,
    *,
    column_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
) -> Config:
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
    if extra_lines:
        lines.extend(extra_lines)
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
        land_use=pl.DataFrame(
            {"zone_id": [10, 20, 30], "TAZ": [10, 20, 30], "jobs": [7, 8, 9]}
        ),
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
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(
            {"zone_id": [10, 20, 30], "TAZ": [10, 20, 30], "EMPLOY_TOT": [7, 8, 9]}
        ),
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
        trips=pl.DataFrame(
            {"tour_id": [1001], "person_id": [101], "household_id": [1]}
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
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
        trips=pl.DataFrame(
            {"tour_id": [1001], "person_id": [101], "household_id": [1]}
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
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
        trips=pl.DataFrame(
            {"tour_id": [1001], "person_id": [101], "household_id": [1]}
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_config_normalizes_column_alias_values_and_preserves_order(
    tmp_path: Path,
) -> None:
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


def test_tour_purpose_grouping_flags_default_to_true(tmp_path: Path) -> None:
    config = _write_config(tmp_path)

    assert config.group_joint_tour_purposes is True
    assert config.group_atwork_tour_purposes is True
    assert config.group_school_tour_purposes is True


def test_tour_purpose_grouping_flags_parse_explicit_booleans(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "group_joint_tour_purposes: true",
            "group_atwork_tour_purposes: false",
            "group_school_tour_purposes: true",
        ],
    )

    assert config.group_joint_tour_purposes is True
    assert config.group_atwork_tour_purposes is False
    assert config.group_school_tour_purposes is True


def test_tour_purpose_grouping_flags_allow_explicit_false_overrides(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "group_joint_tour_purposes: false",
            "group_atwork_tour_purposes: false",
            "group_school_tour_purposes: false",
        ],
    )

    assert config.group_joint_tour_purposes is False
    assert config.group_atwork_tour_purposes is False
    assert config.group_school_tour_purposes is False


def test_tour_purpose_grouping_flags_reject_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="group_joint_tour_purposes must be true or false",
    ):
        _write_config(tmp_path, extra_lines=["group_joint_tour_purposes: maybe"])


def test_config_summary_signature_changes_when_alias_lists_change(
    tmp_path: Path,
) -> None:
    config_a = _write_config(
        tmp_path / "a",
        column_lines=["tour_purpose: [primary_purpose, tour_type]"],
    )
    config_b = _write_config(
        tmp_path / "b",
        column_lines=["tour_purpose: [tour_type, primary_purpose]"],
    )

    assert config_a.summary_config_digest != config_b.summary_config_digest


def test_config_summary_signature_changes_when_transit_subsidy_labels_change(
    tmp_path: Path,
) -> None:
    config_a = _write_config(
        tmp_path / "a",
        extra_lines=[
            "transit_subsidies:",
            "  0: No Subsidy",
            "  1: Employer Paid",
        ],
    )
    config_b = _write_config(
        tmp_path / "b",
        extra_lines=[
            "transit_subsidies:",
            "  0: No Subsidy",
            "  1: Universal Pass",
        ],
    )

    assert config_a.summary_config_digest != config_b.summary_config_digest


def test_config_categories_preserve_mapping_order_and_fallback_order(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "categories:",
            "  mode:",
            "    mapping:",
            "      WALK: Walk",
            "      DRIVEALONE: Drive Alone",
            "    order: descending",
        ],
    )

    spec = config.category_spec("mode")
    assert spec is not None
    assert list(spec.mapping_items) == [
        ("WALK", "Walk"),
        ("DRIVEALONE", "Drive Alone"),
    ]
    assert spec.fallback_order == "descending"


def test_category_specs_apply_ascending_descending_and_data_fallbacks(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "categories:",
            "  alpha:",
            "    order: ascending",
            "  omega:",
            "    order: descending",
            "  seen:",
            "    order: data",
        ],
    )

    assert config.ordered_values("alpha", ["b", "c", "a"]) == ["a", "b", "c"]
    assert config.ordered_values("omega", ["b", "c", "a"]) == ["c", "b", "a"]
    assert config.ordered_values("seen", ["b", "c", "a"]) == ["b", "c", "a"]


def test_categories_override_legacy_label_and_order_settings(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "person_types:",
            "  1: Worker Legacy",
            "transit_subsidies:",
            "  1: Subsidy Legacy",
            "geography:",
            "  enabled: true",
            "  landuse_col: COUNTY",
            "  mapping:",
            "    1: Legacy County",
            "modes:",
            "  order:",
            "    - LEGACY_MODE",
            "categories:",
            "  person_type:",
            "    mapping:",
            "      1: Worker New",
            "  transit_subsidy:",
            "    mapping:",
            "      1: Subsidy New",
            "  geography:",
            "    mapping:",
            "      1: New County",
            "  mode:",
            "    mapping:",
            "      NEW_MODE: New Mode",
        ],
    )

    assert config.person_type_label("1") == "Worker New"
    assert config.transit_subsidy_label("1") == "Subsidy New"
    assert config.apply_geo_mapping(pl.Series(["1", "9"])).to_list() == [
        "New County",
        "9",
    ]
    assert config.ordered_modes(["LEGACY_MODE", "NEW_MODE", "OTHER"]) == [
        "NEW_MODE",
        "LEGACY_MODE",
        "OTHER",
    ]


def test_geography_aggregations_support_inline_and_file_mappings(
    tmp_path: Path,
) -> None:
    geography_csv = tmp_path / "district_lookup.csv"
    geography_csv.write_text(
        "\n".join(["MAZ,district", "10,North", "20,South"]),
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        Urban: [10]",
            "        Rural: [20]",
            "    district:",
            "      source_zone_system: maz",
            f"      file: {geography_csv.name}",
            "      zone_id_col: MAZ",
            "      geography_col: district",
        ],
    )

    assert [aggregation.name for aggregation in config.geography_aggregations.aggregations] == [
        "county",
        "district",
    ]
    county = config.geography_aggregations.aggregations[0]
    district = config.geography_aggregations.aggregations[1]
    assert county.lookup_rows == ((10, "Urban"), (20, "Rural"))
    assert district.file == str(geography_csv.resolve())
    assert district.lookup_rows == ((10, "North"), (20, "South"))


def test_geography_aggregation_digest_changes_when_lookup_changes(
    tmp_path: Path,
) -> None:
    config_a = _write_config(
        tmp_path / "a",
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        Urban: [10]",
        ],
    )
    config_b = _write_config(
        tmp_path / "b",
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        Rural: [10]",
        ],
    )

    assert config_a.prepare_config_digest != config_b.prepare_config_digest
    assert config_a.summary_config_digest != config_b.summary_config_digest


def test_enable_maz_geographies_defaults_off_and_only_changes_presentation_digest(
    tmp_path: Path,
) -> None:
    config_a = _write_config(tmp_path / "a")
    config_path = tmp_path / "b" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "\n".join(
            [
                'name: "Canonical Test Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Canonical Test Dashboard"',
                "  enable_maz_geographies: true",
            ]
        ),
        encoding="utf-8",
    )
    config_b = Config.from_yaml(config_path)

    assert config_a.enable_maz_geographies is False
    assert config_b.enable_maz_geographies is True
    assert config_a.prepare_config_digest == config_b.prepare_config_digest
    assert config_a.summary_config_digest == config_b.summary_config_digest
    assert config_a.presentation_config_digest != config_b.presentation_config_digest


def test_typed_geography_summaries_include_configured_aggregation_levels(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "geography:",
            "  enabled: true",
            "  aggregations:",
            "    county:",
            "      source_zone_system: taz",
            "      mapping:",
            "        Urban: [10]",
            "        Rural: [20, 30]",
        ],
    )

    prepared = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "is_worker": [True],
                "home_zone_id": [10],
                "workplace_zone_id": [20],
                "home_geo__county": ["Urban"],
                "work_geo__county": ["Rural"],
                "finalweight": [1.0],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )
    wfh = long_term.wfh(prepared, config)
    flows = long_term.commuting_flows(prepared, config)
    assert ("county" in wfh["geography_type"].to_list()) is True
    assert (
        wfh.filter(pl.col("geography_type") == "county")["geography_id"].to_list()
        == ["Urban"]
    )
    assert (
        flows.filter(pl.col("origin_geography_type") == "county")[
            "origin_geography_id"
        ].to_list()
        == ["Urban"]
    )
    assert (
        flows.filter(pl.col("destination_geography_type") == "county")[
            "destination_geography_id"
        ].to_list()
        == ["Rural"]
    )


def test_config_summary_signature_changes_when_tour_purpose_grouping_changes(
    tmp_path: Path,
) -> None:
    config_a = _write_config(tmp_path / "a")
    config_b = _write_config(
        tmp_path / "b",
        extra_lines=["group_joint_tour_purposes: false"],
    )

    assert config_a.summary_config_digest != config_b.summary_config_digest


def test_transit_subsidy_summary_uses_raw_categories_and_label_overrides(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "person_types:",
            "  1: Full-time worker",
            "  3: University student",
            "transit_subsidies:",
            "  0: No Subsidy",
            "  1: Employer Paid",
            "  2: Student Discount",
        ],
    )
    run = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "person_type": [1, 1, 3, 3, 4],
                "transit_pass_subsidy": [1, 2, 2, 0, 9],
                "is_worker": [True, True, False, False, False],
                "is_student": [False, False, True, True, False],
                "finalweight": [2.0, 1.0, 3.0, 4.0, 5.0],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    result = long_term.transit_subsidy(run, config).sort(
        ["person_type", "transit_subsidy_status"]
    )

    assert result.columns == [
        "person_type",
        "transit_subsidy_status",
        "transit_subsidy_label",
        "person_type_label",
        "person_count",
    ]
    assert result.to_dicts() == [
        {
            "person_type": "1",
            "transit_subsidy_status": "1",
            "transit_subsidy_label": "Employer Paid",
            "person_type_label": "Full-time worker",
            "person_count": 2.0,
        },
        {
            "person_type": "1",
            "transit_subsidy_status": "2",
            "transit_subsidy_label": "Student Discount",
            "person_type_label": "Full-time worker",
            "person_count": 1.0,
        },
        {
            "person_type": "all_person_types",
            "transit_subsidy_status": "1",
            "transit_subsidy_label": "Employer Paid",
            "person_type_label": "All Person Types",
            "person_count": 2.0,
        },
        {
            "person_type": "all_person_types",
            "transit_subsidy_status": "2",
            "transit_subsidy_label": "Student Discount",
            "person_type_label": "All Person Types",
            "person_count": 1.0,
        },
    ]


def _prepared_run_with_groupable_tour_purposes() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1, 2], "home_zone_id": [10, 20]}),
        per=pl.DataFrame(
            {
                "person_id": [101, 102],
                "person_type": ["worker", "student"],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1, 2, 3, 4, 5],
                "person_id": [101, 101, 101, 102, 102],
                "household_id": [1, 1, 1, 2, 2],
                "tour_purpose": [
                    "shopping",
                    "eatout",
                    "escort",
                    "university",
                    "college",
                ],
                "tour_mode": ["DRIVE", "DRIVE", "WALK", "WALK", "WALK"],
                "tour_category": [
                    "non-mandatory",
                    "joint",
                    "atwork",
                    "mandatory",
                    "mandatory",
                ],
                "atwork_subtour_frequency": [
                    "no_subtours",
                    "no_subtours",
                    "1_eat",
                    "no_subtours",
                    "no_subtours",
                ],
                "NUMBER_HH": [1, 3, 1, 1, 1],
                "finalweight": [1.0, 2.0, 1.0, 1.0, 1.0],
                "start_hour": [1, 1, 1, 1, 1],
                "end_hour": [1, 1, 1, 1, 1],
                "tourdur": [1, 1, 1, 1, 1],
                "AUTOSUFF": [2, 2, 1, 0, 0],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1, 2, 3, 4, 5],
                "tour_purpose": [
                    "shopping",
                    "eatout",
                    "escort",
                    "university",
                    "college",
                ],
                "tour_category": [
                    "non-mandatory",
                    "joint",
                    "atwork",
                    "mandatory",
                    "mandatory",
                ],
                "atwork_subtour_frequency": [
                    "no_subtours",
                    "no_subtours",
                    "1_eat",
                    "no_subtours",
                    "no_subtours",
                ],
                "tour_mode": ["DRIVE", "DRIVE", "WALK", "WALK", "WALK"],
                "trip_mode": ["DRIVEALONE", "DRIVEALONE", "WALK", "WALK", "WALK"],
                "depart_hour": [1, 1, 1, 1, 1],
                "stops": [0, 0, 0, 0, 0],
                "od_dist": [5.0, 6.0, 2.0, 4.0, 3.0],
                "num_participants": [1, 3, 1, 1, 1],
                "finalweight": [1.0, 2.0, 1.0, 1.0, 1.0],
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


def test_tour_purpose_grouping_preserves_current_behavior_when_disabled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "group_joint_tour_purposes: false",
            "group_atwork_tour_purposes: false",
            "group_school_tour_purposes: false",
        ],
    )
    prepared = _prepared_run_with_groupable_tour_purposes()
    prepared = RunData(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh=prepared.hh,
        per=prepared.per,
        tours=with_summary_tour_purpose(prepared.tours, config),
        trips=with_summary_tour_purpose(prepared.trips, config),
        joint_participants=prepared.joint_participants,
        land_use=prepared.land_use,
        skim_matrix=prepared.skim_matrix,
        skim_zone_map=prepared.skim_zone_map,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )

    tour_tod_profiles = tour.tour_tod(prepared, config)
    trip_mode_profile = trip.trip_mode(prepared, config)
    person_tour_rates = daily_travel.tour_rate_per_person(prepared, config)

    tour_purposes = set(tour_tod_profiles["tour_purpose"].unique().to_list())
    assert "joint_eatout" in tour_purposes
    assert "escort" in trip_mode_profile["tour_purpose"].unique().to_list()
    assert "university" in person_tour_rates["tour_purpose"].unique().to_list()
    assert "college" in person_tour_rates["tour_purpose"].unique().to_list()


def test_tour_purpose_grouping_rolls_up_joint_atwork_and_school_across_summaries(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run_with_groupable_tour_purposes()
    prepared = RunData(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh=prepared.hh,
        per=prepared.per,
        tours=with_summary_tour_purpose(prepared.tours, config),
        trips=with_summary_tour_purpose(prepared.trips, config),
        joint_participants=prepared.joint_participants,
        land_use=prepared.land_use,
        skim_matrix=prepared.skim_matrix,
        skim_zone_map=prepared.skim_zone_map,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )

    tour_tod_profiles = tour.tour_tod(prepared, config)
    trip_mode_profile = trip.trip_mode(prepared, config)
    person_tour_rates = daily_travel.tour_rate_per_person(prepared, config)

    tour_purposes = set(tour_tod_profiles["tour_purpose"].unique().to_list())
    assert "joint" in tour_purposes
    assert "joint_eatout" not in tour_purposes
    assert "school" in tour_purposes
    assert "university" not in tour_purposes
    assert "college" not in tour_purposes

    trip_purposes = set(trip_mode_profile["tour_purpose"].unique().to_list())
    assert {"joint", "atwork", "school", "all_tour_purposes"}.issubset(trip_purposes)
    assert "escort" not in trip_purposes
    assert "university" not in trip_purposes
    assert "college" not in trip_purposes

    rate_purposes = set(person_tour_rates["tour_purpose"].unique().to_list())
    assert "school" in rate_purposes
    assert "university" not in rate_purposes
    assert "college" not in rate_purposes

    non_total = tour_tod_profiles.filter(pl.col("tour_purpose") != "all_tour_purposes")
    total = tour_tod_profiles.filter(pl.col("tour_purpose") == "all_tour_purposes")
    assert total["departure_tour_count"].sum() == non_total["departure_tour_count"].sum()


def test_atwork_grouping_does_not_relabel_parent_mandatory_work_tours(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "group_joint_tour_purposes: true",
            "group_atwork_tour_purposes: true",
            "group_school_tour_purposes: false",
        ],
    )
    tours = pl.DataFrame(
        {
            "tour_id": [1, 2],
            "tour_category": ["mandatory", "atwork"],
            "tour_purpose": ["work", "eat"],
            "atwork_subtour_frequency": ["eat", ""],
        }
    )

    grouped = with_summary_tour_purpose(tours, config)

    assert grouped["summary_tour_purpose"].to_list() == ["work", "atwork"]


def test_atwork_subtour_frequency_summary_counts_parent_work_tours_only(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_purpose": ["work", "work", "atwork", "work"],
                "tour_category": ["mandatory", "mandatory", "atwork", "non_mandatory"],
                "atwork_subtour_frequency": ["no_subtours", "eat", "", "business1"],
                "finalweight": [2.0, 3.0, 10.0, 5.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = tour.at_work_sub_tour_freq(rd, config)

    assert summary.sort("atwork_subtour_frequency_category").to_dict(as_series=False) == {
        "atwork_subtour_frequency_category": ["eat", "no_subtours"],
        "atwork_subtour_count": [3.0, 2.0],
    }


def test_escorted_tour_summaries_exclude_child_person_types(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103],
                "person_type": [4, 7, 2],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 1002, 1003, 1004],
                "person_id": [101, 101, 103, 102],
                "person_type": [4, 4, 2, 7],
                "tour_purpose": ["escort", "shopping", "escort", "school"],
                "school_esc_outbound": ["ride_share", None, "pure_escort", "pure_escort"],
                "school_esc_inbound": [None, "ride_share", "pure_escort", "ride_share"],
                "SKIMDIST": [12.2, 7.6, 44.4, 9.1],
                "num_ob_stops": [1, 5, 4, 2],
                "num_ib_stops": [0, 3, 5, 1],
                "num_tot_stops": [1, 8, 9, 3],
                "finalweight": [2.0, 4.0, 3.0, 5.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1001, 1001, 1003, 1003, 1004],
                "od_dist": [5.4, 6.2, 8.8, 41.1, 9.9],
                "inbound": [0, 1, 0, 1, 0],
                "finalweight": [2.0, 2.0, 3.0, 3.0, 5.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    total = daily_travel.total_escorted_tours(rd, config)
    school = daily_travel.escorted_tours_to_from_school(rd, config).sort(
        ["escort_type", "direction"]
    )
    purposes = daily_travel.adult_escorted_tour_purposes_by_direction(rd, config).sort(
        ["tour_purpose", "direction"]
    )
    person_types = daily_travel.adult_escorted_tours_by_person_type_and_direction(
        rd, config
    ).sort(["person_type", "direction"])
    tour_distance = (
        daily_travel.adult_escorted_tour_distance_distribution_by_direction(
            rd, config
        ).sort(["direction", "distance_bin"])
    )
    trip_distance = (
        daily_travel.adult_escorted_trip_distance_distribution_by_direction(
            rd, config
        ).sort(["direction", "distance_bin"])
    )
    stop_frequency = daily_travel.adult_escort_trip_stop_frequency(rd, config).sort(
        ["tour_purpose", "outbound_stop_count", "inbound_stop_count", "total_stop_count"]
    )

    assert total.to_dict(as_series=False) == {"tour_count": [5.0]}
    assert school.to_dict(as_series=False) == {
        "escort_type": [
            "pure_escort",
            "pure_escort",
            "pure_escort",
            "ride_share",
            "ride_share",
        ],
        "direction": [
            "all_directions",
            "inbound",
            "outbound",
            "all_directions",
            "outbound",
        ],
        "tour_count": [6.0, 3.0, 3.0, 2.0, 2.0],
    }
    assert purposes.to_dict(as_series=False) == {
        "tour_purpose": ["escort", "escort", "escort"],
        "direction": ["all_directions", "inbound", "outbound"],
        "tour_count": [8.0, 3.0, 5.0],
    }
    assert person_types.to_dict(as_series=False) == {
        "person_type": ["2", "2", "2", "4"],
        "direction": [
            "both",
            "inbound",
            "outbound",
            "outbound",
        ],
        "tour_count": [3.0, 3.0, 3.0, 2.0],
    }
    assert tour_distance.to_dict(as_series=False) == {
        "distance_bin": ["40+", "40+", "12", "40+"],
        "direction": [
            "both",
            "inbound",
            "outbound",
            "outbound",
        ],
        "tour_count": [3.0, 3.0, 2.0, 3.0],
    }
    assert trip_distance.to_dict(as_series=False) == {
        "distance_bin": ["40+", "9", "40+", "5", "9"],
        "direction": [
            "both",
            "both",
            "inbound",
            "outbound",
            "outbound",
        ],
        "trip_count": [3.0, 3.0, 3.0, 2.0, 3.0],
    }
    assert stop_frequency.to_dict(as_series=False) == {
        "tour_purpose": ["escort", "escort"],
        "outbound_stop_count": [1, 3],
        "inbound_stop_count": [0, 3],
        "total_stop_count": [1, 6],
        "tour_count": [2.0, 3.0],
    }


def test_adult_escort_event_stop_distribution_filters_to_explicit_escort_types(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103],
                "person_type": [4, 2, 7],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 1002, 1003, 1004],
                "person_id": [101, 101, 102, 103],
                "person_type": [4, 4, 2, 7],
                "tour_purpose": ["escort", "escort", "escort", "school"],
                "summary_tour_purpose": ["escort", "escort", "escort", "school"],
                "school_esc_outbound": [
                    "ride_share",
                    "mystery_mode",
                    "pure_escort",
                    "pure_escort",
                ],
                "school_esc_inbound": [None, "ride_share", "pure_escort", "ride_share"],
                "finalweight": [2.0, 5.0, 3.0, 7.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1001, 1001, 1002, 1003, 1004],
                "escort_event_role": [
                    "dropoff",
                    "pickup",
                    "dropoff",
                    "pickup",
                    "dropoff",
                ],
                "escort_stops_before_event": [1, 2, 0, 0, 9],
                "escort_stops_after_event": [0, 1, 1, 0, 9],
                "finalweight": [2.0, 2.0, 5.0, 3.0, 7.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = daily_travel.adult_escort_event_stop_distribution(rd, config).sort(
        ["segment", "stop_count"]
    )

    assert summary.to_dict(as_series=False) == {
        "segment": [
            "inbound_after_pickup",
            "inbound_before_pickup",
            "outbound_after_dropoff",
            "outbound_before_dropoff",
        ],
        "stop_count": [0, 0, 0, 1],
        "tour_count": [3.0, 3.0, 2.0, 2.0],
    }


def test_adult_escort_distance_distributions_filter_to_explicit_escort_types(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103],
                "person_type": [4, 2, 7],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 1002, 1003, 1004],
                "person_id": [101, 101, 102, 103],
                "person_type": [4, 4, 2, 7],
                "tour_purpose": ["escort", "escort", "escort", "school"],
                "summary_tour_purpose": ["escort", "escort", "escort", "school"],
                "school_esc_outbound": [
                    "ride_share",
                    "mystery_mode",
                    "pure_escort",
                    "pure_escort",
                ],
                "school_esc_inbound": [None, "ride_share", "pure_escort", "ride_share"],
                "SKIMDIST": [12.2, 18.7, 44.4, 9.1],
                "finalweight": [2.0, 5.0, 3.0, 7.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1001, 1001, 1002, 1003, 1003, 1004],
                "od_dist": [5.4, 6.2, 18.0, 8.8, 41.1, 9.9],
                "inbound": [0, 1, 0, 0, 1, 0],
                "finalweight": [2.0, 2.0, 5.0, 3.0, 3.0, 7.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    tour_distance = (
        daily_travel.adult_escorted_tour_distance_distribution_by_direction(
            rd, config
        ).sort(["direction", "distance_bin"])
    )
    trip_distance = (
        daily_travel.adult_escorted_trip_distance_distribution_by_direction(
            rd, config
        ).sort(["direction", "distance_bin"])
    )

    assert tour_distance.to_dict(as_series=False) == {
        "distance_bin": ["40+", "19", "40+", "12", "40+"],
        "direction": ["both", "inbound", "inbound", "outbound", "outbound"],
        "tour_count": [3.0, 5.0, 3.0, 2.0, 3.0],
    }
    assert trip_distance.to_dict(as_series=False) == {
        "distance_bin": ["40+", "9", "40+", "5", "9"],
        "direction": [
            "both",
            "both",
            "inbound",
            "outbound",
            "outbound",
        ],
        "trip_count": [3.0, 3.0, 3.0, 2.0, 3.0],
    }


def test_student_school_escort_status_by_direction_summarizes_student_school_tours(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "person_id": [201, 202, 203, 204],
                "person_type": [6, 7, 4, 8],
                "finalweight": [1.0, 1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [2001, 2002, 2003, 2004, 2005, 2006],
                "person_id": [201, 202, 202, 203, 204, 204],
                "person_type": [6, 7, 7, 4, 8, 8],
                "tour_purpose": ["school", "school", "school", "school", "shopping", "school"],
                "school_esc_outbound": ["none", "pure_escort", "ride_share", "pure_escort", "ride_share", "pure_escort"],
                "school_esc_inbound": ["none", "ride_share", "none", "pure_escort", "ride_share", "pure_escort"],
                "finalweight": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = daily_travel.student_school_escort_status_by_direction(rd, config).sort(
        ["direction", "escort_type"]
    )

    assert summary.to_dict(as_series=False) == {
        "direction": [
            "both",
            "both",
            "inbound",
            "inbound",
            "inbound",
            "outbound",
            "outbound",
            "outbound",
        ],
        "escort_type": [
            "pure_escort",
            "ride_share",
            "not_escorted",
            "pure_escort",
            "ride_share",
            "not_escorted",
            "pure_escort",
            "ride_share",
        ],
        "tour_count": [6.0, 2.0, 4.0, 6.0, 2.0, 1.0, 8.0, 3.0],
    }


def test_student_school_escort_status_treats_blank_labels_as_not_escorted(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(
            {
                "person_id": [201, 202],
                "person_type": [6, 7],
                "finalweight": [1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [2001, 2002],
                "person_id": [201, 202],
                "person_type": [6, 7],
                "tour_purpose": ["school", "school"],
                "school_esc_outbound": ["", "   "],
                "school_esc_inbound": ["", None],
                "finalweight": [2.0, 3.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = daily_travel.student_school_escort_status_by_direction(rd, config).sort(
        ["direction", "escort_type"]
    )

    assert summary.to_dict(as_series=False) == {
        "direction": [
            "inbound",
            "outbound",
        ],
        "escort_type": [
            "not_escorted",
            "not_escorted",
        ],
        "tour_count": [5.0, 5.0],
    }


def test_households_with_school_escorting_by_student_count_and_direction_summarizes_weighted_households(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2, 3, 4],
                "finalweight": [10.0, 20.0, 30.0, 40.0],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103, 104, 105, 106],
                "household_id": [1, 1, 2, 3, 3, 4],
                "person_type": [6, 7, 8, 4, 6, 4],
                "finalweight": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001, 1002, 1003, 1004, 1005],
                "person_id": [101, 103, 104, 105, 106],
                "tour_purpose": ["school", "school", "school", "school", "work"],
                "school_esc_outbound": [
                    "pure_escort",
                    "ride_share",
                    "pure_escort",
                    "none",
                    "ride_share",
                ],
                "school_esc_inbound": [
                    "none",
                    "ride_share",
                    "pure_escort",
                    "ride_share",
                    "ride_share",
                ],
                "finalweight": [1.0, 1.0, 1.0, 1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    denominator = daily_travel.student_households_by_student_count(rd, config).sort(
        "student_count"
    )
    summary = (
        daily_travel.households_with_school_escorting_by_student_count_and_direction(
            rd, config
        ).sort(["direction", "student_count"])
    )

    assert denominator.to_dict(as_series=False) == {
        "student_count": [1, 2],
        "household_count": [50.0, 10.0],
    }
    assert summary.to_dict(as_series=False) == {
        "student_count": [1, 2, 1, 2, 1, 2],
        "direction": [
            "both",
            "both",
            "inbound",
            "inbound",
            "outbound",
            "outbound",
        ],
        "household_count": [20.0, 0.0, 50.0, 0.0, 20.0, 10.0],
    }


def test_schoolkids_per_escorted_tour_by_student_count_and_direction_summarizes_weighted_average(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2, 3, 4],
                "finalweight": [10.0, 20.0, 30.0, 40.0],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 103, 104, 105, 106],
                "household_id": [1, 1, 2, 3, 3, 4],
                "person_type": [1, 6, 2, 4, 7, 4],
                "finalweight": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [2001, 2002, 2003, 2004, 2005, 2006],
                "person_id": [101, 101, 103, 104, 104, 106],
                "tour_purpose": ["escort", "escort", "escort", "escort", "shopping", "escort"],
                "school_esc_outbound": [
                    "pure_escort",
                    "ride_share",
                    "pure_escort",
                    "none",
                    "pure_escort",
                    "ride_share",
                ],
                "school_esc_inbound": [
                    "none",
                    "ride_share",
                    "pure_escort",
                    "pure_escort",
                    "pure_escort",
                    "ride_share",
                ],
                "num_escorted": [1.0, 2.0, 3.0, 4.0, 9.0, None],
                "finalweight": [2.0, 1.0, 3.0, 4.0, 5.0, 6.0],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    summary = (
        daily_travel.schoolkids_per_escorted_tour_by_student_count_and_direction(
            rd, config
        ).sort(["direction", "student_count"])
    )

    assert summary.to_dict(as_series=False) == {
        "student_count": [1, 1, 1],
        "direction": [
            "both",
            "inbound",
            "outbound",
        ],
        "avg_schoolkids_per_tour": [2.0, 3.6, 1.3333333333333333],
        "tour_count": [1.0, 5.0, 3.0],
    }


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

    prepared = prepare_data(
        _raw_run_with_numeric_tour_purpose_and_string_tour_type(), config
    )

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

    trip_mode_profile = trip.trip_mode(prepared, config)
    assert trip_mode_profile.columns == list(
        SUMMARY_OUTPUT_COLUMNS["trip_mode_by_tour_purpose_and_tour_mode"]
    )
    assert "eatout" in trip_mode_profile["tour_purpose"].to_list()

    stop_purpose = trip.stop_purpose_by_tour_purpose(prepared, config)
    assert stop_purpose.columns == list(
        SUMMARY_OUTPUT_COLUMNS["stop_destination_purpose_by_tour_purpose"]
    )
    assert stop_purpose["tour_purpose"].to_list() == ["eatout"]
    assert stop_purpose["stop_destination_purpose"].to_list() == ["shop"]

    stop_freq = tour.stop_freq(prepared, config)
    assert stop_freq.columns == list(
        SUMMARY_OUTPUT_COLUMNS["tour_stop_frequency_by_tour_purpose"]
    )

    stop_location = trip.stop_ood_distance(prepared, config)
    assert stop_location.columns == list(
        SUMMARY_OUTPUT_COLUMNS["stop_out_of_direction_distance_by_tour_purpose"]
    )
    assert "all_tour_purposes" in stop_location["tour_purpose"].unique().to_list()
    assert "eatout" in stop_location["tour_purpose"].unique().to_list()

    stop_timing = trip.trip_stop_tod(prepared, config)
    assert stop_timing.columns == list(
        SUMMARY_OUTPUT_COLUMNS["trip_departure_time_by_purpose"]
    )
    assert "all_tour_purposes" in stop_timing["tour_purpose"].unique().to_list()
    assert "eatout" in stop_timing["tour_purpose"].unique().to_list()

    tour_mode_profile = legacy.tour_mode_profile(prepared, config)
    assert tour_mode_profile.columns == [
        "tour_mode",
        "purpose",
        "freq_as0",
        "freq_as1",
        "freq_as2",
        "freq_all",
    ]

    tour_tod_profiles = tour.tour_tod(prepared, config)
    assert tour_tod_profiles.columns == [
        "time_bin",
        "tour_purpose",
        "departure_tour_count",
        "arrival_tour_count",
        "duration_tour_count",
    ]
    assert "all_tour_purposes" in tour_tod_profiles["tour_purpose"].unique().to_list()
    assert "eatout" in tour_tod_profiles["tour_purpose"].unique().to_list()

    totals_df = legacy.system_totals(prepared, config)
    assert totals_df["employment"].to_list() == [24.0]

    distance_df = legacy.distance_distribution(prepared, config)
    assert "purpose" in distance_df.columns
    assert "All NM" in distance_df["purpose"].to_list()


def test_summaries_return_empty_tables_when_canonical_columns_are_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = prepare_data(_raw_run_with_default_fallback_columns(), config)

    prepared = RunData(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh=prepared.hh,
        per=prepared.per,
        tours=prepared.tours.drop(["tour_purpose", "summary_tour_purpose"]),
        trips=prepared.trips.drop(["tour_purpose", "summary_tour_purpose", "trip_purpose"]),
        joint_participants=prepared.joint_participants,
        land_use=prepared.land_use,
        skim_matrix=prepared.skim_matrix,
        skim_zone_map=prepared.skim_zone_map,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )

    assert trip.trip_mode(prepared, config).is_empty()
    assert trip.stop_purpose_by_tour_purpose(prepared, config).is_empty()
    assert trip.trip_stop_tod(prepared, config).is_empty()
    assert trip.stop_ood_distance(prepared, config).is_empty()
    assert tour.stop_freq(prepared, config).is_empty()
    assert tour.tour_tod(prepared, config).is_empty()
    assert legacy.distance_distribution(prepared, config).is_empty()


def test_prepare_data_skips_fragile_joins_when_dependency_keys_are_missing(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    raw = _raw_run_with_default_fallback_columns()
    raw = RunData(
        label=raw.label,
        run_dir=raw.run_dir,
        skim_file=raw.skim_file,
        hh=raw.hh,
        per=raw.per.drop("household_id"),
        tours=raw.tours.drop("person_id"),
        trips=raw.trips.drop("tour_id"),
        joint_participants=raw.joint_participants.drop("tour_id"),
        land_use=pl.DataFrame(),
        skim_matrix=raw.skim_matrix,
        skim_zone_map=raw.skim_zone_map,
        hh_weight_col=raw.hh_weight_col,
        person_weight_col=raw.person_weight_col,
        trip_weight_col=raw.trip_weight_col,
    )

    prepared = prepare_data(raw, config)

    assert "finalweight" in prepared.per.columns
    assert prepared.per["finalweight"].to_list() == [1.0]
    assert "finalweight" in prepared.tours.columns
    assert prepared.tours["finalweight"].to_list() == [1.0]
    assert "finalweight" in prepared.trips.columns
    assert prepared.trips["finalweight"].to_list() == [1.0, 1.0]
    assert "NUMBER_HH" in prepared.tours.columns
    assert prepared.tours["NUMBER_HH"].to_list() == [1]


def test_person_jtp_by_household_size_returns_counts_for_runtime_value_modes(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    rd = RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1, 2],
                "hhsize": [2, 3],
                "finalweight": [1.0, 1.0],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101, 102, 201],
                "household_id": [1, 1, 2],
                "num_joint_tours": [1, 0, 2],
                "finalweight": [2.0, 1.0, 3.0],
            }
        ),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    result = joint_travel.joint_participation_person_by_hhsize(rd, config)

    assert result.sort("household_size").to_dict(as_series=False) == {
        "household_size": [2, 3],
        "joint_tour_person_count": [2.0, 3.0],
        "total_person_count": [3.0, 3.0],
    }
