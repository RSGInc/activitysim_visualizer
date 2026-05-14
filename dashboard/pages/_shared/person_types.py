"""Shared person-type helpers for dashboard page modules."""

from __future__ import annotations

import polars as pl

from dashboard.pages._shared.common import nonempty_runs
from runtime.config import Config


def person_type_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    person_type_col: str = "person_type",
    all_value: str = "all_person_types",
) -> list[str]:
    person_types = set()
    for _, df in nonempty_runs(data_list):
        if person_type_col not in df.columns:
            continue
        person_types.update(
            df.select(person_type_col).drop_nulls().to_series().cast(pl.Utf8).to_list()
        )
    return sorted(str(person_type) for person_type in person_types) or [all_value]


def person_type_display_mapping(
    raw_values: list[str],
    config: Config,
    *,
    all_value: str = "all_person_types",
    total_display: str = "Total",
) -> tuple[list[str], dict[str, str | None]]:
    label_to_person_type: dict[str, str | None] = {}
    label_to_person_type[total_display] = all_value if all_value in raw_values else None
    for person_type in raw_values:
        if person_type in {all_value, total_display}:
            continue
        label_to_person_type[config.person_type_label(person_type)] = person_type
    return list(label_to_person_type), label_to_person_type


def filter_person_type_frame(
    df: pl.DataFrame,
    person_type: str | None,
    *,
    person_type_col: str = "person_type",
    all_values: tuple[str, ...] = ("all_person_types", "Total"),
) -> pl.DataFrame:
    person_type_expr = pl.col(person_type_col).cast(pl.Utf8)
    if person_type is None:
        return df.filter(~person_type_expr.is_in(list(all_values)))
    return df.filter(person_type_expr == person_type)


def filter_person_type_runs(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str | None,
    *,
    person_type_col: str = "person_type",
    all_values: tuple[str, ...] = ("all_person_types", "Total"),
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty_runs(data_list):
        if person_type_col not in df.columns:
            out.append((label, df))
            continue
        out.append(
            (
                label,
                filter_person_type_frame(
                    df,
                    person_type,
                    person_type_col=person_type_col,
                    all_values=all_values,
                ),
            )
        )
    return out
