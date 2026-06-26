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
        ["income_segment", "household_size", "time_period"]
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
            "auto_vmt": 15.0,
            "trip_count": 2.0,
            "distance_source": "skim_auto_distance",
            "time_period_source": "trip_period",
        }
    ]
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
            "time_period": "MD",
            "auto_vmt": 13.0,
            "trip_count": 2.0,
            "distance_source": "od_dist",
            "time_period_source": "trip_period",
        }
    ]


def test_auto_vmt_segment_summary_derives_time_period_from_network_los(
    tmp_path: Path,
) -> None:
    network_los = tmp_path / "network_los.yaml"
    network_los.write_text(
        "\n".join(
            [
                "skim_time_periods:",
                "  periods:",
                "    - 0",
                "    - 6",
                "    - 12",
                "  labels:",
                "    - EA",
                "    - AM",
            ]
        ),
        encoding="utf-8",
    )
    rd = _run_data(
        trips=pl.DataFrame(
            {
                "household_id": [1, 1],
                "trip_mode": ["SOV", "SOV"],
                "od_dist": [10.0, 20.0],
                "depart_hour": [1, 7],
                "num_participants": [1, 1],
                "finalweight": [1.0, 1.0],
            }
        ),
        hh=pl.DataFrame({"household_id": [1], "income_segment": [1], "HHSIZE": [1]}),
        skimjoin_manifest={
            "skimjoin_resolved_network_los_file": str(network_los),
        },
    )

    result = _all_geographies_rows(
        validation.auto_vmt_by_home_geography_income_hhsize_time_period(rd, None)
    )

    assert result.select("time_period", "auto_vmt", "time_period_source").to_dicts() == [
        {"time_period": "AM", "auto_vmt": 20.0, "time_period_source": "network_los"},
        {"time_period": "EA", "auto_vmt": 10.0, "time_period_source": "network_los"},
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
            "auto_vmt": 14.0,
            "trip_count": 2.0,
            "distance_source": "od_dist",
            "time_period_source": "daily",
        }
    ]
