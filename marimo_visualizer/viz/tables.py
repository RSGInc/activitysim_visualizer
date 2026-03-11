"""Shared marimo table helpers and formatting utilities."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import polars as pl


FormatMapping = dict[str, Callable[[Any], str]]


def prepare_table_df(
    df: pl.DataFrame,
    column_order: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Normalize a Polars DataFrame for stable table rendering."""
    if df is None:
        return pl.DataFrame()

    result = df
    cat_cols = [col for col in result.columns if result[col].dtype == pl.Categorical]
    if cat_cols:
        result = result.with_columns([pl.col(col).cast(pl.Utf8) for col in cat_cols])

    if column_order:
        ordered = [col for col in column_order if col in result.columns]
        remaining = [col for col in result.columns if col not in ordered]
        result = result.select(ordered + remaining)

    return result


def make_table(
    mo: Any,
    df: pl.DataFrame,
    empty_text: str,
    column_order: Sequence[str] | None = None,
    format_mapping: FormatMapping | None = None,
    page_size: int = 10,
):
    """Render a single marimo table with stable ordering and formatting."""
    prepared = prepare_table_df(df, column_order=column_order)
    if len(prepared) == 0:
        return mo.md(empty_text)

    effective_page_size = min(max(len(prepared), 1), page_size)
    return mo.ui.table(
        prepared,
        pagination=len(prepared) > effective_page_size,
        page_size=effective_page_size,
        format_mapping=format_mapping,
    )


def make_run_tables(
    mo: Any,
    data_list: Sequence[tuple[str, pl.DataFrame]],
    empty_text: str,
    column_order: Sequence[str] | None = None,
    format_mapping: FormatMapping | Callable[[pl.DataFrame], FormatMapping | None] | None = None,
    page_size: int = 10,
):
    """Render one labeled table block per run."""
    blocks: list[Any] = []
    for label, df in data_list:
        prepared = prepare_table_df(df, column_order=column_order)
        if len(prepared) == 0:
            continue
        mapping = format_mapping(prepared) if callable(format_mapping) else format_mapping
        blocks.append(mo.md(f"#### {label}"))
        blocks.append(
            make_table(
                mo,
                prepared,
                empty_text=empty_text,
                format_mapping=mapping,
                page_size=page_size,
            )
        )
    if not blocks:
        return mo.md(empty_text)
    return mo.vstack(blocks, gap=0.5)


def kpi_format_mapping(
    df: pl.DataFrame,
    exclude_columns: Sequence[str] = ("Metric", "Purpose", "Geography", "HGEO", "WGEO"),
    digits: int = 2,
) -> FormatMapping:
    """Build numeric formatters for KPI-style tables."""
    exclude = set(exclude_columns)
    mapping: FormatMapping = {}
    for col in df.columns:
        if col in exclude:
            continue
        dtype = df[col].dtype
        if dtype.is_numeric():
            mapping[col] = lambda value, digits=digits: "" if value is None else f"{float(value):,.{digits}f}"
    return mapping


def percent_difference_format_mapping(
    df: pl.DataFrame,
    label_columns: Sequence[str] = ("Metric",),
    digits: int = 2,
) -> FormatMapping:
    """Build percent formatters for comparison tables."""
    labels = set(label_columns)
    mapping: FormatMapping = {}
    for col in df.columns:
        if col in labels:
            continue
        if df[col].dtype.is_numeric():
            mapping[col] = lambda value, digits=digits: "" if value is None else f"{float(value):.{digits}f}%"
    return mapping


def percent_difference_table(
    totals_list: Sequence[tuple[str, pl.DataFrame]],
    metrics: Sequence[tuple[str, str]],
) -> pl.DataFrame:
    """Build a base-run percent difference table using the first run as baseline."""
    if not totals_list:
        return pl.DataFrame()

    base_label, base_df = totals_list[0]
    rows: list[dict[str, object]] = []
    for metric, metric_label in metrics:
        base_val = float(base_df[metric][0]) if metric in base_df.columns and len(base_df) > 0 else 0.0
        row: dict[str, object] = {"Metric": metric_label, base_label: 0.0}
        for run_label, df in totals_list[1:]:
            value = float(df[metric][0]) if metric in df.columns and len(df) > 0 else 0.0
            row[run_label] = ((value - base_val) / base_val * 100.0) if base_val else 0.0
        rows.append(row)
    return pl.DataFrame(rows)
