"""Chart-ready queries for the joint-travel dashboard page."""

from __future__ import annotations

import polars as pl

from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    add_percent_of_total,
    cap_numeric_category_data,
    capped_numeric_category_expr,
    complete_category_counts,
    nonempty,
    numeric_like_sort_expr,
)

PARTY_SIZE_ALL_LABEL = "All Party Sizes"
HOUSEHOLD_SIZE_ALL_LABEL = "All"
JOINT_SIZE_VALUES = ["2", "3", "4", "5+"]


def party_size_options(data_list) -> list[str]:
    return [PARTY_SIZE_ALL_LABEL, *JOINT_SIZE_VALUES] if nonempty(data_list) else [PARTY_SIZE_ALL_LABEL]


def household_size_options(data_list) -> list[str]:
    return [HOUSEHOLD_SIZE_ALL_LABEL, *JOINT_SIZE_VALUES] if nonempty(data_list) else [HOUSEHOLD_SIZE_ALL_LABEL]


def joint_household_size_values(*data_lists) -> list[str]:
    return JOINT_SIZE_VALUES.copy() if any(nonempty(data) for data in data_lists) else []


def complete_joint_household_size_data(
    data_list,
    *,
    value_col: str,
    household_size_values: list[str],
):
    normalized = [
        (
            label,
            cap_numeric_category_data(
                [
                    (
                        label,
                        frame.filter(
                            pl.col("household_size").cast(pl.Int64, strict=False) >= 2
                        ),
                    )
                ],
                category="household_size",
                cap_value=5,
                value_cols=(value_col,),
            )[0][1].select("household_size", value_col),
        )
        for label, frame in nonempty(data_list)
    ]
    return complete_category_counts(
        normalized,
        category="household_size",
        category_values=household_size_values,
        value_cols=(value_col,),
    )


def joint_party_size_data(data_list):
    """Return the standard capped party-size distribution."""
    return cap_numeric_category_data(
        data_list,
        category="party_size",
        cap_value=5,
        value_cols=("joint_tour_count",),
    )


def _ordered_composition(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "tour_composition" not in frame.columns:
        return frame
    return (
        frame.with_columns(
            pl.col("tour_composition")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .alias("tour_composition")
        )
        .with_columns(
            pl.when(pl.col("tour_composition") == "adults")
            .then(0)
            .when(pl.col("tour_composition") == "mixed")
            .then(1)
            .when(pl.col("tour_composition") == "children")
            .then(2)
            .otherwise(99)
            .alias("_ord")
        )
        .sort("_ord")
        .drop("_ord")
    )


def composition_by_party_size_data(data_list, party_size: str):
    view = RunTables.from_runs(data_list).with_columns(
        capped_numeric_category_expr("party_size", 5)
    )
    if party_size != PARTY_SIZE_ALL_LABEL:
        view = view.where(party_size=party_size)
    return (
        view.group(
            "tour_composition",
            pl.col("joint_tour_count").sum().alias("joint_tour_count"),
        )
        .with_columns(pl.col("tour_composition").cast(pl.Utf8))
        .map(_ordered_composition)
    )


def household_participation_data(data_list, household_size: str):
    view = RunTables.from_runs(data_list).with_columns(
        capped_numeric_category_expr("household_size", 5),
        pl.col("jtf").cast(pl.Utf8),
    )
    if household_size != HOUSEHOLD_SIZE_ALL_LABEL:
        view = view.where(household_size=household_size)
    return (
        view.group(
            "jtf",
            pl.col("household_percent").mean().alias("household_percent"),
        )
        .sort("jtf")
    )


def person_participation_data(data_list, *, as_percent: bool):
    view = (
        RunTables.from_runs(data_list)
        .with_columns(capped_numeric_category_expr("household_size", 5))
        .group(
            "household_size",
            pl.col("joint_tour_person_count").sum(),
            pl.col("total_person_count").sum(),
        )
        .sort(numeric_like_sort_expr("household_size"))
    )
    if as_percent:
        view = view.with_columns(
            pl.when(pl.col("total_person_count") > 0)
            .then(pl.col("joint_tour_person_count") / pl.col("total_person_count") * 100.0)
            .otherwise(0.0)
            .alias("person_value")
        )
    else:
        view = view.with_columns(
            pl.col("joint_tour_person_count").alias("person_value")
        )
    return view


def joint_tour_frequency_data(data_list, *, hide_no_joint_tours: bool):
    def transform(frame: pl.DataFrame) -> pl.DataFrame:
        result = frame.with_columns(pl.col("jtf_label").cast(pl.Utf8))
        result = add_percent_of_total(
            [("run", result)],
            value_col="household_count",
            percent_col="household_count_percent",
        )[0][1]
        if hide_no_joint_tours:
            result = result.filter(
                pl.col("jtf_label").str.strip_chars().str.to_lowercase()
                != "no joint tours"
            )
        return result

    return RunTables.from_runs(data_list).map(transform)
