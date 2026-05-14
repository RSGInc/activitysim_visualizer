"""Shared time- and distance-bin helpers for dashboard pages."""

from __future__ import annotations

import polars as pl

from dashboard.pages._shared.common import nonempty_runs


def time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def duration_hours(timebin: int, maxbin: int) -> float:
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def max_timebin(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    column: str = "time_bin",
    default: int = 48,
) -> int:
    for _, df in nonempty_runs(data_list):
        if column in df.columns:
            return int(df[column].max())
    return default


def distance_bin_sort_expr(column: str, *, plus_label: str = "40+") -> pl.Expr:
    return (
        pl.when(pl.col(column).cast(pl.Utf8) == plus_label)
        .then(999)
        .otherwise(pl.col(column).cast(pl.Int64, strict=False))
    )
