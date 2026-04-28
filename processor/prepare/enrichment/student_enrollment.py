"""Prepare-stage student type and enrollment derivations."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.columns import resolve_source_column
from processor.prepare.enrichment.types import _PrepareState
from runtime.config import Config, StudentTypeConfig


_TRUE_TOKENS = {"true", "1", "yes", "y", "t"}


def _boolish_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(sorted(_TRUE_TOKENS))
        .fill_null(False)
    )


def _boolish_expr_from_candidates(
    df: pl.DataFrame,
    candidates: list[str],
) -> pl.Expr:
    source = resolve_source_column(df, candidates)
    if source is None:
        return pl.lit(False)
    return _boolish_expr(source)


def _membership_expr(
    df: pl.DataFrame,
    column: str,
    values: tuple[str, ...],
) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(False)
    return pl.col(column).cast(pl.Utf8).is_in(list(values)).fill_null(False)


def _student_type_defaults_to_university(entry: StudentTypeConfig) -> bool:
    text = f"{entry.label} {' '.join(entry.land_use_columns)}".lower()
    return "univ" in text or "college" in text


def _default_student_types(state: _PrepareState) -> list[StudentTypeConfig]:
    defaults: list[StudentTypeConfig] = []
    if any(
        column in state.land_use.columns
        for column in ("ENROLLGRADEKto8", "ENROLLGRADE9to12")
    ):
        school_columns = tuple(
            column
            for column in ("ENROLLGRADEKto8", "ENROLLGRADE9to12")
            if column in state.land_use.columns
        )
        if school_columns:
            defaults.append(
                StudentTypeConfig(
                    label="School",
                    land_use_columns=school_columns,
                )
            )
    if "COLLEGEENROLL" in state.land_use.columns:
        defaults.append(
            StudentTypeConfig(
                label="University",
                land_use_columns=("COLLEGEENROLL",),
            )
        )
    return defaults


def _resolved_student_types(state: _PrepareState, config: Config) -> list[StudentTypeConfig]:
    return config.student_types or _default_student_types(state)


def _person_match_expr(state: _PrepareState, entry: StudentTypeConfig) -> pl.Expr:
    per = state.per
    university_expr = _boolish_expr_from_candidates(per, ["is_university", "major_uni"])
    student_expr = _boolish_expr_from_candidates(per, ["is_student", "student"])
    selector = entry.person
    if selector is None:
        if _student_type_defaults_to_university(entry):
            return university_expr
        return student_expr & (~university_expr)

    expr = pl.lit(True)
    if selector.is_university is not None:
        expr = expr & (university_expr if selector.is_university else ~university_expr)
    if selector.school_segment:
        expr = expr & _membership_expr(per, "school_segment", selector.school_segment)
    if selector.SCHG:
        expr = expr & _membership_expr(per, "SCHG", selector.SCHG)
    if selector.pstudent:
        expr = expr & _membership_expr(per, "pstudent", selector.pstudent)
    return expr


def _derive_person_student_type(
    state: _PrepareState, student_types: list[StudentTypeConfig]
) -> None:
    if state.per.is_empty() or not student_types:
        return

    student_type_expr = pl.lit(None, dtype=pl.Utf8)
    for entry in reversed(student_types):
        student_type_expr = (
            pl.when(_person_match_expr(state, entry))
            .then(pl.lit(entry.label))
            .otherwise(student_type_expr)
        )
    state.per = state.per.with_columns(student_type_expr.alias("student_type"))


def _build_land_use_overlay(
    state: _PrepareState,
    config: Config,
    student_types: list[StudentTypeConfig],
) -> pl.DataFrame | None:
    if state.land_use.is_empty() or not student_types:
        return None

    key_columns = [
        column
        for column in [config.maz_col, config.taz_col, config.geography_landuse_col]
        if column and column in state.land_use.columns
    ]
    if not key_columns:
        return None

    overlays: list[pl.DataFrame] = []
    for entry in student_types:
        present_columns = [
            column for column in entry.land_use_columns if column in state.land_use.columns
        ]
        if not present_columns:
            continue

        enrollment_expr = pl.lit(0.0)
        for column in present_columns:
            enrollment_expr = enrollment_expr + pl.col(column).cast(pl.Float64)
        overlay = (
            state.land_use.select([*key_columns, *present_columns])
            .with_columns(
                pl.lit(entry.label).alias("student_type"),
                enrollment_expr.alias("enrollment_count"),
            )
            .select([*key_columns, "student_type", "enrollment_count"])
            .filter(pl.col("enrollment_count").is_not_null())
        )
        overlays.append(overlay)

    if not overlays:
        return None
    return pl.concat(overlays, how="diagonal_relaxed")


def _derive_land_use_enrollment(
    state: _PrepareState,
    config: Config,
    student_types: list[StudentTypeConfig],
) -> None:
    overlay = _build_land_use_overlay(state, config, student_types)
    if overlay is None or overlay.is_empty():
        return
    state.land_use = pl.concat([state.land_use, overlay], how="diagonal_relaxed")


def _derive_student_enrollment(
    state: _PrepareState,
    config: Config,
) -> _PrepareState:
    student_types = _resolved_student_types(state, config)
    _derive_person_student_type(state, student_types)
    _derive_land_use_enrollment(state, config, student_types)
    return state


__all__ = ["_derive_student_enrollment"]
