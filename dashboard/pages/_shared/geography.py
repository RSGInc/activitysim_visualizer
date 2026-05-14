"""Shared geography helpers for dashboard page modules."""

from __future__ import annotations

import polars as pl

from dashboard.pages._shared.common import first_nonempty_frame, nonempty_runs


def rename_present(df: pl.DataFrame, mapping: dict[str, str]) -> pl.DataFrame:
    rename_map = {
        source: target
        for source, target in mapping.items()
        if source in df.columns and target not in df.columns
    }
    return df.rename(rename_map) if rename_map else df


def normalize_geography_columns(
    df: pl.DataFrame,
    *,
    geo_level_col: str = "geography_level",
    geo_type_col: str = "geography_type",
    geo_col: str = "geography",
    geo_id_col: str = "geography_id",
) -> pl.DataFrame:
    rename_map: dict[str, str] = {}
    if geo_type_col in df.columns and geo_level_col not in df.columns:
        rename_map[geo_type_col] = geo_level_col
    if geo_id_col in df.columns and geo_col not in df.columns:
        rename_map[geo_id_col] = geo_col
    return df.rename(rename_map) if rename_map else df


def geo_level_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    total_label: str = "All",
    preferred_order: list[str] | None = None,
    support_origin_destination: bool = False,
) -> list[str]:
    first_df = first_nonempty_frame(data_list)
    if first_df is None:
        return [total_label]

    vals: list[str]
    if "geography_level" in first_df.columns:
        vals = (
            first_df.select("geography_level")
            .drop_nulls()
            .unique()
            .to_series()
            .cast(pl.Utf8)
            .to_list()
        )
    elif support_origin_destination and {
        "origin_geography_level",
        "destination_geography_level",
    }.issubset(first_df.columns):
        vals = (
            pl.concat(
                [
                    first_df["origin_geography_level"].cast(pl.Utf8),
                    first_df["destination_geography_level"].cast(pl.Utf8),
                ]
            )
            .drop_nulls()
            .unique()
            .to_list()
        )
    else:
        return [total_label]

    if preferred_order:
        ordered = [value for value in preferred_order if value in vals]
        extras = sorted(v for v in vals if v not in preferred_order and v != total_label)
        return ordered + extras if ordered or extras else [total_label]

    return [total_label] + sorted(v for v in vals if v != total_label)


def filter_geo_level(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
    *,
    total_values: tuple[str, ...] = ("All", "Total"),
    support_origin_destination: bool = False,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty_runs(data_list):
        if "geography_level" in df.columns and geo_level not in total_values:
            df = df.with_columns(pl.col("geography_level").cast(pl.Utf8)).filter(
                pl.col("geography_level") == geo_level
            )
        elif support_origin_destination and {
            "origin_geography_level",
            "destination_geography_level",
        }.issubset(df.columns) and geo_level not in total_values:
            df = df.with_columns(
                pl.col("origin_geography_level").cast(pl.Utf8),
                pl.col("destination_geography_level").cast(pl.Utf8),
            ).filter(
                (pl.col("origin_geography_level") == geo_level)
                & (pl.col("destination_geography_level") == geo_level)
            )
        out.append((label, df))
    return out
