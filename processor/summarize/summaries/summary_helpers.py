"""Shared helper patterns across summary modules."""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from processor.models import RunData
from processor.tour_purpose import purpose_column

ALL_TOUR_PURPOSES = "all_tour_purposes"
ALL_PERSON_TYPES = "all_person_types"
MAX_RESIDUAL_HISTOGRAM_BINS = 200


def _summary_purpose_column(df: pl.DataFrame) -> str:
    """Return the prepared purpose grouping column, or an empty string."""
    return purpose_column(df)


def weighted_group_sum(
    df: pl.DataFrame,
    group_cols: str | list[str],
    *,
    weight_col: str,
    output_col: str,
) -> pl.DataFrame:
    """Group rows and sum one weight column into one named output column."""
    return df.group_by(group_cols).agg(pl.col(weight_col).sum().alias(output_col))


def joint_participant_weight_expr(
    df: pl.DataFrame,
    *,
    participant_col: str,
    output_col: str,
    weight_col: str = "finalweight",
    category_col: str = "tour_category",
) -> pl.Expr:
    """Return person-level weight, expanding valid joint-party records only."""
    weight = pl.col(weight_col).cast(pl.Float64)
    if category_col not in df.columns or participant_col not in df.columns:
        return weight.alias(output_col)

    participant_count = pl.col(participant_col).cast(pl.Float64, strict=False)
    valid_participant_count = (
        participant_count.is_not_null()
        & (participant_count > 0)
        & (participant_count < 995)
    )
    joint_record = (
        pl.col(category_col).cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        == "joint"
    )
    multiplier = pl.when(valid_participant_count).then(participant_count).otherwise(1.0)
    return (
        pl.when(joint_record)
        .then(weight * multiplier)
        .otherwise(weight)
        .alias(output_col)
    )


def attach_person_travel_weight(
    rd: RunData,
    activity: pl.DataFrame,
    *,
    participant_col: str,
    output_col: str,
    weight_col: str = "finalweight",
    category_col: str = "tour_category",
    tour_id_col: str = "tour_id",
) -> pl.DataFrame:
    """Attach a person-tour or person-trip weight to every activity row."""
    weighted = activity.with_columns(
        joint_participant_weight_expr(
            activity,
            participant_col=participant_col,
            output_col=output_col,
            weight_col=weight_col,
            category_col=category_col,
        )
    )
    if (
        category_col not in activity.columns
        or tour_id_col not in activity.columns
        or not {tour_id_col, "person_id"}.issubset(rd.joint_participants.columns)
        or not {"person_id", "finalweight"}.issubset(rd.per.columns)
        or rd.joint_participants.is_empty()
        or rd.per.is_empty()
    ):
        return weighted

    attributed_col = "_attributed_person_travel_weight"
    participant_weights = (
        rd.joint_participants.filter(pl.col(tour_id_col).is_not_null())
        .select(tour_id_col, "person_id")
        .join(
            rd.per.filter(
                pl.col("person_id").is_not_null()
                & pl.col("finalweight").is_not_null()
            ).select(
                "person_id",
                pl.col("finalweight").cast(pl.Float64).alias(attributed_col),
            ),
            on="person_id",
            how="inner",
        )
        .group_by(tour_id_col)
        .agg(pl.col(attributed_col).sum())
    )
    if participant_weights.is_empty():
        return weighted

    joint_record = (
        pl.col(category_col).cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        == "joint"
    )
    return (
        weighted.join(participant_weights, on=tour_id_col, how="left")
        .with_columns(
            pl.when(joint_record & pl.col(attributed_col).is_not_null())
            .then(pl.col(attributed_col))
            .otherwise(pl.col(output_col))
            .alias(output_col)
        )
        .drop(attributed_col)
    )


def joint_party_size_expr(df: pl.DataFrame) -> pl.Expr:
    """Resolve a valid household joint-tour party size from prepared columns."""
    candidates: list[pl.Expr] = []
    for column in ("number_of_participants", "NUMBER_HH"):
        if column not in df.columns:
            continue
        party_size = pl.col(column).cast(pl.Float64, strict=False)
        candidates.append(
            pl.when(
                party_size.is_not_null()
                & party_size.is_finite()
                & (party_size >= 2)
                & (party_size < 995)
            ).then(party_size)
        )
    if not candidates:
        return pl.lit(None, dtype=pl.Float64)
    return pl.coalesce(candidates)


