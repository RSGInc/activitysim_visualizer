"""Shared helpers for dashboard pages that filter by tour purpose."""

from __future__ import annotations

import polars as pl

from dashboard.pages._shared.common import column_options, nonempty_runs


def tour_purpose_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    col: str = "tour_purpose",
    total_display: str = "Total",
    total_raw: str = "all_tour_purposes",
) -> list[str]:
    raw_values = column_options(
        data_list,
        col,
        total_label=total_display,
        include_total=False,
        exclude=("All", "Total", total_raw),
    )
    has_total = any(
        total_raw in df.select(col).drop_nulls().to_series().cast(pl.Utf8).to_list()
        for _, df in nonempty_runs(data_list)
        if col in df.columns
    )
    options: list[str] = [total_display] if has_total else []
    options.extend(raw_values)
    return options or [total_display]


def tour_purpose_mapping(
    raw_values: list[str],
    *,
    total_display: str = "Total",
    total_raw: str = "all_tour_purposes",
) -> tuple[list[str], dict[str, str]]:
    mapping: dict[str, str] = {}
    if total_raw in raw_values:
        mapping[total_display] = total_raw
    for value in raw_values:
        if value not in {"All", "Total", total_raw}:
            mapping[str(value)] = str(value)
    return list(mapping), mapping


def raw_tour_purpose(
    display_value: str,
    *,
    total_display: str = "Total",
    total_raw: str = "all_tour_purposes",
) -> str:
    return total_raw if display_value == total_display else display_value
