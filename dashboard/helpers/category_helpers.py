"""Shared helpers for selector domains, labels, ordering, and category completion."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import polars as pl

from dashboard.state import DashboardState
from runtime.config import Config


def nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Drop empty or missing run tables while preserving run labels."""
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def first_nonempty_frame(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *columns: str,
) -> pl.DataFrame | None:
    """Return the first non-empty frame that contains every requested column."""
    if not data_list:
        return None
    for _, df in nonempty(data_list):
        if all(column in df.columns for column in columns):
            return df
    return None


def column_value_union(
    data_list: list[tuple[str, pl.DataFrame]],
    column: str,
    *,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
) -> list[str]:
    """Return unique column values across all usable runs, preserving discovery order."""

    def _compute() -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for _, df in nonempty(data_list):
            if column not in df.columns:
                continue
            series = df.select(column).drop_nulls().to_series().cast(pl.Utf8)
            for value in series.to_list():
                value_str = str(value)
                if value_str in seen:
                    continue
                seen.add(value_str)
                values.append(value_str)
        return values

    if state is None or cache_key is None:
        return _compute()
    return state.get_or_create_cached("selector_domain", *cache_key, factory=_compute)


def column_value_intersection(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
    column: str,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
) -> list[str]:
    """Return values present in every usable run across every provided data list."""

    def _compute() -> list[str]:
        common_values: set[str] | None = None
        ordered_values: list[str] = []
        seen_ordered: set[str] = set()

        for data_list in data_lists:
            if not data_list:
                continue
            per_run_sets: list[set[str]] = []
            for _, df in nonempty(data_list):
                if column not in df.columns:
                    continue
                values = (
                    df.select(column)
                    .drop_nulls()
                    .to_series()
                    .cast(pl.Utf8)
                    .to_list()
                )
                value_set = {str(value) for value in values}
                if value_set:
                    per_run_sets.append(value_set)
                for value in values:
                    value_str = str(value)
                    if value_str in seen_ordered:
                        continue
                    seen_ordered.add(value_str)
                    ordered_values.append(value_str)
            if not per_run_sets:
                continue
            list_intersection = set.intersection(*per_run_sets)
            common_values = (
                list_intersection
                if common_values is None
                else common_values.intersection(list_intersection)
            )

        if not common_values:
            return []
        return [value for value in ordered_values if value in common_values]

    if state is None or cache_key is None:
        return _compute()
    return state.get_or_create_cached("selector_domain", *cache_key, factory=_compute)


def ordered_category_values(
    data_list: list[tuple[str, pl.DataFrame]],
    column: str,
    *,
    category_id: str | None = None,
    config: Config | None = None,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
) -> list[str]:
    """Return column values ordered by config metadata when available."""
    values = column_value_union(
        data_list,
        column,
        state=state,
        cache_key=cache_key,
    )
    if category_id is None or config is None:
        return values
    return config.ordered_values(category_id, values)


def selector_options_from_values(
    raw_values: Iterable[str],
    *,
    total_label: str | None = None,
    total_values: Iterable[str] = (),
) -> list[str]:
    """Build selector labels from raw values with an optional leading total label."""
    options: list[str] = []
    if total_label is not None:
        options.append(total_label)
    skipped = {str(value) for value in total_values}
    for raw_value in raw_values:
        value = str(raw_value)
        if value in skipped or value == total_label:
            continue
        options.append(value)
    return options


def raw_display_options(
    raw_values: list[str],
    *,
    category_id: str | None = None,
    config: Config | None = None,
    total_raw: str | None = None,
    total_label: str | None = None,
) -> tuple[list[str], dict[str, str | None]]:
    """Return display labels plus a reverse mapping back to raw values."""
    label_to_raw: dict[str, str | None] = {}
    if total_label is not None:
        label_to_raw[total_label] = total_raw
    for raw_value in raw_values:
        if total_raw is not None and raw_value == total_raw:
            continue
        display_value = (
            config.label_value(category_id, raw_value)
            if category_id is not None and config is not None
            else str(raw_value)
        )
        label_to_raw[display_value] = raw_value
    return list(label_to_raw), label_to_raw


