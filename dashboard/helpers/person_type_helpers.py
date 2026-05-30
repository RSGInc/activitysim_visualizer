"""Shared helpers for person-type selector options, filters, and weighted rollups."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from dashboard.helpers.category_helpers import column_options, nonempty, ordered_category_values

if TYPE_CHECKING:
    from dashboard.state import DashboardState
    from runtime.config import Config


PERSON_TYPE_COL = "person_type"
ALL_PERSON_TYPES = "all_person_types"
DEFAULT_TOTAL_LABEL = "Total"


def _person_type_filter_expr(
    person_type: str | None,
    *,
    person_type_col: str = PERSON_TYPE_COL,
) -> pl.Expr:
    column = pl.col(person_type_col).cast(pl.Utf8)
    if person_type is None:
        return ~column.is_in([ALL_PERSON_TYPES, DEFAULT_TOTAL_LABEL])
    return column == person_type


def filter_person_type_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str | None,
    *,
    person_type_col: str = PERSON_TYPE_COL,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter count-style summaries to one person type or the detail-only subset."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        if person_type_col not in df.columns:
            out.append((label, df))
            continue
        out.append((label, df.filter(_person_type_filter_expr(person_type, person_type_col=person_type_col))))
    return out


def person_type_weights_by_run(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    person_type_col: str = PERSON_TYPE_COL,
    weight_col: str = "person_count",
) -> dict[str, pl.DataFrame]:
    """Build per-run person weights used to aggregate rate charts to total person type."""
    weights: dict[str, pl.DataFrame] = {}
    for label, df in nonempty(data_list):
        if person_type_col not in df.columns or weight_col not in df.columns:
            continue
        weights[label] = (
            df.with_columns(pl.col(person_type_col).cast(pl.Utf8))
            .filter(~pl.col(person_type_col).is_in([ALL_PERSON_TYPES, DEFAULT_TOTAL_LABEL]))
            .group_by(person_type_col)
            .agg(pl.col(weight_col).sum().alias(weight_col))
        )
    return weights


def filter_person_type_rates(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str | None,
    *,
    purpose_col: str,
    rate_col: str,
    person_weights: dict[str, pl.DataFrame],
    person_type_col: str = PERSON_TYPE_COL,
    weight_col: str = "person_count",
) -> list[tuple[str, pl.DataFrame]]:
    """Filter or roll up rate summaries to one person type or a weighted total."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        if person_type_col not in df.columns:
            out.append((label, df))
            continue

        typed = df.with_columns(pl.col(person_type_col).cast(pl.Utf8))
        if person_type not in {None, ALL_PERSON_TYPES, DEFAULT_TOTAL_LABEL}:
            out.append((label, typed.filter(pl.col(person_type_col) == person_type)))
            continue

        existing_total = typed.filter(pl.col(person_type_col) == ALL_PERSON_TYPES)
        if len(existing_total) > 0:
            out.append((label, existing_total.drop(person_type_col)))
            continue

        weights = person_weights.get(label)
        detail_rows = typed.filter(
            ~pl.col(person_type_col).is_in([ALL_PERSON_TYPES, DEFAULT_TOTAL_LABEL])
        )
        if weights is None or len(weights) == 0:
            aggregated = (
                detail_rows.group_by(purpose_col)
                .agg(pl.col(rate_col).mean().alias(rate_col))
                .sort(purpose_col)
            )
            out.append((label, aggregated))
            continue

        total_person_count = float(weights[weight_col].sum())
        aggregated = (
            detail_rows.join(weights, on=person_type_col, how="left")
            .with_columns(
                pl.col(weight_col).fill_null(0.0),
                (pl.col(rate_col) * pl.col(weight_col)).alias("_weighted_rate"),
            )
            .group_by(purpose_col)
            .agg(pl.col("_weighted_rate").sum().alias("_weighted_rate_sum"))
            .with_columns(
                pl.when(pl.lit(total_person_count) > 0)
                .then(pl.col("_weighted_rate_sum") / pl.lit(total_person_count))
                .otherwise(None)
                .alias(rate_col)
            )
            .select(purpose_col, rate_col)
            .sort(purpose_col)
        )
        out.append((label, aggregated))
    return out


def person_type_selector_options(
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
    state: DashboardState | None = None,
    cache_key: tuple[Any, ...] | None = None,
    category_id: str = "person_type",
    person_type_col: str = PERSON_TYPE_COL,
    total_raw: str = ALL_PERSON_TYPES,
    total_label: str = DEFAULT_TOTAL_LABEL,
) -> tuple[list[str], dict[str, str | None]]:
    """Build one person-type selector domain across multiple possible source summaries."""
    raw_values: list[str] = []
    for index, data_list in enumerate(summary_lists):
        if not data_list:
            continue
        per_list_cache_key = None
        if cache_key is not None:
            per_list_cache_key = (*cache_key, index)
        for raw_value in ordered_category_values(
            data_list,
            person_type_col,
            category_id=category_id,
            config=config,
            state=state,
            cache_key=per_list_cache_key,
        ):
            if raw_value not in raw_values:
                raw_values.append(raw_value)

    if not raw_values:
        return [total_label], {total_label: total_raw}

    return column_options(
        [("all", pl.DataFrame({person_type_col: raw_values}))],
        person_type_col,
        category_id=category_id,
        config=config,
        total_raw=total_raw,
        total_label=total_label,
    )
