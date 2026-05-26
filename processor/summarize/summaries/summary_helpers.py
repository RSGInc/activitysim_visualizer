"""Shared helper patterns across summary modules."""

from __future__ import annotations

import polars as pl

from processor.tour_purpose import purpose_column

ALL_TOUR_PURPOSES = "all_tour_purposes"
ALL_PERSON_TYPES = "all_person_types"


def _summary_purpose_column(df: pl.DataFrame) -> str:
    """Return the prepared purpose grouping column, or an empty string."""
    return purpose_column(df)


def _weighted_group_sum(
    df: pl.DataFrame,
    group_cols: str | list[str],
    *,
    weight_col: str,
    output_col: str,
) -> pl.DataFrame:
    """Group rows and sum one weight column into one named output column."""
    return df.group_by(group_cols).agg(pl.col(weight_col).sum().alias(output_col))


def _all_purpose_rollup(
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    """Aggregate a pre-grouped frame across all purposes."""
    return (
        df.group_by(group_cols)
        .agg(pl.col(value_col).sum().alias(value_col))
        .with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
        .select(*group_cols, "tour_purpose", value_col)
    )


def _all_person_types_rollup(
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    """Aggregate a pre-grouped frame across all person types."""
    return (
        df.group_by(group_cols)
        .agg(pl.col(value_col).sum().alias(value_col))
        .with_columns(pl.lit(ALL_PERSON_TYPES).alias("person_type"))
        .select("person_type", *group_cols, value_col)
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
    value_col: str = "trip_count",
    weight_col: str = "finalweight",
) -> pl.DataFrame:
    """Aggregate weighted counts for one geography dimension."""
    return (
        df.group_by(geography_id_col)
        .agg(pl.col(weight_col).sum().alias(value_col))
        .rename({geography_id_col: "geography_id"})
        .with_columns(
            pl.lit(geography_type).alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col(value_col).cast(pl.Float64),
        )
        .select("geography_type", "geography_id", value_col)
    )


def _configured_geography_dimensions(
    df: pl.DataFrame,
    *,
    config,
    base_type: str,
    base_col: str,
    role_prefix: str,
) -> list[tuple[str, str]]:
    """Return available geography dimensions for one semantic role."""
    dimensions: list[tuple[str, str]] = []
    if base_col in df.columns:
        dimensions.append((base_type, base_col))
    for aggregation in config.geography_aggregations.aggregations:
        column = f"{role_prefix}_geo__{aggregation.name}"
        if column in df.columns:
            dimensions.append((aggregation.name, column))
    return dimensions


def _configured_geography_columns(
    df: pl.DataFrame,
    *,
    config,
    role_prefix: str,
) -> list[str]:
    """Return configured prepared geography columns present for one role."""
    return [
        column
        for _, column in _configured_geography_dimensions(
            df,
            config=config,
            base_type="",
            base_col="",
            role_prefix=role_prefix,
        )
        if column
    ]


def _configured_land_use_geography_dimensions(
    df: pl.DataFrame,
    *,
    config,
) -> list[tuple[str, str]]:
    """Return available geography dimensions for prepared land use."""
    base_dimensions: list[tuple[str, str]] = []
    base_col = "MAZ" if config.use_maz else "TAZ"
    base_type = "maz" if config.use_maz else "taz"
    if base_col in df.columns:
        base_dimensions.append((base_type, base_col))
    for aggregation in config.geography_aggregations.aggregations:
        column = f"land_use_geo__{aggregation.name}"
        if column in df.columns:
            base_dimensions.append((aggregation.name, column))
    return base_dimensions


def _aggregate_counts_across_geographies(
    df: pl.DataFrame,
    *,
    geography_dimensions: list[tuple[str, str]],
    value_col: str = "trip_count",
    weight_col: str = "finalweight",
) -> pl.DataFrame:
    """Aggregate one frame across multiple geography dimensions."""
    outputs = [
        _aggregate_counts_by_geography(
            df.filter(pl.col(column).is_not_null()),
            geography_type=geography_type,
            geography_id_col=column,
            value_col=value_col,
            weight_col=weight_col,
        )
        for geography_type, column in geography_dimensions
        if column in df.columns
    ]
    if not outputs:
        return pl.DataFrame(
            schema={
                "geography_type": pl.Utf8,
                "geography_id": pl.Utf8,
                value_col: pl.Float64,
            }
        )
    return pl.concat(outputs, how="vertical")


def _aggregate_weighted_average_across_geographies(
    df: pl.DataFrame,
    *,
    geography_dimensions: list[tuple[str, str]],
    value_col: str,
    output_col: str,
    weight_col: str = "finalweight",
    group_cols: list[str] | None = None,
    count_col: str | None = None,
) -> pl.DataFrame:
    """Aggregate weighted averages across multiple geography dimensions."""
    group_cols = list(group_cols or [])
    outputs: list[pl.DataFrame] = []
    for geography_type, column in geography_dimensions:
        if column not in df.columns:
            continue
        group_by_cols = [column, *group_cols]
        agg_exprs = [
            (
                (pl.col(value_col) * pl.col(weight_col)).sum()
                / pl.col(weight_col).sum()
            ).alias(output_col)
        ]
        if count_col is not None:
            agg_exprs.append(pl.col(weight_col).sum().alias(count_col))
        outputs.append(
            df.filter(pl.col(column).is_not_null())
            .group_by(group_by_cols)
            .agg(*agg_exprs)
            .rename({column: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col(output_col).cast(pl.Float64),
                *(
                    [pl.col(count_col).cast(pl.Float64)]
                    if count_col is not None
                    else []
                ),
            )
            .select(
                "geography_type",
                "geography_id",
                *group_cols,
                output_col,
                *([count_col] if count_col is not None else []),
            )
        )
    if not outputs:
        schema: dict[str, pl.DataType] = {
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            output_col: pl.Float64,
        }
        for column in group_cols:
            schema[column] = pl.Utf8
        if count_col is not None:
            schema[count_col] = pl.Float64
        return pl.DataFrame(schema=schema)
    return pl.concat(outputs, how="vertical")


def _rounded_distance_bin_expr(distance_col: str) -> pl.Expr:
    """Return the common 0-decimal distance bin label expression with 40+ cap."""
    rounded = pl.col(distance_col).cast(pl.Float64).round(0)
    return (
        pl.when(rounded >= 40)
        .then(pl.lit("40+"))
        .otherwise(rounded.cast(pl.Int64, strict=False).cast(pl.Utf8))
        .alias("distance_bin")
    )


def _trip_direction_expr(df: pl.DataFrame) -> pl.Expr | None:
    """Infer a standard outbound/inbound direction label from trip flags."""
    if "inbound" in df.columns:
        return (
            pl.when(
                pl.col("inbound").cast(pl.Utf8).str.to_lowercase().is_in(["1", "true"])
            )
            .then(pl.lit("inbound"))
            .otherwise(pl.lit("outbound"))
            .alias("direction")
        )
    if "outbound" in df.columns:
        return (
            pl.when(
                pl.col("outbound")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["false", "0"])
            )
            .then(pl.lit("inbound"))
            .otherwise(pl.lit("outbound"))
            .alias("direction")
        )
    return None
