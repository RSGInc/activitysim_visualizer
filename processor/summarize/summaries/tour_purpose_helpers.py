"""Shared helpers for normalized tour purpose grouping."""

from __future__ import annotations

import polars as pl

from runtime.config import Config

ALL_TOUR_PURPOSES = "all_tour_purposes"
SUMMARY_TOUR_PURPOSE = "summary_tour_purpose"
_ATWORK_PURPOSE_ALIASES = {"eat", "maint", "business"}
_SCHOOL_PURPOSE_ALIASES = {"university", "univ", "college"}


def with_summary_tour_purpose(
    df: pl.DataFrame,
    config: Config,
    *,
    source_col: str = "tour_purpose",
    output_col: str = SUMMARY_TOUR_PURPOSE,
) -> pl.DataFrame:
    """Attach a normalized summary tour purpose column according to config flags."""
    if source_col not in df.columns:
        return df
    return df.with_columns(
        summary_tour_purpose_expr(
            config,
            available_columns=set(df.columns),
            source_col=source_col,
        ).alias(output_col)
    )


def purpose_column(df: pl.DataFrame, fallback: str = "tour_purpose") -> str:
    """Return the preferred prepared column for summary-time purpose grouping."""
    if SUMMARY_TOUR_PURPOSE in df.columns:
        return SUMMARY_TOUR_PURPOSE
    if fallback in df.columns:
        return fallback
    return ""


def summary_tour_purpose_expr(
    config: Config,
    *,
    available_columns: set[str],
    source_col: str = "tour_purpose",
) -> pl.Expr:
    """Return an expression that normalizes summary-time tour purpose values."""
    purpose = pl.col(source_col).cast(pl.Utf8)
    normalized_text = purpose.str.strip_chars().str.to_lowercase()
    expr = purpose

    if config.group_school_tour_purposes:
        expr = (
            pl.when(normalized_text == ALL_TOUR_PURPOSES)
            .then(purpose)
            .when(normalized_text.is_in(_SCHOOL_PURPOSE_ALIASES))
            .then(pl.lit("school"))
            .otherwise(expr)
        )

    if config.group_atwork_tour_purposes:
        atwork_condition = normalized_text.is_in(_ATWORK_PURPOSE_ALIASES)
        if "tour_category" in available_columns:
            atwork_category_text = (
                pl.col("tour_category")
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.to_lowercase()
            )
            atwork_condition = pl.col("tour_category").is_not_null() & (
                atwork_category_text == "atwork"
            )
        elif "atwork_subtour_frequency" in available_columns:
            atwork_text = (
                pl.col("atwork_subtour_frequency")
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.to_lowercase()
            )
            atwork_condition = atwork_condition | (
                pl.col("atwork_subtour_frequency").is_not_null()
                & (atwork_text != "")
                & (atwork_text != "no_subtours")
            )

        expr = (
            pl.when(
                expr.cast(pl.Utf8).str.strip_chars().str.to_lowercase()
                == ALL_TOUR_PURPOSES
            )
            .then(expr)
            .when(atwork_condition)
            .then(pl.lit("atwork"))
            .otherwise(expr)
        )

    if "tour_category" in available_columns:
        joint_text = (
            pl.col("tour_category").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        )
        if config.group_joint_tour_purposes:
            expr = (
                pl.when(
                    expr.cast(pl.Utf8).str.strip_chars().str.to_lowercase()
                    == ALL_TOUR_PURPOSES
                )
                .then(expr)
                .when(pl.col("tour_category").is_not_null() & (joint_text == "joint"))
                .then(pl.lit("joint"))
                .otherwise(expr)
            )
        else:
            expr = (
                pl.when(
                    expr.cast(pl.Utf8).str.strip_chars().str.to_lowercase()
                    == ALL_TOUR_PURPOSES
                )
                .then(expr)
                .when(pl.col("tour_category").is_not_null() & (joint_text == "joint"))
                .then(pl.format("joint_{}", expr))
                .otherwise(expr)
            )

    return expr.cast(pl.Utf8)
