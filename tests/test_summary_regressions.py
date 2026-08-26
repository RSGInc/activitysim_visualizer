from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from processor.models import RunData
from processor.summarize.summaries.daily_travel_activity import (
    dap_summary,
    mandatory_tour_freq,
    tour_rate_per_person,
    trip_rate_per_person,
)
from processor.summarize.summaries.demographics import hh_size, person_type
from processor.summarize.summaries.long_term_geography import free_parking
from processor.summarize.summaries.validation import screenline_flow_comparisons


def _run(
    *,
    hh: pl.DataFrame | None = None,
    per: pl.DataFrame | None = None,
    day: pl.DataFrame | None = None,
    tours: pl.DataFrame | None = None,
    trips: pl.DataFrame | None = None,
) -> RunData:
    return RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=hh if hh is not None else pl.DataFrame(),
        per=per if per is not None else pl.DataFrame(),
        day=day if day is not None else pl.DataFrame(),
        tours=tours if tours is not None else pl.DataFrame(),
        trips=trips if trips is not None else pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_dap_summary_uses_person_day_activity_patterns_when_available() -> None:
    result = dap_summary(
        _run(
            per=pl.DataFrame(
                {
                    "person_id": [1, 2],
                    "person_type": ["1", "2"],
                    "finalweight": [10.0, 20.0],
                }
            ),
            day=pl.DataFrame(
                {
                    "person_id": [1, 1, 2],
                    "cdap_activity": ["M", "N", "H"],
                    "finalweight": [1.0, 2.0, 3.0],
                }
            ),
        ),
        _config(),
    )

    assert result.to_dicts() == [
        {"person_type": "1", "daily_activity_pattern": "M", "person_count": 10.0},
        {"person_type": "1", "daily_activity_pattern": "N", "person_count": 10.0},
        {"person_type": "2", "daily_activity_pattern": "H", "person_count": 20.0},
        {
            "person_type": "all_person_types",
            "daily_activity_pattern": "H",
            "person_count": 20.0,
        },
        {
            "person_type": "all_person_types",
            "daily_activity_pattern": "M",
            "person_count": 10.0,
        },
        {
            "person_type": "all_person_types",
            "daily_activity_pattern": "N",
            "person_count": 10.0,
        },
    ]


def test_dap_summary_falls_back_to_person_activity_patterns() -> None:
    result = dap_summary(
        _run(
            per=pl.DataFrame(
                {
                    "person_type": ["1", "2"],
                    "cdap_activity": ["M", "N"],
                    "finalweight": [1.0, 2.0],
                }
            )
        ),
        _config(),
    )

    assert result.filter(pl.col("person_type") != "all_person_types").to_dicts() == [
        {"person_type": "1", "daily_activity_pattern": "M", "person_count": 1.0},
        {"person_type": "2", "daily_activity_pattern": "N", "person_count": 2.0},
    ]


def test_dap_summary_prefers_person_activity_patterns_when_both_exist() -> None:
    result = dap_summary(
        _run(
            per=pl.DataFrame(
                {
                    "person_id": [1],
                    "person_type": ["1"],
                    "cdap_activity": ["M"],
                    "finalweight": [2.0],
                }
            ),
            day=pl.DataFrame(
                {
                    "person_id": [1],
                    "cdap_activity": ["N"],
                }
            ),
        ),
        _config(),
    )

    assert result.filter(pl.col("person_type") != "all_person_types").to_dicts() == [
        {"person_type": "1", "daily_activity_pattern": "M", "person_count": 2.0}
    ]


def test_mandatory_tour_frequency_falls_back_to_person_day_tour_counts() -> None:
    result = mandatory_tour_freq(
        _run(
            per=pl.DataFrame(
                {
                    "person_id": [1, 2],
                    "person_type": ["1", "2"],
                    "finalweight": [0.5, 2.0],
                }
            ),
            day=pl.DataFrame(
                {
                    "person_id": [1, 1, 2],
                    "day_id": [11, 12, 21],
                }
            ),
            tours=pl.DataFrame(
                {
                    "person_id": [1, 1, 2, 2],
                    "day_id": [11, 12, 21, 21],
                    "tour_purpose": ["work", "school", "work", "work"],
                    "tour_category": ["mandatory"] * 4,
                }
            ),
        ),
        _config(),
    )

    assert result.filter(pl.col("person_type") != "all_person_types").to_dicts() == [
        {"person_type": "1", "mandatory_tour_frequency": 1, "person_count": 0.5},
        {"person_type": "1", "mandatory_tour_frequency": 3, "person_count": 0.5},
        {"person_type": "2", "mandatory_tour_frequency": 2, "person_count": 2.0},
    ]


