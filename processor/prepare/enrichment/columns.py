"""Column resolution and lightweight DataFrame helpers for prepare enrichment."""

from __future__ import annotations

import polars as pl


def _resolve_source_column(
    df: pl.DataFrame,
    preferred: str | list[str] | None,
    *,
    fallbacks: tuple[str, ...] = (),
    require_non_numeric: bool = False,
) -> str | None:
    """Return the first matching source column for one semantic concept."""
    candidates: list[str] = []
    if isinstance(preferred, list):
        preferred_candidates = preferred
    elif preferred is None:
        preferred_candidates = []
    else:
        preferred_candidates = [preferred]

    for candidate in [*preferred_candidates, *fallbacks]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        return None

    if require_non_numeric:
        for candidate in candidates:
            if candidate in df.columns and not df[candidate].dtype.is_numeric():
                return candidate

    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def resolve_source_column(
    df: pl.DataFrame,
    preferred: str | list[str] | None,
    *,
    fallbacks: tuple[str, ...] = (),
    require_non_numeric: bool = False,
) -> str | None:
    """Public wrapper for config-aware source-column resolution."""
    return _resolve_source_column(
        df,
        preferred,
        fallbacks=fallbacks,
        require_non_numeric=require_non_numeric,
    )


def _materialize_column(
    df: pl.DataFrame,
    target: str,
    source: str | None,
    *,
    overwrite: bool = False,
) -> pl.DataFrame:
    """Alias a source column into a canonical target column when needed."""
    if source is None or source not in df.columns:
        return df
    if source == target and not overwrite:
        return df
    if target in df.columns and not overwrite:
        return df
    return df.with_columns(pl.col(source).alias(target))


def _materialize_preferred_column(
    df: pl.DataFrame,
    target: str,
    preferred: str | list[str] | None,
    *,
    fallbacks: tuple[str, ...] = (),
    require_non_numeric: bool = False,
) -> pl.DataFrame:
    """Materialize a preferred source column, replacing numeric placeholders."""
    source = resolve_source_column(
        df,
        preferred,
        fallbacks=fallbacks,
        require_non_numeric=require_non_numeric,
    )
    overwrite = False
    if (
        source is not None
        and source != target
        and target in df.columns
        and require_non_numeric
        and df[target].dtype.is_numeric()
        and not df[source].dtype.is_numeric()
    ):
        overwrite = True
    return _materialize_column(df, target, source, overwrite=overwrite)


def _cast_if_present(df: pl.DataFrame, casts: dict[str, pl.DataType]) -> pl.DataFrame:
    exprs = [
        pl.col(col).cast(dtype).alias(col)
        for col, dtype in casts.items()
        if col in df.columns
    ]
    return df.with_columns(exprs) if exprs else df


def _has_columns(df: pl.DataFrame, *columns: str) -> bool:
    return all(column in df.columns for column in columns)


__all__ = ["resolve_source_column"]