def column_options(
    data_list: list[tuple[str, pl.DataFrame]],
    column: str,
    *,
    category_id: str | None = None,
    config: Config | None = None,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
    total_raw: str | None = None,
    total_label: str | None = None,
) -> tuple[list[str], dict[str, str | None]]:
    """Build ordered selector labels for one column plus display-to-raw lookup."""
    raw_values = ordered_category_values(
        data_list,
        column,
        category_id=category_id,
        config=config,
        state=state,
        cache_key=cache_key,
    )
    return raw_display_options(
        raw_values,
        category_id=category_id,
        config=config,
        total_raw=total_raw,
        total_label=total_label,
    )


def common_column_options(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
    column: str,
    category_id: str | None = None,
    config: Config | None = None,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
    total_raw: str | None = None,
    total_label: str | None = None,
) -> tuple[list[str], dict[str, str | None]]:
    """Build selector options from the intersection of values across data lists."""
    raw_values = column_value_intersection(
        *data_lists,
        column=column,
        state=state,
        cache_key=cache_key,
    )
    if category_id is not None and config is not None:
        raw_values = config.ordered_values(category_id, raw_values)
    return raw_display_options(
        raw_values,
        category_id=category_id,
        config=config,
        total_raw=total_raw,
        total_label=total_label,
    )


def label_category_frame(
    df: pl.DataFrame,
    *,
    source_col: str,
    category_id: str,
    config: Config,
    target_col: str | None = None,
) -> pl.DataFrame:
    """Add a config-driven display label column for one categorical source column."""
    label_col = target_col or f"{source_col}_label"
    if source_col not in df.columns:
        return df
    return df.with_columns(
        pl.col(source_col)
        .cast(pl.Utf8)
        .map_elements(
            lambda value: config.label_value(category_id, value),
            return_dtype=pl.Utf8,
        )
        .alias(label_col)
    )


def label_category_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    source_col: str,
    category_id: str,
    config: Config,
    target_col: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Apply config-driven category labels across a run-indexed data list."""
    label_col = target_col or f"{source_col}_label"
    labeled: list[tuple[str, pl.DataFrame]] = []
    for label, df in data_list:
        if df is None:
            labeled.append((label, df))
            continue
        labeled.append(
            (
                label,
                label_category_frame(
                    df,
                    source_col=source_col,
                    category_id=category_id,
                    config=config,
                    target_col=label_col,
                ),
            )
        )
    return labeled


def normalize_category_strings(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
    *,
    blank_label: str = "Unspecified",
) -> list[tuple[str, pl.DataFrame]]:
    """Cast one category column to strings and replace blank values consistently."""
    return [
        (
            label,
            df.with_columns(
                pl.when(pl.col(category_col).cast(pl.Utf8).str.strip_chars() == "")
                .then(pl.lit(blank_label))
                .otherwise(pl.col(category_col).cast(pl.Utf8))
                .alias(category_col)
            ),
        )
        for label, df in nonempty(data_list)
    ]


def numeric_like_sort_expr(column: str) -> pl.Expr:
    """Sort numeric-like string bins numerically while leaving text bins at the end."""
    base_value = (
        pl.col(column)
        .cast(pl.Utf8)
        .str.replace(r"\+$", "")
        .cast(pl.Float64, strict=False)
    )
    return pl.when(base_value.is_null()).then(pl.lit(float("inf"))).otherwise(base_value)


def complete_category_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    category_col: str,
    category_values: list[str],
    value_cols: tuple[str, ...],
    extra_fill_values: dict[str, Any] | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Ensure each run has one row per category value with zero-filled metric columns."""
    if not category_values:
        return data_list
    base = pl.DataFrame({category_col: category_values}, schema={category_col: pl.Utf8})
    fill_values = dict(extra_fill_values or {})
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in data_list:
        if df is None:
            completed = base
        else:
            available_cols = [column for column in df.columns if column != category_col]
            completed = base.join(
                df.with_columns(pl.col(category_col).cast(pl.Utf8)).select(
                    category_col, *available_cols
                ),
                on=category_col,
                how="left",
            )
        fill_exprs = []
        for value_col in value_cols:
            if value_col in completed.columns:
                fill_exprs.append(pl.col(value_col).fill_null(0).alias(value_col))
            else:
                fill_exprs.append(pl.lit(0).alias(value_col))
        for column, fill_value in fill_values.items():
            if column in completed.columns:
                fill_exprs.append(pl.col(column).fill_null(fill_value).alias(column))
            else:
                fill_exprs.append(pl.lit(fill_value).alias(column))
        out.append((label, completed.with_columns(fill_exprs)))
    return out
