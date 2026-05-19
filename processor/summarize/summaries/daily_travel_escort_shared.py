"""Shared escort-domain helpers for daily travel summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.summaries.summary_helpers import _summary_purpose_column

_CHILD_PERSON_TYPES = {"6", "7", "8"}
_STUDENT_SCHOOL_ESCORT_TYPES = ("not_escorted", "pure_escort", "ride_share")
_EXPLICIT_ESCORT_TYPES = ("pure_escort", "ride_share")


def _parent_only_escorted_tours(rd: RunData) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame()

    tours = rd.tours
    if "person_type" not in tours.columns and {"person_id", "person_type"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "person_type"),
            on="person_id",
            how="left",
        )

    if "person_type" not in tours.columns:
        return tours

    return tours.filter(
        ~pl.col("person_type").cast(pl.Utf8).is_in(sorted(_CHILD_PERSON_TYPES))
    )


def _adult_side_escorted_tours(rd: RunData) -> pl.DataFrame:
    tours = _parent_only_escorted_tours(rd)
    if tours.is_empty():
        return tours

    escorted = tours.filter(
        pl.col("school_esc_outbound").is_not_null()
        | pl.col("school_esc_inbound").is_not_null()
    ).filter(
        (pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase() != "none")
        | (pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase() != "none")
    )

    if escorted.is_empty():
        return escorted

    purpose_col = _summary_purpose_column(escorted)
    if not purpose_col:
        return escorted

    adult_escort = escorted.filter(
        pl.col(purpose_col).cast(pl.Utf8).str.to_lowercase() == "escort"
    )
    return adult_escort if not adult_escort.is_empty() else escorted


def _escort_type_matches(column: str, escort_type: str) -> pl.Expr:
    normalized = pl.col(column).cast(pl.Utf8).str.to_lowercase()
    if escort_type == "ride_share":
        return normalized.is_in(["ride_share", "rideshare", "ride share"])
    return normalized == escort_type


def _explicit_escort_label_present(column: str) -> pl.Expr:
    return _escort_type_matches(column, "pure_escort") | _escort_type_matches(
        column, "ride_share"
    )


def _escort_label_present(column: str) -> pl.Expr:
    normalized = pl.col(column).cast(pl.Utf8).str.to_lowercase()
    return (
        pl.col(column).is_not_null()
        & (normalized != "none")
        & (normalized.str.strip_chars() != "")
    )


def _both_escort_labels_present() -> pl.Expr:
    return _escort_label_present("school_esc_outbound") & _escort_label_present(
        "school_esc_inbound"
    )


def _both_explicit_escort_labels_present() -> pl.Expr:
    return _explicit_escort_label_present(
        "school_esc_outbound"
    ) & _explicit_escort_label_present("school_esc_inbound")


def _adult_side_explicit_escorted_tours(rd: RunData) -> pl.DataFrame:
    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return escorted
    return escorted.filter(
        _explicit_escort_label_present("school_esc_outbound")
        | _explicit_escort_label_present("school_esc_inbound")
    )


def _student_school_tours(rd: RunData) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame()

    tours = rd.tours
    if "person_type" not in tours.columns and {"person_id", "person_type"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "person_type"),
            on="person_id",
            how="left",
        )

    if "person_type" not in tours.columns:
        return pl.DataFrame()

    purpose_col = _summary_purpose_column(tours)
    if not purpose_col:
        return pl.DataFrame()

    return tours.filter(
        pl.col("person_type").cast(pl.Utf8).is_in(sorted(_CHILD_PERSON_TYPES))
        & (pl.col(purpose_col).cast(pl.Utf8).str.to_lowercase() == "school")
    )


def _student_households(rd: RunData) -> pl.DataFrame:
    hh_required = {"household_id", "finalweight"}
    per_required = {"household_id", "person_type"}
    if not hh_required.issubset(set(rd.hh.columns)) or not per_required.issubset(
        set(rd.per.columns)
    ):
        return pl.DataFrame()

    student_counts = (
        rd.per.filter(
            pl.col("household_id").is_not_null()
            & pl.col("person_type").cast(pl.Utf8).is_in(sorted(_CHILD_PERSON_TYPES))
        )
        .group_by("household_id")
        .agg(student_count=pl.len().cast(pl.Int64))
    )

    return (
        rd.hh.select("household_id", "finalweight")
        .join(student_counts, on="household_id", how="left")
        .with_columns(
            pl.col("student_count").fill_null(0).cast(pl.Int64),
            pl.col("finalweight").cast(pl.Float64),
        )
        .filter(pl.col("student_count") > 0)
    )


def _student_school_tours_with_household(rd: RunData) -> pl.DataFrame:
    tours = _student_school_tours(rd)
    if tours.is_empty():
        return tours

    if "household_id" not in tours.columns and {"person_id", "household_id"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "household_id"),
            on="person_id",
            how="left",
        )

    if "household_id" not in tours.columns:
        return pl.DataFrame()

    return tours.filter(pl.col("household_id").is_not_null())


def _adult_escorted_tours_with_household(rd: RunData) -> pl.DataFrame:
    tours = _adult_side_escorted_tours(rd)
    if tours.is_empty():
        return tours

    if "household_id" not in tours.columns and {"person_id", "household_id"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "household_id"),
            on="person_id",
            how="left",
        )

    if "household_id" not in tours.columns:
        return pl.DataFrame()

    return tours.filter(pl.col("household_id").is_not_null())


def _escort_type_expr(column: str) -> pl.Expr:
    normalized = pl.col(column).cast(pl.Utf8).str.to_lowercase()
    return (
        pl.when(
            pl.col(column).is_null()
            | (normalized == "none")
            | (normalized.str.strip_chars() == "")
        )
        .then(pl.lit("not_escorted"))
        .when(normalized == "pure_escort")
        .then(pl.lit("pure_escort"))
        .when(normalized.is_in(["ride_share", "rideshare", "ride share"]))
        .then(pl.lit("ride_share"))
        .otherwise(pl.lit("ride_share"))
    )


def _sorted_distance_bins(
    df: pl.DataFrame,
    *,
    direction_col: str,
    value_col: str,
) -> pl.DataFrame:
    return (
        df.with_columns(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col(direction_col).cast(pl.Utf8),
            pl.col(value_col).cast(pl.Float64),
            pl.when(pl.col("distance_bin") == "40+")
            .then(999)
            .otherwise(pl.col("distance_bin").cast(pl.Int64, strict=False))
            .alias("_sort_distance"),
        )
        .select("distance_bin", direction_col, value_col, "_sort_distance")
        .sort([direction_col, "_sort_distance"])
        .select("distance_bin", direction_col, value_col)
    )
