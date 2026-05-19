"""Shared helper patterns for trip summaries."""

from __future__ import annotations

import polars as pl

from processor.tour_purpose import purpose_column

ALL_TOUR_PURPOSES = "all_tour_purposes"


def _trip_purpose_column(trips: pl.DataFrame) -> str:
    """Return the prepared trip purpose grouping column, or an empty string."""
    return purpose_column(trips)


def _weighted_group_sum(
    df: pl.DataFrame,
    group_cols: str | list[str],
    *,
    weight_col: str,
    output_col: str,
) -> pl.DataFrame:
    """Group rows and sum one weight column into one named output column."""
    return df.group_by(group_cols).agg(pl.col(weight_col).sum().alias(output_col))


def _all_tour_purpose_rollup(
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    """Aggregate a pre-grouped frame across all tour purposes."""
    return (
        df.group_by(group_cols)
        .agg(pl.col(value_col).sum().alias(value_col))
        .with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
    )


def _dense_zero_fill(
    *,
    bins_df: pl.DataFrame,
    groups_df: pl.DataFrame,
    counts_df: pl.DataFrame,
    join_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    """Cross-join bins with groups, then fill missing counts with zeros."""
    return (
        bins_df.join(groups_df, how="cross")
        .join(counts_df, on=join_cols, how="left")
        .with_columns(pl.col(value_col).fill_null(0.0))
    )


def _aggregate_counts_by_geography(
    df: pl.DataFrame,
    *,
    geography_type: str,
    geography_id_col: str,
) -> pl.DataFrame:
    """Aggregate weighted trip counts for one geography dimension."""
    return (
        df.group_by(geography_id_col)
        .agg(trip_count=pl.col("finalweight").sum())
        .rename({geography_id_col: "geography_id"})
        .with_columns(
            pl.lit(geography_type).alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
        .select("geography_type", "geography_id", "trip_count")
    )
