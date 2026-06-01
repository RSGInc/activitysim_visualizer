"""Shared helpers for percent-error formatting and base-run comparison tables."""

from __future__ import annotations

import math
from typing import Any

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

    rows: list[dict[str, Any]] = []
    for row_label, values_by_run in row_values.items():
        row: dict[str, Any] = {row_header: row_label}
        base_value = values_by_run.get(base_run_label)
        row[base_run_label] = (
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
    category_col: str,
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
    if category_col not in df.columns or average_col not in df.columns:
        return {}
    if weight_col not in df.columns:
        aggregated = (
            df.group_by(category_col)
            .agg(pl.col(average_col).mean().alias(average_col))
            .select(category_col, average_col)
        )
        return {
            str(row[category_col]): float(row[average_col])
            for row in aggregated.to_dicts()
            if row.get(category_col) is not None and row.get(average_col) is not None
        }
    aggregated = (
        df.group_by(category_col)
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
        .select(category_col, average_col)
    )
    return {
        str(row[category_col]): float(row[average_col])
        for row in aggregated.to_dicts()
        if row.get(category_col) is not None and row.get(average_col) is not None
    }
