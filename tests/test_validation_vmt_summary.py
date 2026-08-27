from __future__ import annotations

from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.models import RunData
from processor.summarize.summaries import validation


def _run_data(
    *,
    trips: pl.DataFrame,
    hh: pl.DataFrame | None = None,
    skimjoin_manifest: dict[str, object] | None = None,
) -> RunData:
    return RunData(
        label="Base",
        run_dir="",
        skim_file=None,
        hh=hh if hh is not None else pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=trips,
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skimjoin_manifest=skimjoin_manifest or {},
    )


def _all_geographies_rows(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("geography_type") == "all_geographies").sort(
        ["income_segment", "household_size", "mode", "time_period"]
    )


def test_auto_vmt_segment_summary_prefers_skim_auto_distance() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "household_id": [1, 1, 1],
                "trip_mode": ["SOV", "PNR_TRANSIT", "WALK"],
                "skim_auto_distance": [10.0, 5.0, None],
                "od_dist": [99.0, 99.0, 99.0],
                "trip_period": ["AM", "AM", "AM"],
                "num_participants": [1, 1, 1],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "income_segment": [3],
                "HHSIZE": [2],
                "home_taz": [101],
                "home_county": ["County"],
                "home_mpo": ["Metro"],
                "DISTRICT9": ["Legacy District"],
            }
        ),
    )

    result = validation.auto_vmt_by_home_geography_income_hhsize_time_period(rd, None)

    all_geo = _all_geographies_rows(result)
    assert all_geo.to_dicts() == [
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "3",
            "household_size": "2",
            "time_period": "AM",
            "mode": "PNR_TRANSIT",
            "auto_vmt": 5.0,
            "trip_count": 1.0,
            "distance_source": "skim_auto_distance",
            "time_period_source": "trip_period",
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "3",
            "household_size": "2",
            "time_period": "Daily",
            "mode": "PNR_TRANSIT",
            "auto_vmt": 5.0,
            "trip_count": 1.0,
            "distance_source": "skim_auto_distance",
            "time_period_source": "trip_period",
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "3",
            "household_size": "2",
            "time_period": "AM",
            "mode": "SOV",
            "auto_vmt": 10.0,
            "trip_count": 1.0,
            "distance_source": "skim_auto_distance",
            "time_period_source": "trip_period",
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "3",
            "household_size": "2",
            "time_period": "Daily",
            "mode": "SOV",
            "auto_vmt": 10.0,
            "trip_count": 1.0,
            "distance_source": "skim_auto_distance",
            "time_period_source": "trip_period",
        }
    ]
    assert (
        all_geo.group_by("time_period")
        .agg(
            pl.col("auto_vmt").sum().alias("auto_vmt"),
            pl.col("trip_count").sum().alias("trip_count"),
        )
        .sort("time_period")
        .to_dicts()
        == [
            {"time_period": "AM", "auto_vmt": 15.0, "trip_count": 2.0},
            {"time_period": "Daily", "auto_vmt": 15.0, "trip_count": 2.0},
        ]
    )
    assert set(result["geography_type"].to_list()) == {
        "all_geographies",
        "home_county",
        "home_mpo",
        "home_taz",
    }
    assert "DISTRICT9" not in set(result["geography_type"].to_list())


def test_auto_vmt_segment_summary_falls_back_to_od_dist_auto_modes() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "household_id": [1, 1, 1],
                "trip_mode": ["SOV", "HOV2", "WALK"],
                "od_dist": [10.0, 6.0, 100.0],
                "trip_period": ["MD", "MD", "MD"],
                "num_participants": [1, 2, 1],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        hh=pl.DataFrame(
            {"household_id": [1], "income_segment": [2], "HHSIZE": [3]}
        ),
    )

    result = validation.auto_vmt_by_home_geography_income_hhsize_time_period(rd, None)

    assert _all_geographies_rows(result).to_dicts() == [
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "2",
            "household_size": "3",
            "time_period": "Daily",
            "mode": "HOV2",
            "auto_vmt": 3.0,
            "trip_count": 1.0,
            "distance_source": "od_dist",
            "time_period_source": "trip_period",
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "2",
            "household_size": "3",
            "time_period": "MD",
            "mode": "HOV2",
            "auto_vmt": 3.0,
            "trip_count": 1.0,
            "distance_source": "od_dist",
            "time_period_source": "trip_period",
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "2",
            "household_size": "3",
            "time_period": "Daily",
            "mode": "SOV",
            "auto_vmt": 10.0,
            "trip_count": 1.0,
            "distance_source": "od_dist",
            "time_period_source": "trip_period",
        },
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "2",
            "household_size": "3",
            "time_period": "MD",
            "mode": "SOV",
            "auto_vmt": 10.0,
            "trip_count": 1.0,
            "distance_source": "od_dist",
            "time_period_source": "trip_period",
        }
    ]


