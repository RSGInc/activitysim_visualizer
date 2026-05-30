"""Shared helpers for repeated time-bin and distance-bin formatting."""

from __future__ import annotations

import polars as pl

from dashboard.helpers.category_helpers import nonempty, numeric_like_sort_expr


def max_timebin(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    column: str = "time_bin",
    default: int = 48,
) -> int:
    """Return the observed max time bin across runs, falling back to the half-hour clock."""
    for _, df in nonempty(data_list):
        if column in df.columns:
            return int(df[column].max())
    return default


def timebin_label(timebin: int, maxbin: int) -> str:
    """Convert a time-bin index into the dashboard's 03:00-based clock label."""
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def timebin_duration_hours(timebin: int, maxbin: int) -> float:
    """Convert a duration-bin count to hours using the observed time-bin resolution."""
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def distance_sort_expr(column: str) -> pl.Expr:
    """Sort distance bins numerically, including values like ``40+`` after ``39``."""
    return numeric_like_sort_expr(column)
