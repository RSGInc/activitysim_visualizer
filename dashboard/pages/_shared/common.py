"""Common helper utilities reused across dashboard page modules."""

from __future__ import annotations

import polars as pl


def nonempty_runs(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Return only runs with non-empty DataFrames."""
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def first_nonempty_frame(
    *data_lists: list[tuple[str, pl.DataFrame]],
) -> pl.DataFrame | None:
    """Return the first non-empty DataFrame across one or more run lists."""
    for data_list in data_lists:
        for _, df in nonempty_runs(data_list):
            return df
    return None


def column_options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    *,
    total_label: str = "All",
    include_total: bool = True,
    exclude: tuple[str, ...] = (),
) -> list[str]:
    """Build selector options from the first available run."""
    first_df = first_nonempty_frame(data_list)
    if first_df is None or col not in first_df.columns:
        return [total_label] if include_total else []

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    excluded = {total_label, *exclude}
    options = sorted(v for v in vals if v not in excluded)
    if include_total:
        return [total_label] + options
    return options


def filter_runs_by_column(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    value: str,
    *,
    total_values: tuple[str, ...] = ("All", "Total"),
) -> list[tuple[str, pl.DataFrame]]:
    """Filter each run by one string-like column unless the value is aggregate."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty_runs(data_list):
        if col in df.columns and value not in total_values:
            df = df.with_columns(pl.col(col).cast(pl.Utf8)).filter(pl.col(col) == value)
        out.append((label, df))
    return out


def category_order(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
) -> list[str]:
    """Return category values in first-seen order across runs."""
    order: list[str] = []
    for _, df in nonempty_runs(data_list):
        if category_col not in df.columns:
            continue
        values = (
            df.select(category_col).drop_nulls().to_series().cast(pl.Utf8).to_list()
        )
        for value in values:
            if value not in order:
                order.append(value)
    return order


def complete_category_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    category_col: str,
    category_values: list[str],
    value_cols: tuple[str, ...] = ("person_count", "pct"),
) -> list[tuple[str, pl.DataFrame]]:
    """Fill missing category/value combinations with zeros for each run."""
    if not category_values:
        return data_list

    base = pl.DataFrame({category_col: category_values})
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in data_list:
        if df is None:
            completed = base
        else:
            available_cols = [col for col in (category_col, *value_cols) if col in df.columns]
            completed = base.join(df.select(available_cols), on=category_col, how="left")
        fill_exprs = []
        for col in value_cols:
            if col in completed.columns:
                fill_exprs.append(pl.col(col).fill_null(0).alias(col))
            else:
                fill_exprs.append(pl.lit(0).alias(col))
        out.append((label, completed.with_columns(fill_exprs)))
    return out
