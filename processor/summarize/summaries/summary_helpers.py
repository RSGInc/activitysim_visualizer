"""Shared helper patterns across summary modules."""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from processor.tour_purpose import purpose_column

ALL_TOUR_PURPOSES = "all_tour_purposes"
ALL_PERSON_TYPES = "all_person_types"
MAX_RESIDUAL_HISTOGRAM_BINS = 200


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


def _first_existing_column(columns: list[str], candidates: list[str]) -> str | None:
    candidate_set = set(columns)
    for candidate in candidates:
        if candidate in candidate_set:
            return candidate
    return None


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
    """Return available native and configured geography dimensions for one role."""
    dimensions: list[tuple[str, str]] = []
    seen_columns: set[str] = set()

    def _append(geography_type: str, column: str) -> None:
        if column and column in df.columns and column not in seen_columns:
            dimensions.append((geography_type, column))
            seen_columns.add(column)

    if base_col in df.columns:
        _append(base_type, base_col)
    if role_prefix == "home":
        for geography_type, column in [
            ("home_taz", "home_taz"),
            ("home_county", "home_county"),
            ("home_mpo", "home_mpo"),
        ]:
            _append(geography_type, column)
    geography_aggregations = getattr(
        getattr(config, "geography_aggregations", None),
        "aggregations",
        (),
    )
    for aggregation in geography_aggregations:
        column = f"{role_prefix}_geo__{aggregation.name}"
        _append(aggregation.name, column)
    return dimensions


def _configured_geography_columns(
    df: pl.DataFrame,
    *,
    config,
    role_prefix: str,
) -> list[str]:
    """Return native and configured prepared geography columns present for one role."""
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


def _residual_metrics_columns(
    target_col: str,
    modeled_col: str,
    *,
    target_output_col: str = "target_count",
    modeled_output_col: str = "modeled_count",
) -> list[pl.Expr]:
    residual = pl.col(modeled_col) - pl.col(target_col)
    return [
        pl.col(target_col).cast(pl.Float64).alias(target_output_col),
        pl.col(modeled_col).cast(pl.Float64).alias(modeled_output_col),
        residual.cast(pl.Float64).alias("residual_count"),
        residual.abs().cast(pl.Float64).alias("absolute_residual_count"),
        pl.when(pl.col(target_col) > 0)
        .then((residual / pl.col(target_col)) * 100.0)
        .otherwise(None)
        .cast(pl.Float64)
        .alias("percent_error"),
    ]


def _finalize_residual_frame(
    df: pl.DataFrame,
    *,
    target_output_col: str = "target_count",
    modeled_output_col: str = "modeled_count",
    group_cols: list[str] | None = None,
) -> pl.DataFrame:
    ordered_cols = ["geography_type", "geography_id"]
    if group_cols:
        ordered_cols.extend(group_cols)
    ordered_cols.extend(
        [
            target_output_col,
            modeled_output_col,
            "residual_count",
            "absolute_residual_count",
            "percent_error",
        ]
    )
    cast_exprs = [
        pl.col("geography_type").cast(pl.Utf8),
        pl.col("geography_id").cast(pl.Utf8),
        pl.col(target_output_col).cast(pl.Float64),
        pl.col(modeled_output_col).cast(pl.Float64),
        pl.col("residual_count").cast(pl.Float64),
        pl.col("absolute_residual_count").cast(pl.Float64),
        pl.col("percent_error").cast(pl.Float64),
    ]
    if group_cols:
        cast_exprs.extend(pl.col(column).cast(pl.Utf8) for column in group_cols)
    return df.with_columns(cast_exprs).select(ordered_cols)


def _dynamic_count_bin_edges(values: list[float]) -> np.ndarray:
    finite = np.array([value for value in values if math.isfinite(value)], dtype=float)
    if finite.size == 0:
        return np.array([-1.0, 1.0], dtype=float)
    if finite.size == 1 or math.isclose(float(finite.min()), float(finite.max())):
        center = float(finite[0])
        width = max(1.0, abs(center) * 0.25)
        return np.array([center - width, center + width], dtype=float)
    edges = np.histogram_bin_edges(finite, bins="fd")
    if edges.size < 2 or np.allclose(edges[0], edges[-1]):
        lower = float(finite.min())
        upper = float(finite.max())
        if math.isclose(lower, upper):
            width = max(1.0, abs(lower) * 0.25)
            return np.array([lower - width, lower + width], dtype=float)
        return np.linspace(lower, upper, num=7, dtype=float)
    max_edges = MAX_RESIDUAL_HISTOGRAM_BINS + 1
    if edges.size > max_edges:
        return np.linspace(
            float(finite.min()),
            float(finite.max()),
            num=max_edges,
            dtype=float,
        )
    return edges.astype(float)


def _residual_histogram_summary(
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    valid = df.select(
        *group_cols,
        pl.col(value_col).cast(pl.Float64).alias(value_col),
    ).filter(pl.col(value_col).is_not_null())
    if valid.is_empty():
        return pl.DataFrame(
            schema={
                **{column: pl.Utf8 for column in group_cols},
                "bin_start": pl.Float64,
                "bin_end": pl.Float64,
                "geography_count": pl.Float64,
            }
        )
    rows: list[dict[str, object]] = []
    for group_df in valid.partition_by(group_cols, as_dict=False, maintain_order=True):
        key = {column: group_df[column][0] for column in group_cols}
        values = np.array(group_df[value_col].to_list(), dtype=float)
        zero_mask = np.isclose(values, 0.0)
        zero_count = float(zero_mask.sum())
        nonzero_values = values[~zero_mask]
        if zero_count > 0:
            rows.append(
                {
                    **key,
                    "bin_start": 0.0,
                    "bin_end": 0.0,
                    "geography_count": zero_count,
                }
            )
        if nonzero_values.size == 0:
            continue
        edges = _dynamic_count_bin_edges(nonzero_values.tolist())
        counts, bin_edges = np.histogram(nonzero_values, bins=edges)
        for index, geography_count in enumerate(counts.tolist()):
            rows.append(
                {
                    **key,
                    "bin_start": float(bin_edges[index]),
                    "bin_end": float(bin_edges[index + 1]),
                    "geography_count": float(geography_count),
                }
            )
    return pl.DataFrame(rows).with_columns(
        *[pl.col(column).cast(pl.Utf8) for column in group_cols],
        pl.col("bin_start").cast(pl.Float64),
        pl.col("bin_end").cast(pl.Float64),
        pl.col("geography_count").cast(pl.Float64),
    )


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
