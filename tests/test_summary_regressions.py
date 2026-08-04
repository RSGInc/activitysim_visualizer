from __future__ import annotations

from types import SimpleNamespace

import polars as pl

from processor.models import RunData
from processor.summarize.summaries.demographics import hh_size, person_type
from processor.summarize.summaries.long_term_geography import free_parking
from processor.summarize.summaries.validation import screenline_flow_comparisons


def _run(
    *,
    hh: pl.DataFrame | None = None,
    per: pl.DataFrame | None = None,
) -> RunData:
    return RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=hh if hh is not None else pl.DataFrame(),
        per=per if per is not None else pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


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
