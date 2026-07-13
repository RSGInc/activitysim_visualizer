"""Chart-ready queries for the escorted-tours dashboard page."""

from __future__ import annotations

import polars as pl

from dashboard.data_access import RunTableView
from dashboard.helpers.category_helpers import (
    capped_numeric_category_expr,
    capped_numeric_category_values,
    numeric_like_sort_expr,
    ordered_category_values,
)

DIRECTION_COL = "direction"
DISTANCE_BINS = [str(i) for i in range(40)] + ["40+"]


def direction_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    directions = ordered_category_values(data_list, DIRECTION_COL)
    if not directions:
        return ["Both Directions"]
    return [
        "Both Directions",
        *(["Outbound"] if "outbound" in directions else []),
        *(["Inbound"] if "inbound" in directions else []),
    ]


def adult_raw_direction(value: str) -> str:
    return {
        "Both Directions": "both",
        "Outbound": "outbound",
        "Inbound": "inbound",
    }.get(value, "both")


def default_direction_option(options: list[str]) -> str:
    return "Outbound" if "Outbound" in options else (options[0] if options else "Both Directions")


def adult_escort_event_stop_chart_data(data_list, segment: str):
    return (
        RunTableView.from_runs(data_list)
        .with_columns(pl.col("segment").cast(pl.Utf8))
        .where(segment=segment)
        .with_columns(capped_numeric_category_expr("stop_count", 3))
        .group("stop_count", pl.col("tour_count").sum().alias("tour_count"))
        .select("stop_count", "tour_count")
        .sort(numeric_like_sort_expr("stop_count"))
        .collect()
    )


def escort_person_type_chart_data(data_list, direction: str):
    return (
        RunTableView.from_runs(data_list)
        .with_columns(
            pl.col(DIRECTION_COL).cast(pl.Utf8),
            pl.col("person_type").cast(pl.Utf8),
        )
        .where(direction=direction)
        .select("person_type", "tour_count")
        .collect()
    )


def escort_distance_chart_data(data_list, direction: str, *, y_col: str):
    bins = pl.DataFrame(
        {"distance_bin": DISTANCE_BINS},
        schema={"distance_bin": pl.Utf8},
    )
    return (
        RunTableView.from_runs(data_list)
        .with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
        .where(direction=direction)
        .select(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col(y_col).cast(pl.Float64).alias("freq"),
        )
        .map(
            lambda filtered: bins.join(filtered, on="distance_bin", how="left")
            .with_columns(pl.col("freq").fill_null(0.0))
            .select("distance_bin", "freq")
        )
        .collect()
    )


def student_school_escort_chart_data(data_list, direction: str):
    return (
        RunTableView.from_runs(data_list)
        .with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
        .where(direction=direction)
        .select("escort_type", "tour_count")
        .collect()
    )


def household_school_escort_chart_data(numerator, denominator, direction: str):
    totals = (
        RunTableView.from_runs(denominator)
        .with_columns(capped_numeric_category_expr("student_count", 6))
        .group(
            "student_count",
            pl.col("household_count").cast(pl.Float64).sum().alias("total_household_count"),
        )
    )
    escorted = (
        RunTableView.from_runs(numerator)
        .with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
        .where(direction=direction)
        .with_columns(capped_numeric_category_expr("student_count", 6))
        .group(
            "student_count",
            pl.col("household_count").cast(pl.Float64).sum().alias("household_count"),
        )
    )
    return (
        totals.join(escorted, on="student_count")
        .with_columns(
            pl.col("household_count").fill_null(0.0),
            pl.when(pl.col("total_household_count") > 0)
            .then(pl.col("household_count") / pl.col("total_household_count") * 100.0)
            .otherwise(0.0)
            .alias("pct"),
        )
        .select("student_count", "household_count", "pct")
        .collect()
    )


def schoolkids_per_escorted_tour_chart_data(data_list, direction: str):
    return (
        RunTableView.from_runs(data_list)
        .with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
        .where(direction=direction)
        .with_columns(
            capped_numeric_category_expr("student_count", 6),
            pl.col("avg_schoolkids_per_tour").cast(pl.Float64),
            pl.col("tour_count").cast(pl.Float64),
        )
        .with_columns(
            (pl.col("avg_schoolkids_per_tour") * pl.col("tour_count")).alias(
                "_weighted_schoolkids"
            )
        )
        .group(
            "student_count",
            pl.col("_weighted_schoolkids").sum(),
            pl.col("tour_count").sum(),
        )
        .with_columns(
            pl.when(pl.col("tour_count") > 0)
            .then(pl.col("_weighted_schoolkids") / pl.col("tour_count"))
            .otherwise(0.0)
            .alias("avg_schoolkids_per_tour")
        )
        .select("student_count", "avg_schoolkids_per_tour", "tour_count")
        .sort(numeric_like_sort_expr("student_count"))
        .collect()
    )


def student_count_category_values(data_list) -> list[str]:
    return capped_numeric_category_values(data_list, "student_count", cap_value=6)


def stop_count_category_values(data_list) -> list[str]:
    return capped_numeric_category_values(data_list, "stop_count", cap_value=3)