def test_daily_rates_sum_every_activity_weight_and_retain_person_day_rows() -> None:
    run = _run(
        per=pl.DataFrame(
            {
                "person_id": [1, 2],
                "person_type": ["1", "2"],
                "finalweight": [2.0, 3.0],
            }
        ),
        day=pl.DataFrame(
            {
                "person_id": [1, 1, 2],
                "day_id": [11, 12, 21],
            }
        ),
        tours=pl.DataFrame(
            {
                "person_id": [1, 1, 2],
                "tour_purpose": ["work", "work", "work"],
                "finalweight": [2.0, 4.0, 3.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "person_id": [1, 1, 1, 2],
                "trip_purpose": ["work", "work", "work", "work"],
                "finalweight": [1.0, 2.0, 3.0, 6.0],
            }
        ),
    )

    tour_result = tour_rate_per_person(run, _config())
    trip_result = trip_rate_per_person(run, _config())

    assert tour_result.filter(pl.col("person_type") == "all_person_types").to_dicts() == [
        {"person_type": "all_person_types", "tour_purpose": "work", "tour_rate": 9 / 7}
    ]
    assert trip_result.filter(pl.col("person_type") == "all_person_types").to_dicts() == [
        {"person_type": "all_person_types", "trip_purpose": "work", "trip_rate": 12 / 7}
    ]


def _config():
    return SimpleNamespace(
        use_maz=False,
        geography_aggregations=SimpleNamespace(aggregations=()),
        person_type_label=lambda value: {"1": "Full-Time Worker"}.get(
            str(value), str(value)
        ),
    )


def test_screenline_comparison_uses_available_facility_type() -> None:
    run = _run()
    run.observed_screenline_flows = pl.DataFrame(
        {
            "screenline_id": ["A"],
            "direction": ["NB"],
            "count_period": ["AM"],
            "volume": [100.0],
        }
    )
    run.visum_screenline_flows = pl.DataFrame(
        {
            "screenline_id": ["A"],
            "direction": ["NB"],
            "count_period": ["AM"],
            "facility_type": [3],
            "volume": [110.0],
        }
    )

    assert screenline_flow_comparisons(run, None).to_dicts() == [
        {
            "screenline_id": "A",
            "direction": "NB",
            "count_period": "AM",
            "facility_type": "3",
            "observed_volume": 100.0,
            "modeled_volume": 110.0,
        }
    ]


def test_household_size_summary_normalizes_integer_width_to_contract() -> None:
    result = hh_size(
        _run(
            hh=pl.DataFrame(
                {
                    "HHSIZE": pl.Series([1, 2, 2], dtype=pl.Int32),
                    "finalweight": [1.0, 2.0, 3.0],
                }
            )
        )
    )

    assert result.schema == {
        "household_size": pl.Int64,
        "household_count": pl.Float64,
    }
    assert result.to_dicts() == [
        {"household_size": 1, "household_count": 1.0},
        {"household_size": 2, "household_count": 5.0},
    ]


def test_person_type_summary_returns_declared_column_order() -> None:
    result = person_type(
        _run(
            per=pl.DataFrame(
                {
                    "person_type": [1, 1],
                    "finalweight": [1.0, 2.0],
                }
            )
        ),
        _config(),
    )

    assert result.columns == ["person_type", "person_type_label", "person_count"]
    assert result.to_dicts() == [
        {
            "person_type": "1",
            "person_type_label": "Full-Time Worker",
            "person_count": 3.0,
        }
    ]


def test_free_parking_summary_accepts_boolean_model_output() -> None:
    result = free_parking(
        _run(
            per=pl.DataFrame(
                {
                    "is_worker": [True, True, True],
                    "free_parking_at_work": [False, True, False],
                    "workplace_zone_id": [10, 10, 20],
                    "finalweight": [1.0, 2.0, 3.0],
                }
            )
        ),
        _config(),
    )

    assert result.to_dicts() == [
        {
            "geography_type": "taz",
            "geography_id": "10",
            "workers_without_free_parking_count": 1.0,
            "workers_with_free_parking_count": 2.0,
        },
        {
            "geography_type": "taz",
            "geography_id": "20",
            "workers_without_free_parking_count": 3.0,
            "workers_with_free_parking_count": 0.0,
        },
    ]


def test_free_parking_summary_accepts_estimation_alternative_codes() -> None:
    result = free_parking(
        _run(
            per=pl.DataFrame(
                {
                    "is_worker": [True, True, True],
                    "free_parking_at_work": [0, 1, 2],
                    "workplace_zone_id": [10, 10, 10],
                    "finalweight": [1.0, 2.0, 3.0],
                }
            )
        ),
        _config(),
    )

    assert result.schema == {
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "workers_without_free_parking_count": pl.Float64,
        "workers_with_free_parking_count": pl.Float64,
    }
    assert result.to_dicts() == [
        {
            "geography_type": "taz",
            "geography_id": "10",
            "workers_without_free_parking_count": 3.0,
            "workers_with_free_parking_count": 3.0,
        }
    ]