def household_tour_weight_expr(
    df: pl.DataFrame,
    *,
    output_col: str,
    weight_col: str = "finalweight",
    category_col: str = "tour_category",
    joint_tour_id_col: str = "joint_tour_id",
) -> pl.Expr:
    """Return a row-preserving household-tour representation weight.

    Some survey tour tables contain one joint-tour row per participant. When a
    valid joint-tour ID has exactly the reported number of participant rows,
    each row receives 1/k of its source weight. ActivitySim's one-row joint
    tours and incomplete or malformed groups retain their full source weight.
    """
    weight = pl.col(weight_col).cast(pl.Float64)
    if category_col not in df.columns or joint_tour_id_col not in df.columns:
        return weight.alias(output_col)

    joint_record = (
        pl.col(category_col).cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        == "joint"
    )
    joint_tour_id = pl.col(joint_tour_id_col)
    joint_tour_id_text = joint_tour_id.cast(pl.Utf8, strict=False).str.strip_chars()
    numeric_joint_tour_id = joint_tour_id.cast(pl.Float64, strict=False)
    valid_joint_tour_id = (
        joint_tour_id_text.is_not_null()
        & (joint_tour_id_text != "")
        & (
            numeric_joint_tour_id.is_null()
            | (
                numeric_joint_tour_id.is_finite()
                & (numeric_joint_tour_id > 0)
                & (numeric_joint_tour_id != 995)
            )
        )
    )

    party_size = joint_party_size_expr(df)
    represented_rows = (
        pl.when(joint_record).then(1).otherwise(0).sum().over(joint_tour_id_col)
    ).cast(pl.Float64)
    complete_participant_group = (
        (represented_rows > 1)
        & (party_size.min().over(joint_tour_id_col) == represented_rows)
        & (party_size.max().over(joint_tour_id_col) == represented_rows)
    )
    return (
        pl.when(joint_record & valid_joint_tour_id & complete_participant_group)
        .then(weight / represented_rows)
        .otherwise(weight)
        .alias(output_col)
    )


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


def aggregate_counts_by_geography(
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


def aggregate_counts_across_geographies(
    df: pl.DataFrame,
    *,
    geography_dimensions: list[tuple[str, str]],
    value_col: str = "trip_count",
    weight_col: str = "finalweight",
) -> pl.DataFrame:
    """Aggregate one frame across multiple geography dimensions."""
    outputs = [
        aggregate_counts_by_geography(
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


def aggregate_weighted_average_across_geographies(
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


POSITIVE_SUBMILE_DISTANCE_BIN = ">0-<1"


def _distance_bin_labels(cap_value: int = 40) -> list[str]:
    """Return the common exact-zero, sub-mile, whole-mile, and terminal bins."""
    return [
        "0",
        POSITIVE_SUBMILE_DISTANCE_BIN,
        *[str(value) for value in range(1, cap_value)],
        f"{cap_value}+",
    ]


def _distance_bin_expr(distance_col: str, *, cap_value: int = 40) -> pl.Expr:
    """Bin usable distances without combining exact zero and sub-mile values."""
    distance = pl.col(distance_col).cast(pl.Float64, strict=False)
    return (
        pl.when(~distance.is_finite() | (distance < 0))
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(distance == 0)
        .then(pl.lit("0"))
        .when(distance < 1)
        .then(pl.lit(POSITIVE_SUBMILE_DISTANCE_BIN))
        .when(distance >= cap_value)
        .then(pl.lit(f"{cap_value}+"))
        .otherwise(distance.floor().cast(pl.Int64, strict=False).cast(pl.Utf8))
        .alias("distance_bin")
    )


def _distance_bin_sort_expr(column: str = "distance_bin") -> pl.Expr:
    """Sort the common distance-bin labels by their numeric axis position."""
    label = pl.col(column).cast(pl.Utf8)
    numeric = label.str.replace(r"\+$", "").cast(pl.Float64, strict=False)
    return (
        pl.when(label == POSITIVE_SUBMILE_DISTANCE_BIN)
        .then(pl.lit(0.5))
        .when(numeric.is_null())
        .then(pl.lit(float("inf")))
        .otherwise(numeric)
    )


def _ensure_zero_distance_bin(
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    """Add a zero-valued exact-zero bin for every represented group."""
    if df.is_empty():
        return df
    zero_rows = df.select(group_cols).unique().with_columns(
        pl.lit("0").alias("distance_bin"),
        pl.lit(0.0).alias(value_col),
    )
    return (
        pl.concat([df, zero_rows.select(df.columns)], how="vertical")
        .group_by(["distance_bin", *group_cols])
        .agg(pl.col(value_col).sum())
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
