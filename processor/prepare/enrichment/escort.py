"""Escort field normalization for prepared tour tables."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.columns import (
    _materialize_column,
    _resolve_source_column,
)
from processor.prepare.enrichment.types import _PrepareState
from runtime.config import Config


def _sanitized_source_expr(df: pl.DataFrame, column: str) -> pl.Expr:
    dtype = df.schema.get(column)
    if dtype == pl.Utf8:
        return (
            pl.when(pl.col(column).str.strip_chars() == "")
            .then(None)
            .otherwise(pl.col(column))
        )
    return pl.col(column)


def _normalize_escort_expr(column: str, config: Config) -> pl.Expr:
    return pl.col(column).map_elements(
        config.normalize_escort_value,
        return_dtype=pl.Utf8,
    )


def _count_escorted_tour_ids_expr(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(0, dtype=pl.Int64)
    dtype = df.schema.get(column)
    if dtype != pl.Utf8:
        return (
            pl.when(pl.col(column).is_null())
            .then(pl.lit(0))
            .otherwise(pl.lit(1))
            .cast(pl.Int64)
        )
    cleaned = pl.col(column).str.strip_chars()
    return (
        pl.when(pl.col(column).is_null() | (cleaned == ""))
        .then(pl.lit(0))
        .otherwise(cleaned.str.split("_").list.len())
        .cast(pl.Int64)
    )


def _normalize_tour_escort_fields(
    tours: pl.DataFrame,
    config: Config,
) -> pl.DataFrame:
    tours = _materialize_column(
        tours,
        "school_esc_outbound",
        _resolve_source_column(tours, config.col_school_esc_outbound),
    )
    tours = _materialize_column(
        tours,
        "school_esc_inbound",
        _resolve_source_column(tours, config.col_school_esc_inbound),
    )
    tours = _materialize_column(
        tours,
        "num_escortees",
        _resolve_source_column(tours, config.col_num_escortees),
    )
    tours = _materialize_column(
        tours,
        "out_escorted_tour_ids",
        _resolve_source_column(tours, config.col_out_escorted_tour_ids),
    )
    tours = _materialize_column(
        tours,
        "inb_escorted_tour_ids",
        _resolve_source_column(tours, config.col_inb_escorted_tour_ids),
    )
    tours = _materialize_column(
        tours,
        "out_escorting_type",
        _resolve_source_column(tours, config.col_out_escorting_type),
    )
    tours = _materialize_column(
        tours,
        "inb_escorting_type",
        _resolve_source_column(tours, config.col_inb_escorting_type),
    )
    tours = _materialize_column(
        tours,
        "out_chauffeur_tour_id",
        _resolve_source_column(tours, config.col_out_chauffeur_tour_id),
    )
    tours = _materialize_column(
        tours,
        "inb_chauffeur_tour_id",
        _resolve_source_column(tours, config.col_inb_chauffeur_tour_id),
    )

    outbound_candidates = [
        column
        for column in (
            "school_esc_outbound",
            "out_escort_type",
            "out_escorting_type",
        )
        if column in tours.columns
    ]
    inbound_candidates = [
        column
        for column in (
            "school_esc_inbound",
            "inb_escort_type",
            "inb_escorting_type",
        )
        if column in tours.columns
    ]

    exprs: list[pl.Expr] = []
    if outbound_candidates:
        exprs.append(
            pl.coalesce(
                [_sanitized_source_expr(tours, column) for column in outbound_candidates]
            )
            .alias("_school_esc_outbound_raw")
        )
    if inbound_candidates:
        exprs.append(
            pl.coalesce(
                [_sanitized_source_expr(tours, column) for column in inbound_candidates]
            ).alias("_school_esc_inbound_raw")
        )

    result = tours.with_columns(exprs) if exprs else tours
    normalize_exprs: list[pl.Expr] = []
    if "_school_esc_outbound_raw" in result.columns:
        normalize_exprs.append(
            _normalize_escort_expr("_school_esc_outbound_raw", config).alias(
                "school_esc_outbound"
            )
        )
    if "_school_esc_inbound_raw" in result.columns:
        normalize_exprs.append(
            _normalize_escort_expr("_school_esc_inbound_raw", config).alias(
                "school_esc_inbound"
            )
        )
    current_num_escortees = (
        pl.col("num_escortees").cast(pl.Int64, strict=False)
        if "num_escortees" in result.columns
        else pl.lit(None, dtype=pl.Int64)
    )
    out_count = _count_escorted_tour_ids_expr(result, "out_escorted_tour_ids")
    inb_count = _count_escorted_tour_ids_expr(result, "inb_escorted_tour_ids")
    normalize_exprs.append(
        pl.coalesce([current_num_escortees, pl.max_horizontal(out_count, inb_count)])
        .fill_null(0)
        .cast(pl.Int64)
        .alias("num_escortees")
    )

    result = result.with_columns(normalize_exprs)
    drop_cols = [
        column
        for column in ("_school_esc_outbound_raw", "_school_esc_inbound_raw")
        if column in result.columns
    ]
    return result.drop(drop_cols) if drop_cols else result


def _normalize_escort_fields(state: _PrepareState, config: Config) -> _PrepareState:
    state.tours = _normalize_tour_escort_fields(state.tours, config)
    return state
