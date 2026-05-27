"""Shared auto-sufficiency helpers for prepare enrichment."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.types import _PrepareState
from processor.prepare.enrichment.zones import _record_prepare_metric
from runtime.config import Config

_AUTO_SUFFICIENCY_REF_COLUMNS = {
    "licensed_drivers": "LICENSEDDRIVERS",
    "workers": "_autosuff_workers",
    "adults": "_autosuff_adults",
}


def _truthy_expr(
    column_name: str,
    *,
    true_tokens: tuple[str, ...] = ("true", "1", "yes"),
) -> pl.Expr:
    return (
        pl.col(column_name)
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(list(true_tokens))
    )


def autosuff_reference_column(config: Config) -> str:
    return _AUTO_SUFFICIENCY_REF_COLUMNS[config.prepare_auto_sufficiency.basis]


def autosuff_basis_noun(config: Config) -> str:
    return {
        "licensed_drivers": "licensed drivers",
        "workers": "workers",
        "adults": "adults",
    }[config.prepare_auto_sufficiency.basis]


def derive_household_autosuff_counts(state: _PrepareState) -> None:
    if "household_id" not in state.hh.columns or "household_id" not in state.per.columns:
        return

    if {"household_id", "has_license"}.issubset(state.per.columns):
        licensed_drivers = (
            state.per.filter(
                pl.col("household_id").is_not_null()
                & pl.col("has_license").is_not_null()
            )
            .group_by("household_id")
            .agg(
                _truthy_expr(
                    "has_license",
                    true_tokens=("true", "1", "yes", "licensed"),
                )
                .sum()
                .cast(pl.Int32)
                .alias("LICENSEDDRIVERS")
            )
        )
        state.hh = state.hh.join(
            licensed_drivers, on="household_id", how="left"
        ).with_columns(pl.col("LICENSEDDRIVERS").fill_null(0).cast(pl.Int32))

    for person_col, output_col in (
        ("is_worker", "_autosuff_workers"),
        ("adult", "_autosuff_adults"),
    ):
        if {"household_id", person_col}.issubset(state.per.columns):
            counts = (
                state.per.filter(
                    pl.col("household_id").is_not_null()
                    & pl.col(person_col).is_not_null()
                )
                .group_by("household_id")
                .agg(_truthy_expr(person_col).sum().cast(pl.Int32).alias(output_col))
            )
            state.hh = state.hh.join(counts, on="household_id", how="left").with_columns(
                pl.col(output_col).fill_null(0).cast(pl.Int32)
            )


def apply_autosufficiency(
    df: pl.DataFrame,
    *,
    state: _PrepareState,
    config: Config,
    metric_id: str,
) -> pl.DataFrame:
    if "AUTOSUFF" in df.columns:
        return df

    ref_col = autosuff_reference_column(config)
    required_columns = ["HHVEH", ref_col]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        total = df.filter(pl.col("HHVEH").is_not_null()).height if "HHVEH" in df.columns else 0
        _record_prepare_metric(
            state,
            metric_id,
            total=total,
            unresolved=total,
            details={
                "basis": config.prepare_auto_sufficiency.basis,
                "missing_columns": tuple(missing_columns),
            },
        )
        return df

    return df.with_columns(
        pl.when(pl.col("HHVEH") == 0)
        .then(0)
        .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") < pl.col(ref_col)))
        .then(1)
        .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") >= pl.col(ref_col)))
        .then(2)
        .otherwise(0)
        .cast(pl.Int32)
        .alias("AUTOSUFF")
    )

