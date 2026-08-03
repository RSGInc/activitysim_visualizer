"""Shared helpers for percent-error formatting and base-run comparison tables."""

from __future__ import annotations

import math
from typing import Any, Mapping

import polars as pl


def format_percent_error_table(
    df: pl.DataFrame,
    *,
    column: str = "percent_error",
    precision: int = 2,
) -> pl.DataFrame:
    """Format percent-error columns for display while preserving blank invalid values."""
    if column not in df.columns:
        return df
    return df.with_columns(
        pl.col(column)
        .map_elements(
            lambda value: (
                ""
                if value is None
                or (isinstance(value, float) and not math.isfinite(value))
                else f"{float(value):.{precision}f}%"
            ),
            return_dtype=pl.Utf8,
        )
        .fill_null("")
        .alias(column)
    )


def percent_difference_string(
    base_value: float | None,
    compare_value: float | None,
    *,
    precision: int = 2,
) -> str:
    """Return a formatted percent-difference string relative to a base value."""
    if base_value is None:
        return ""
    if compare_value is None:
        return ""
    if float(base_value) == 0.0:
        return ""
    pct_diff = ((float(compare_value) - float(base_value)) / float(base_value)) * 100.0
    return f"{pct_diff:.{precision}f}%"


def _finite_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def ab_percent_difference_string(
    quantity_a: float | int | None,
    quantity_b: float | int | None,
    *,
    precision: int = 2,
) -> str:
    """Return formatted percent difference using the second value as denominator."""
    a_value = _finite_float(quantity_a)
    b_value = _finite_float(quantity_b)
    if a_value is None or b_value is None or b_value == 0.0:
        return ""
    pct_diff = ((a_value - b_value) / b_value) * 100.0
    return f"{pct_diff:.{precision}f}%"


def ab_difference_value(
    quantity_a: float | int | None,
    quantity_b: float | int | None,
) -> float | None:
    """Return absolute difference for a single A/B comparison."""
    a_value = _finite_float(quantity_a)
    b_value = _finite_float(quantity_b)
    if a_value is None or b_value is None:
        return None
    return math.sqrt((a_value - b_value) ** 2)


def build_ab_comparison_row(
    *,
    keys: Mapping[str, Any],
    quantity_a: float | int | None,
    quantity_b: float | int | None,
    quantity_a_column: str,
    quantity_b_column: str,
    precision: int = 2,
) -> dict[str, Any]:
    """Build one long-form A/B comparison row with caller-supplied value labels."""
    a_value = _finite_float(quantity_a)
    b_value = _finite_float(quantity_b)
    return {
        **dict(keys),
        quantity_a_column: a_value,
        quantity_b_column: b_value,
        "Difference": ab_difference_value(a_value, b_value),
        "% Difference": ab_percent_difference_string(
            a_value,
            b_value,
            precision=precision,
        ),
    }


def build_ab_comparison_table(
    rows: list[Mapping[str, Any]],
    *,
    key_columns: list[str],
    quantity_a_column: str,
    quantity_b_column: str,
) -> pl.DataFrame:
    """Return rows with stable key/A/B/difference/% difference column ordering."""
    columns = [
        *key_columns,
        quantity_a_column,
        quantity_b_column,
        "Difference",
        "% Difference",
    ]
    if not rows:
        schema = {
            **{column: pl.Utf8 for column in key_columns},
            quantity_a_column: pl.Float64,
            quantity_b_column: pl.Float64,
            "Difference": pl.Float64,
            "% Difference": pl.Utf8,
        }
        return pl.DataFrame(schema=schema).select(columns)
    return pl.DataFrame(rows).select(columns)


def build_base_run_percent_difference_table(
    *,
    run_labels: list[str],
    base_run_label: str,
    row_header: str,
    row_values: dict[str, dict[str, float | None]],
    precision: int = 2,
) -> pl.DataFrame:
    """Build a page-ready comparison table from pre-aggregated run values."""
    if not run_labels or base_run_label not in run_labels:
        return pl.DataFrame()
    base_column_label = (
        base_run_label
        if base_run_label == "Base"
        else f"{base_run_label} (Base Run)"
    )

    rows: list[dict[str, Any]] = []
    for row_label, values_by_run in row_values.items():
        row: dict[str, Any] = {row_header: row_label}
        base_value = values_by_run.get(base_run_label)
        row[base_column_label] = (
            f"{0.0:.{precision}f}%"
            if base_value is not None
            else ""
        )
        for run_label in run_labels:
            if run_label == base_run_label:
                continue
            row[run_label] = percent_difference_string(
                base_value,
                values_by_run.get(run_label),
                precision=precision,
            )
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def weighted_average_lookup(
    df: pl.DataFrame,
    *,
    category: str,
    average_col: str,
    weight_col: str,
) -> dict[str, float]:
    """Aggregate one frame into averages keyed by category.

    When `weight_col` is present, this returns a weighted average. Some summary
    tables only expose a pre-aggregated average column, so this helper falls
    back to a simple mean in that case to preserve export-time compatibility.
    """
    if df.is_empty():
        return {}
    if category not in df.columns or average_col not in df.columns:
        return {}
    if weight_col not in df.columns:
        aggregated = (
            df.group_by(category)
            .agg(pl.col(average_col).mean().alias(average_col))
            .select(category, average_col)
        )
        return {
            str(row[category]): float(row[average_col])
            for row in aggregated.to_dicts()
            if row.get(category) is not None and row.get(average_col) is not None
        }
    aggregated = (
        df.group_by(category)
        .agg(
            pl.col(weight_col).sum().alias(weight_col),
            (pl.col(average_col) * pl.col(weight_col)).sum().alias("_weighted_value"),
        )
        .with_columns(
            pl.when(pl.col(weight_col) > 0)
            .then(pl.col("_weighted_value") / pl.col(weight_col))
            .otherwise(None)
            .alias(average_col)
        )
        .select(category, average_col)
    )
    return {
        str(row[category]): float(row[average_col])
        for row in aggregated.to_dicts()
        if row.get(category) is not None and row.get(average_col) is not None
    }
