"""Shared helpers for dashboard pages that filter by tour purpose."""

from __future__ import annotations

import polars as pl

from dashboard.pages._shared.common import (
    category_display_mapping,
    category_selector_options,
    column_value_union,
    selector_domain,
)
from runtime.config import Config


def tour_purpose_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    col: str = "tour_purpose",
    total_display: str = "Total",
    total_raw: str = "all_tour_purposes",
    config: Config | None = None,
) -> list[str]:
    if config is not None:
        options, _ = category_selector_options(
            data_list,
            column=col,
            category_id="tour_purpose",
            config=config,
            total_raw=total_raw,
            total_display=total_display,
            exclude=("All", "Total"),
        )
    else:
        raw_values = column_value_union(data_list, col)
        include_total = total_raw in raw_values or not raw_values
        options, _ = selector_domain(
            raw_values,
            include_total=include_total,
            total_raw=total_raw,
            total_display=total_display,
            exclude=("All", "Total"),
        )
    return options or [total_display]


def tour_purpose_mapping(
    raw_values: list[str],
    *,
    total_display: str = "Total",
    total_raw: str = "all_tour_purposes",
    config: Config | None = None,
) -> tuple[list[str], dict[str, str]]:
    include_total = total_raw in raw_values or not raw_values
    if config is not None:
        options, mapping = category_display_mapping(
            raw_values,
            category_id="tour_purpose",
            config=config,
            include_total=include_total,
            total_raw=total_raw,
            total_display=total_display,
            exclude=("All", "Total"),
        )
    else:
        ordered_raw_values = sorted(str(value) for value in raw_values)
        options: list[str] = []
        mapping: dict[str, str] = {}
        if include_total and total_raw in ordered_raw_values:
            options.append(total_display)
            mapping[total_display] = total_raw
        elif include_total:
            options.append(total_display)
        for raw_value in ordered_raw_values:
            if raw_value in {"All", "Total"} or raw_value == total_raw:
                continue
            options.append(raw_value)
            mapping[raw_value] = raw_value
    return options, mapping


def raw_tour_purpose(
    display_value: str,
    *,
    total_display: str = "Total",
    total_raw: str = "all_tour_purposes",
) -> str:
    return total_raw if display_value == total_display else display_value
