from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.summarize.summaries.summary_helpers import (
    ALL_PERSON_TYPES,
    ALL_TOUR_PURPOSES,
    _all_person_types_rollup,
    _all_purpose_rollup,
    _distance_bin_expr,
    _distance_bin_sort_expr,
)


def test_all_purpose_rollup_preserves_concat_compatible_column_order() -> None:
    by_purpose = pl.DataFrame(
        {
            "distance_bin": ["1", "1", "2"],
            "tour_purpose": ["work", "school", "work"],
            "tour_count": [2.0, 3.0, 4.0],
        }
    )

    total = _all_purpose_rollup(
        by_purpose,
        group_cols=["distance_bin"],
        value_col="tour_count",
    )

    assert total.columns == ["distance_bin", "tour_purpose", "tour_count"]

    combined = pl.concat([by_purpose, total], how="vertical")

    assert (
        combined.filter(pl.col("tour_purpose") == ALL_TOUR_PURPOSES)
        .sort("distance_bin")
        .to_dict(as_series=False)
    ) == {
        "distance_bin": ["1", "2"],
        "tour_purpose": [ALL_TOUR_PURPOSES, ALL_TOUR_PURPOSES],
        "tour_count": [5.0, 4.0],
    }


def test_all_person_types_rollup_preserves_concat_compatible_column_order() -> None:
    by_person_type = pl.DataFrame(
        {
            "person_type": ["worker", "student", "worker"],
            "mandatory_tour_frequency": [1, 1, 2],
            "person_count": [2.0, 3.0, 4.0],
        }
    )

    total = _all_person_types_rollup(
        by_person_type,
        group_cols=["mandatory_tour_frequency"],
        value_col="person_count",
    )

    assert total.columns == [
        "person_type",
        "mandatory_tour_frequency",
        "person_count",
    ]

    combined = pl.concat([by_person_type, total], how="vertical")

    assert (
        combined.filter(pl.col("person_type") == ALL_PERSON_TYPES)
        .sort("mandatory_tour_frequency")
        .to_dict(as_series=False)
    ) == {
        "person_type": [ALL_PERSON_TYPES, ALL_PERSON_TYPES],
        "mandatory_tour_frequency": [1, 2],
        "person_count": [5.0, 4.0],
    }


def test_distance_bins_separate_exact_zero_from_positive_submile_values() -> None:
    result = (
        pl.DataFrame(
            {"distance": [None, -1.0, 0.0, 0.25, 0.99, 1.0, 1.99, 39.99, 40.0]}
        )
        .with_columns(_distance_bin_expr("distance"))
        .with_columns(_distance_bin_sort_expr().alias("_sort_distance"))
    )

    assert result["distance_bin"].to_list() == [
        None,
        None,
        "0",
        ">0-<1",
        ">0-<1",
        "1",
        "1",
        "39",
        "40+",
    ]
    assert result["_sort_distance"].to_list() == [
        float("inf"),
        float("inf"),
        0.0,
        0.5,
        0.5,
        1.0,
        1.0,
        39.0,
        40.0,
    ]
