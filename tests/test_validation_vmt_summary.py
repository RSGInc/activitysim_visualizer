from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

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
