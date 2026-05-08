"""Summaries for skim-enriched prepared tables."""

from __future__ import annotations

import math

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from runtime.config import Config

_PERCENTILES = [index / 100 for index in range(101)]


def _is_numeric_dtype(dtype: pl.DataType | None) -> bool:
    if dtype is None:
        return False
    checker = getattr(dtype, "is_numeric", None)
    return bool(checker()) if callable(checker) else False


def _skim_component_columns(df: pl.DataFrame) -> list[str]:
    return [
        column
        for column in df.columns
        if "skim_" in column and _is_numeric_dtype(df.schema.get(column))
    ]


def _mode_value(values: list[float], weights: list[float]) -> float | None:
    if not values:
        return None

    totals: dict[float, float] = {}
    for value, weight in zip(values, weights, strict=False):
        totals[value] = totals.get(value, 0.0) + weight

    best_weight = max(totals.values())
    return min(value for value, weight in totals.items() if weight == best_weight)


def _weighted_quantile(
    values: list[float],
    weights: list[float],
    percentile: float,
) -> float | None:
    if not values:
        return None

    pairs = sorted(zip(values, weights, strict=False), key=lambda item: item[0])
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None

    threshold = total_weight * percentile
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _weighted_stats_rows(df: pl.DataFrame, *, mode_column: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    component_columns = _skim_component_columns(df)
    if not component_columns:
        return rows

    if mode_column not in df.columns or "finalweight" not in df.columns:
        return rows

    for mode_value in (
        df.filter(pl.col(mode_column).is_not_null())
        .select(pl.col(mode_column).cast(pl.Utf8))
        .unique()
        .sort(mode_column)
        .get_column(mode_column)
        .to_list()
    ):
        mode_df = df.filter(pl.col(mode_column).cast(pl.Utf8) == mode_value)
        n_total = float(
            mode_df.select(pl.col("finalweight").sum().alias("n_total"))["n_total"][0]
            or 0.0
        )

        for component in component_columns:
            valid_df = mode_df.filter(pl.col(component).is_not_null())
            if valid_df.is_empty():
                rows.append(
                    {
                        mode_column: mode_value,
                        "component": component,
                        "n_total": n_total,
                        "n_valid": 0.0,
                        "mean": None,
                        "std": None,
                        "min": None,
                        "max": None,
                        "median": None,
                        "mode": None,
                        "zero_share": None,
                        "missing_share": (
                            None if n_total == 0 else (n_total - 0.0) / n_total
                        ),
                    }
                )
                continue

            values = [
                float(value)
                for value in valid_df.get_column(component).cast(pl.Float64).to_list()
            ]
            weights = [
                float(value)
                for value in valid_df.get_column("finalweight").cast(pl.Float64).to_list()
            ]
            n_valid = float(sum(weights))
            if n_valid <= 0:
                rows.append(
                    {
                        mode_column: mode_value,
                        "component": component,
                        "n_total": n_total,
                        "n_valid": 0.0,
                        "mean": None,
                        "std": None,
                        "min": None,
                        "max": None,
                        "median": None,
                        "mode": None,
                        "zero_share": None,
                        "missing_share": None if n_total == 0 else 1.0,
                    }
                )
                continue

            mean = sum(value * weight for value, weight in zip(values, weights, strict=False)) / n_valid
            variance = (
                sum(
                    weight * ((value - mean) ** 2)
                    for value, weight in zip(values, weights, strict=False)
                )
                / n_valid
            )
            zero_weight = sum(
                weight
                for value, weight in zip(values, weights, strict=False)
                if value == 0.0
            )

            rows.append(
                {
                    mode_column: mode_value,
                    "component": component,
                    "n_total": n_total,
                    "n_valid": n_valid,
                    "mean": mean,
                    "std": math.sqrt(variance),
                    "min": min(values),
                    "max": max(values),
                    "median": _weighted_quantile(values, weights, 0.5),
                    "mode": _mode_value(values, weights),
                    "zero_share": zero_weight / n_valid,
                    "missing_share": None if n_total == 0 else (n_total - n_valid) / n_total,
                }
            )

    return rows


def _weighted_ecdf_rows(df: pl.DataFrame, *, mode_column: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    component_columns = _skim_component_columns(df)
    if not component_columns:
        return rows

    if mode_column not in df.columns or "finalweight" not in df.columns:
        return rows

    for mode_value in (
        df.filter(pl.col(mode_column).is_not_null())
        .select(pl.col(mode_column).cast(pl.Utf8))
        .unique()
        .sort(mode_column)
        .get_column(mode_column)
        .to_list()
    ):
        mode_df = df.filter(pl.col(mode_column).cast(pl.Utf8) == mode_value)

        for component in component_columns:
            valid_df = mode_df.filter(pl.col(component).is_not_null())
            if valid_df.is_empty():
                continue

            values = [
                float(value)
                for value in valid_df.get_column(component).cast(pl.Float64).to_list()
            ]
            weights = [
                float(value)
                for value in valid_df.get_column("finalweight").cast(pl.Float64).to_list()
            ]
            n_valid = float(sum(weights))
            if n_valid <= 0:
                continue

            for percentile in _PERCENTILES:
                rows.append(
                    {
                        mode_column: mode_value,
                        "component": component,
                        "percentile": float(percentile),
                        "value": _weighted_quantile(values, weights, percentile),
                        "n_valid": n_valid,
                    }
                )

    return rows


def _stats_frame(df: pl.DataFrame, *, mode_column: str, builder) -> pl.DataFrame:
    rows = _weighted_stats_rows(df, mode_column=mode_column)
    if not rows:
        return empty_summary_frame(builder)
    empty_frame = empty_summary_frame(builder)
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(*empty_frame.columns)
        .cast(empty_frame.schema)
        .sort([mode_column, "component"])
    )


def _ecdf_frame(df: pl.DataFrame, *, mode_column: str, builder) -> pl.DataFrame:
    rows = _weighted_ecdf_rows(df, mode_column=mode_column)
    if not rows:
        return empty_summary_frame(builder)
    empty_frame = empty_summary_frame(builder)
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(*empty_frame.columns)
        .cast(empty_frame.schema)
        .sort([mode_column, "component", "percentile"])
    )