def test_auto_vmt_segment_summary_includes_taxi_and_tnc_auto_modes() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": ["TAXI", "TNC_SINGLE", "WALK"],
                "od_dist": [4.0, 8.0, 100.0],
                "trip_period": ["MD", "MD", "MD"],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
    )

    result = _all_geographies_rows(
        validation.auto_vmt_by_home_geography_income_hhsize_time_period(rd, None)
    )

    assert result.select("mode", "time_period", "auto_vmt").to_dicts() == [
        {"mode": "TAXI", "time_period": "Daily", "auto_vmt": 4.0},
        {"mode": "TAXI", "time_period": "MD", "auto_vmt": 4.0},
        {"mode": "TNC_SINGLE", "time_period": "Daily", "auto_vmt": 8.0},
        {"mode": "TNC_SINGLE", "time_period": "MD", "auto_vmt": 8.0},
    ]


def test_auto_vmt_segment_summary_ignores_skimjoin_period_mapping() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "household_id": [1, 1, 1],
                "trip_mode": ["SOV", "SOV", "SOV"],
                "od_dist": [10.0, 20.0, 5.0],
                "depart_hour": [1, 7, 20],
                "num_participants": [1, 1, 1],
                "finalweight": [1.0, 1.0, 1.0],
            }
        ),
        hh=pl.DataFrame({"household_id": [1], "income_segment": [1], "HHSIZE": [1]}),
        skimjoin_manifest={
            "skimjoin_resolved_network_los_file": "ignored_network_los.yaml",
        },
    )

    result = _all_geographies_rows(
        validation.auto_vmt_by_home_geography_income_hhsize_time_period(rd, None)
    )

    assert result.select("time_period", "auto_vmt", "time_period_source").to_dicts() == [
        {"time_period": "Daily", "auto_vmt": 35.0, "time_period_source": "daily"},
    ]


def test_auto_vmt_segment_summary_uses_daily_and_dimension_fallbacks() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": ["SOV"],
                "od_dist": [7.0],
                "finalweight": [2.0],
            }
        ),
    )

    result = validation.auto_vmt_by_home_geography_income_hhsize_time_period(rd, None)

    assert result.to_dicts() == [
        {
            "geography_type": "all_geographies",
            "geography_id": "all_geographies",
            "income_segment": "all_income_segments",
            "household_size": "all_household_sizes",
            "time_period": "Daily",
            "mode": "SOV",
            "auto_vmt": 14.0,
            "trip_count": 2.0,
            "distance_source": "od_dist",
            "time_period_source": "daily",
        }
    ]


def test_derived_daily_vmt_uses_period_rows_and_preserves_daily_only_groups() -> None:
    period_rows = pl.DataFrame(
        {
            "geography_type": ["home_taz"] * 4,
            "geography_id": ["101"] * 4,
            "income_segment": ["2"] * 4,
            "household_size": ["3"] * 4,
            "time_period": ["AM", "PM", "Daily", "Daily"],
            "mode": ["SOV", "SOV", "SOV", "HOV2"],
            "auto_vmt": [10.0, 20.0, 999.0, 7.0],
            "trip_count": [1.0, 2.0, 99.0, 4.0],
            "distance_source": ["od_dist"] * 4,
            "time_period_source": ["trip_period"] * 4,
        }
    )

    result = validation._with_derived_daily_vmt_rows(period_rows).sort(
        ["mode", "time_period"]
    )

    assert result.select(
        "mode", "time_period", "auto_vmt", "trip_count"
    ).to_dicts() == [
        {
            "mode": "HOV2",
            "time_period": "Daily",
            "auto_vmt": 7.0,
            "trip_count": 4.0,
        },
        {"mode": "SOV", "time_period": "AM", "auto_vmt": 10.0, "trip_count": 1.0},
        {
            "mode": "SOV",
            "time_period": "Daily",
            "auto_vmt": 30.0,
            "trip_count": 3.0,
        },
        {"mode": "SOV", "time_period": "PM", "auto_vmt": 20.0, "trip_count": 2.0},
    ]


def test_auto_vmt_summaries_share_legacy_occupancy_and_daily_total() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": [
                    "SOV",
                    "HOV2",
                    "HOV3",
                    "KNR_TRANSIT",
                    "PNR_TRANSIT",
                    "HOV3",
                    "HOV2",
                    "TNC_SHARED",
                    "AUTO_PASSENGER",
                    "WALK",
                ],
                "skim_auto_distance": [
                    10.0,
                    12.0,
                    9.99,
                    8.0,
                    5.0,
                    7.0,
                    6.0,
                    6.0,
                    4.0,
                    None,
                ],
                "od_dist": [99.0] * 10,
                "trip_period": ["AM"] * 5 + ["PM"] * 5,
                "tour_category": [
                    "mandatory",
                    "mandatory",
                    "mandatory",
                    "mandatory",
                    "mandatory",
                    "joint",
                    "mandatory",
                    "non_mandatory",
                    "non_mandatory",
                    "non_mandatory",
                ],
                "escort_event_role": [
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "dropoff",
                    None,
                    None,
                    None,
                ],
                "num_participants": [995.0] * 8 + [0.0, 1.0],
                "finalweight": [1.0] * 10,
            }
        )
    )

    total = validation.auto_vmt_totals(rd, None)["auto_vmt"][0]
    detailed = validation.auto_vmt_by_home_geography_income_hhsize_time_period(
        rd, None
    )
    detailed_daily_total = (
        detailed.filter(
            (pl.col("geography_type") == "all_geographies")
            & (pl.col("time_period") == "Daily")
        )["auto_vmt"].sum()
    )

    assert total == pytest.approx(51.0)
    assert detailed_daily_total == pytest.approx(total)


