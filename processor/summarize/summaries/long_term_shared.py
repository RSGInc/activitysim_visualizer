"""Shared helper utilities for long-term summaries."""

from __future__ import annotations

import polars as pl

from processor.summarize.summaries.summary_helpers import (
    ALL_PERSON_TYPES,
    _all_person_types_rollup,
)
from runtime.config import Config


def _worker_filter_expr() -> pl.Expr:
    return (
        pl.col("is_worker")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "worker"])
    )


def _internal_non_wfh_workers(persons: pl.DataFrame) -> pl.DataFrame:
    """Return workers with an internal, non-home workplace assignment."""
    required = {"is_worker", "workplace_zone_id", "work_from_home"}
    if not required.issubset(persons.columns):
        return persons.head(0)

    external_expr: pl.Expr | None = None
    if "is_external_worker" in persons.columns:
        external_expr = (
            pl.col("is_external_worker")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes", "external"])
            .fill_null(True)
        )
    if "external_workplace_zone_id" in persons.columns:
        external_location = (
            pl.col("external_workplace_zone_id").cast(pl.Float64, strict=False) > 0
        ).fill_null(False)
        external_expr = (
            external_location
            if external_expr is None
            else external_expr | external_location
        )
    if external_expr is None:
        return persons.head(0)

    works_from_home = (
        pl.col("work_from_home")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "work_from_home", "home"])
    )
    return persons.filter(
        _worker_filter_expr()
        & (pl.col("workplace_zone_id").cast(pl.Float64, strict=False) > 0)
        & ~works_from_home
        & ~external_expr.fill_null(True)
    )


def _student_filter_expr() -> pl.Expr:
    return (
        pl.col("is_student")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "student"])
    )


def _person_type_label_expr(config: Config) -> pl.Expr:
    return (
        pl.col("person_type")
        .map_elements(
            lambda x: (
                "All Person Types"
                if x == ALL_PERSON_TYPES
                else config.person_type_label(x)
            ),
            return_dtype=pl.Utf8,
        )
        .alias("person_type_label")
    )


def _person_type_distribution_with_total(
    base: pl.DataFrame,
    *,
    category_col: str,
    value_col: str = "person_count",
) -> pl.DataFrame:
    by_person_type = base.group_by(["person_type", category_col]).agg(
        pl.col("finalweight").sum().alias(value_col)
    )
    all_person_types = _all_person_types_rollup(
        by_person_type,
        group_cols=[category_col],
        value_col=value_col,
    ).select("person_type", category_col, value_col)
    return pl.concat([by_person_type, all_person_types], how="vertical")
