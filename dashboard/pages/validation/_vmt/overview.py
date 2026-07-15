"""VMT overview totals and share calculations."""

from __future__ import annotations

import polars as pl

from dashboard.helpers.category_helpers import nonempty
from dashboard.helpers.geography_helpers import ALL_GEOGRAPHY_TYPES_VALUE

from .contracts import (
    EXTERNAL_COMMERCIAL_COLUMNS,
    EXTERNAL_TRAVEL_COLUMNS,
    EXTERNAL_TRAVEL_TOTAL_COLUMN,
    VMT_OVERVIEW_ROWS,
)


def _sum_float_column(df: pl.DataFrame, column: str) -> float:
    if df.is_empty() or column not in df.columns:
        return 0.0
    value = df.select(pl.col(column).cast(pl.Float64).sum()).item()
    return float(value or 0.0)


def _total_segmented_vmt(df: pl.DataFrame, value_col: str) -> float:
    if df.is_empty() or value_col not in df.columns:
        return 0.0

    filtered = df
    if {"geography_type", "geography_id"}.issubset(filtered.columns):
        all_geography_rows = filtered.filter(
            (pl.col("geography_type").cast(pl.Utf8) == ALL_GEOGRAPHY_TYPES_VALUE)
            & (pl.col("geography_id").cast(pl.Utf8) == ALL_GEOGRAPHY_TYPES_VALUE)
        )
        if not all_geography_rows.is_empty():
            filtered = all_geography_rows

    if "time_period" in filtered.columns:
        daily_rows = filtered.filter(pl.col("time_period").cast(pl.Utf8) == "Daily")
        if not daily_rows.is_empty():
            filtered = daily_rows

    return _sum_float_column(filtered, value_col)


def _total_wide_tod_vmt(
    df: pl.DataFrame,
    *,
    value_columns: list[str],
    total_column: str | None = None,
    tod_col: str = "tod",
) -> float:
    if df.is_empty():
        return 0.0

    filtered = df
    if tod_col in filtered.columns:
        daily_rows = filtered.filter(
            pl.col(tod_col).cast(pl.Utf8).str.to_lowercase() == "daily"
        )
        if not daily_rows.is_empty():
            filtered = daily_rows

    if total_column and total_column in filtered.columns:
        return _sum_float_column(filtered, total_column)

    available_columns = [
        column for column in value_columns if column in filtered.columns
    ]
    if not available_columns:
        return 0.0
    value = filtered.select(
        pl.sum_horizontal(
            [pl.col(column).cast(pl.Float64) for column in available_columns]
        )
        .sum()
        .alias("vmt")
    ).item()
    return float(value or 0.0)


def vmt_overview_table_data(
    *,
    personal_auto_vmt: list[tuple[str, pl.DataFrame]] | None,
    non_motorized_vmt: list[tuple[str, pl.DataFrame]] | None,
    external_vmt: list[tuple[str, pl.DataFrame]] | None,
    commercial_vmt: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one VMT/share overview table per run label."""
    personal_auto_vmt = personal_auto_vmt or []
    non_motorized_vmt = non_motorized_vmt or []
    external_vmt = external_vmt or []
    commercial_vmt = commercial_vmt or []
    labels = list(
        dict.fromkeys(
            label
            for data_list in (
                personal_auto_vmt,
                non_motorized_vmt,
                external_vmt,
                commercial_vmt,
            )
            for label, _ in data_list
        )
    )
    personal_by_label = dict(personal_auto_vmt)
    non_motorized_by_label = dict(non_motorized_vmt)
    external_by_label = dict(external_vmt)
    commercial_by_label = dict(commercial_vmt)

    out: list[tuple[str, pl.DataFrame]] = []
    for label in labels:
        totals = {
            "Personal Auto": _total_segmented_vmt(
                personal_by_label.get(label, pl.DataFrame()),
                "auto_vmt",
            ),
            "Non-Motorized": _total_segmented_vmt(
                non_motorized_by_label.get(label, pl.DataFrame()),
                "non_motorized_vmt",
            ),
            "External": _total_wide_tod_vmt(
                external_by_label.get(label, pl.DataFrame()),
                value_columns=EXTERNAL_TRAVEL_COLUMNS,
                total_column=EXTERNAL_TRAVEL_TOTAL_COLUMN,
            ),
            "Commercial": _total_wide_tod_vmt(
                commercial_by_label.get(label, pl.DataFrame()),
                value_columns=EXTERNAL_COMMERCIAL_COLUMNS,
            ),
        }
        grand_total = sum(totals.values())
        share_values = [
            (totals[row] / grand_total * 100.0) if grand_total > 0 else 0.0
            for row in VMT_OVERVIEW_ROWS
        ]
        out.append(
            (
                label,
                pl.DataFrame(
                    {
                        "Category": list(VMT_OVERVIEW_ROWS),
                        "VMT": [totals[row] for row in VMT_OVERVIEW_ROWS],
                        "% Share of Total": share_values,
                    }
                ),
            )
        )
    return out