@summary_contract(
    schema={
        "trip_mode": pl.Utf8,
        "component": pl.Utf8,
        "n_total": pl.Float64,
        "n_valid": pl.Float64,
        "mean": pl.Float64,
        "std": pl.Float64,
        "min": pl.Float64,
        "max": pl.Float64,
        "median": pl.Float64,
        "mode": pl.Float64,
        "zero_share": pl.Float64,
        "missing_share": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "finalweight")},
)
def trip_skim_component_stats(rd: RunData, config: Config) -> pl.DataFrame:
    return _stats_frame(rd.trips, mode_column="trip_mode", builder=trip_skim_component_stats)


@summary_contract(
    schema={
        "trip_mode": pl.Utf8,
        "component": pl.Utf8,
        "percentile": pl.Float64,
        "value": pl.Float64,
        "n_valid": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "finalweight")},
)
def trip_skim_component_ecdf(rd: RunData, config: Config) -> pl.DataFrame:
    return _ecdf_frame(rd.trips, mode_column="trip_mode", builder=trip_skim_component_ecdf)


@summary_contract(
    schema={
        "tour_mode": pl.Utf8,
        "component": pl.Utf8,
        "n_total": pl.Float64,
        "n_valid": pl.Float64,
        "mean": pl.Float64,
        "std": pl.Float64,
        "min": pl.Float64,
        "max": pl.Float64,
        "median": pl.Float64,
        "mode": pl.Float64,
        "zero_share": pl.Float64,
        "missing_share": pl.Float64,
    },
    required_columns={"tours": ("tour_mode", "finalweight")},
)
def tour_skim_component_stats(rd: RunData, config: Config) -> pl.DataFrame:
    return _stats_frame(rd.tours, mode_column="tour_mode", builder=tour_skim_component_stats)


@summary_contract(
    schema={
        "tour_mode": pl.Utf8,
        "component": pl.Utf8,
        "percentile": pl.Float64,
        "value": pl.Float64,
        "n_valid": pl.Float64,
    },
    required_columns={"tours": ("tour_mode", "finalweight")},
)
def tour_skim_component_ecdf(rd: RunData, config: Config) -> pl.DataFrame:
    return _ecdf_frame(rd.tours, mode_column="tour_mode", builder=tour_skim_component_ecdf)