def test_auto_vmt_invalid_participant_codes_fall_back_to_one() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": ["AUTO_PASSENGER"] * 5,
                "od_dist": [5.0] * 5,
                "num_participants": [995.0, None, 0.0, -2.0, 4.0],
                "finalweight": [1.0] * 5,
            }
        )
    )

    result = validation.auto_vmt_totals(rd, None)

    assert result["auto_vmt"][0] == pytest.approx(21.25)


def test_auto_vmt_od_distance_does_not_count_full_drive_transit_trip() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": ["SOV", "KNR_TRANSIT", "PNR_TRANSIT"],
                "od_dist": [10.0, 50.0, 60.0],
                "num_participants": [1.0, 2.0, 1.0],
                "finalweight": [1.0, 1.0, 1.0],
            }
        )
    )

    result = validation.auto_vmt_totals(rd, None)

    assert result["auto_vmt"][0] == pytest.approx(10.0)


def test_auto_vmt_preserves_person_level_joint_rows_and_applies_mode_occupancy() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": ["HOV2", "HOV2", "HOV3", "HOV3", "HOV3"],
                "tour_category": ["joint"] * 5,
                "joint_trip_id": [10, 10, 20, 20, 20],
                "od_dist": [10.0, 10.0, 9.99, 9.99, 9.99],
                "num_participants": [1.0] * 5,
                "finalweight": [1.0] * 5,
            }
        )
    )

    result = validation.auto_vmt_totals(rd, None)

    assert result["auto_vmt"][0] == pytest.approx(19.0)


def test_non_motorized_vmt_summary_prefers_skimjoin_distances() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "household_id": [1, 1, 1, 1],
                "trip_mode": ["WALK", "BIKE", "EBIKE", "SOV"],
                "skim_walk_distance": [1.0, None, None, None],
                "skim_bike_distance": [None, 2.0, None, None],
                "prepared_non_motorized_distance": [9.0, 9.0, 3.0, 99.0],
                "trip_period": ["AM", "AM", "PM", "AM"],
                "finalweight": [2.0, 3.0, 4.0, 1.0],
            }
        ),
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "income_segment": [2],
                "HHSIZE": [1],
            }
        ),
    )

    result = validation.non_motorized_vmt_by_home_geography_income_hhsize_time_period(
        rd,
        None,
    )
    all_geo = _all_geographies_rows(result)

    assert all_geo.select(
        "mode",
        "time_period",
        "non_motorized_vmt",
        "trip_count",
        "distance_source",
    ).to_dicts() == [
        {
            "mode": "BIKE",
            "time_period": "AM",
            "non_motorized_vmt": 6.0,
            "trip_count": 3.0,
            "distance_source": "skim_bike_distance",
        },
        {
            "mode": "BIKE",
            "time_period": "Daily",
            "non_motorized_vmt": 6.0,
            "trip_count": 3.0,
            "distance_source": "skim_bike_distance",
        },
        {
            "mode": "EBIKE",
            "time_period": "Daily",
            "non_motorized_vmt": 12.0,
            "trip_count": 4.0,
            "distance_source": "prepared_non_motorized_distance",
        },
        {
            "mode": "EBIKE",
            "time_period": "PM",
            "non_motorized_vmt": 12.0,
            "trip_count": 4.0,
            "distance_source": "prepared_non_motorized_distance",
        },
        {
            "mode": "WALK",
            "time_period": "AM",
            "non_motorized_vmt": 2.0,
            "trip_count": 2.0,
            "distance_source": "skim_walk_distance",
        },
        {
            "mode": "WALK",
            "time_period": "Daily",
            "non_motorized_vmt": 2.0,
            "trip_count": 2.0,
            "distance_source": "skim_walk_distance",
        },
    ]


def test_non_motorized_vmt_summary_returns_empty_without_distance() -> None:
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "trip_mode": ["WALK", "BIKE", "SOV"],
                "trip_period": ["AM", "AM", "AM"],
                "finalweight": [1.0, 1.0, 1.0],
            }
        )
    )

    result = validation.non_motorized_vmt_by_home_geography_income_hhsize_time_period(
        rd,
        None,
    )

    assert result.is_empty()
    assert result.columns == [
        "geography_type",
        "geography_id",
        "income_segment",
        "household_size",
        "time_period",
        "mode",
        "non_motorized_vmt",
        "trip_count",
        "distance_source",
        "time_period_source",
    ]
