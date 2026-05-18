"""Shared helpers for selector domains, labels, ordering, and category completion."""

from __future__ import annotations

from typing import Any

import polars as pl

from dashboard.state import DashboardState
from runtime.config import Config


def nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def column_value_union(
    data_list: list[tuple[str, pl.DataFrame]],
    column: str,
    *,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
) -> list[str]:
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
    return state.get_or_create_cached(
        "selector_domain",
        *cache_key,
        factory=_compute,
    )


def ordered_category_values(
    data_list: list[tuple[str, pl.DataFrame]],
    column: str,
    *,
    category_id: str | None = None,
    config: Config | None = None,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
) -> list[str]:
    values = column_value_union(
        data_list,
        column,
        state=state,
        cache_key=cache_key,
    )
    if category_id is None or config is None:
        return values
    return config.ordered_values(category_id, values)


def raw_display_options(
    raw_values: list[str],
    *,
    category_id: str | None = None,
    config: Config | None = None,
    total_raw: str | None = None,
    total_label: str | None = None,
) -> tuple[list[str], dict[str, str | None]]:
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


def complete_category_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    category_col: str,
    category_values: list[str],
    value_cols: tuple[str, ...],
    extra_fill_values: dict[str, Any] | None = None,
) -> list[tuple[str, pl.DataFrame]]:
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
