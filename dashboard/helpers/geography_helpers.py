"""Shared dashboard helpers for geography selector discovery, normalization, and filters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from dashboard.helpers.category_helpers import first_nonempty_frame, nonempty

if TYPE_CHECKING:
    from runtime.config import Config


PREFERRED_TYPED_GEO_ORDER = [
    "all_geographies",
    "district",
    "taz",
    "maz",
]
AGGREGATE_GEOGRAPHY_LEVEL = "all_geographies"
ALL_WITHIN_LEVEL_VALUE = "All"
DEFAULT_GEO_LEVEL_COL = "geography_level"
DEFAULT_GEO_COL = "geography"
DEFAULT_GEO_TYPE_COL = "geography_type"
DEFAULT_GEO_ID_COL = "geography_id"


def is_all_geographies(value: str | None) -> bool:
    """Return whether a selector value targets the cross-level aggregate geography."""
    return str(value) == AGGREGATE_GEOGRAPHY_LEVEL


def is_all_within_level(value: str | None) -> bool:
    """Return whether a selector value means all members within one level."""
    return str(value) in {ALL_WITHIN_LEVEL_VALUE, "All", "Total"}


def visible_geography_levels(
    values: list[str] | set[str] | tuple[str, ...],
    *,
    config: Config,
) -> list[str]:
    """Return geography levels that should be exposed in dashboard selectors."""
    visible: list[str] = []
    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            continue
        if value.lower() == "maz" and not config.enable_maz_geographies:
            continue
        if value not in visible:
            visible.append(value)
    return visible


def ordered_visible_geography_levels(
    values: list[str] | set[str] | tuple[str, ...],
    *,
    config: Config,
) -> list[str]:
    """Return visible geography levels in preferred dashboard order."""
    visible = visible_geography_levels(values, config=config)
    ordered = [value for value in PREFERRED_TYPED_GEO_ORDER if value in visible]
    extras = sorted(value for value in visible if value not in PREFERRED_TYPED_GEO_ORDER)
    return ordered + extras


def detail_geography_levels(
    values: list[str] | set[str] | tuple[str, ...],
    *,
    config: Config,
) -> list[str]:
    """Return selector geography levels, hiding only MAZ when disabled."""
    return ordered_visible_geography_levels(values, config=config)


def rename_present(df: pl.DataFrame, mapping: dict[str, str]) -> pl.DataFrame:
    """Rename only columns that exist and do not already collide with the target name."""
    rename_map = {
        source: target
        for source, target in mapping.items()
        if source in df.columns and target not in df.columns
    }
    return df.rename(rename_map) if rename_map else df


def normalize_geography_columns(
    df: pl.DataFrame,
    *,
    geography_level_col: str = DEFAULT_GEO_LEVEL_COL,
    geography_col: str = DEFAULT_GEO_COL,
    geography_type_col: str = DEFAULT_GEO_TYPE_COL,
    geography_id_col: str = DEFAULT_GEO_ID_COL,
) -> pl.DataFrame:
    """Normalize alternative geography column names onto the page-contract names."""
    rename_map: dict[str, str] = {}
    if geography_type_col in df.columns and geography_level_col not in df.columns:
        rename_map[geography_type_col] = geography_level_col
    if geography_id_col in df.columns and geography_col not in df.columns:
        rename_map[geography_id_col] = geography_col
    return df.rename(rename_map) if rename_map else df


def normalize_geography_data(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    geography_level_col: str = DEFAULT_GEO_LEVEL_COL,
    geography_col: str = DEFAULT_GEO_COL,
    geography_type_col: str = DEFAULT_GEO_TYPE_COL,
    geography_id_col: str = DEFAULT_GEO_ID_COL,
) -> list[tuple[str, pl.DataFrame]]:
    """Normalize geography columns across a run-indexed summary list."""
    if not data_list:
        return []
    return [
        (
            label,
            normalize_geography_columns(
                df,
                geography_level_col=geography_level_col,
                geography_col=geography_col,
                geography_type_col=geography_type_col,
                geography_id_col=geography_id_col,
            ),
        )
        for label, df in nonempty(data_list)
    ]


def geography_level_option_set(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    geography_level_col: str = DEFAULT_GEO_LEVEL_COL,
    geography_type_col: str = DEFAULT_GEO_TYPE_COL,
    origin_level_col: str = "origin_geography_level",
    destination_level_col: str = "destination_geography_level",
) -> set[str]:
    """Return geography levels available in any usable run for one summary."""
    if not data_list:
        return set()

    available: set[str] = set()
    for _, df in nonempty(data_list):
        if geography_level_col in df.columns:
            values = (
                df.select(geography_level_col)
                .drop_nulls()
                .unique()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            )
            available.update(values)
        elif geography_type_col in df.columns:
            values = (
                df.select(geography_type_col)
                .drop_nulls()
                .unique()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            )
            available.update(values)
        elif {origin_level_col, destination_level_col}.issubset(df.columns):
            origin_values = set(
                df[origin_level_col].cast(pl.Utf8).drop_nulls().unique().to_list()
            )
            destination_values = set(
                df[destination_level_col].cast(pl.Utf8).drop_nulls().unique().to_list()
            )
            available.update(origin_values & destination_values)
    return available


def geography_level_options(
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
    total_label: str = "Total",
) -> list[str]:
    """Return ordered geography level options discovered across one or more summaries."""
    available_sets = [
        geography_level_option_set(summary)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [available for available in available_sets if available]
    if not available_sets:
        return [total_label]
    ordered = detail_geography_levels(set().union(*available_sets), config=config)
    return ordered or [total_label]


def geography_id_option_set(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    geo_level: str,
    *,
    geography_level_col: str = DEFAULT_GEO_LEVEL_COL,
    geography_col: str = DEFAULT_GEO_COL,
    geography_type_col: str = DEFAULT_GEO_TYPE_COL,
    geography_id_col: str = DEFAULT_GEO_ID_COL,
    origin_level_col: str = "origin_geography_level",
    origin_id_col: str = "origin_geography_id",
) -> set[str]:
    """Return geography ids available at one geography level in one summary."""
    if not data_list:
        return set()

    available: set[str] = set()
    for _, df in nonempty(data_list):
        if {geography_type_col, geography_id_col}.issubset(df.columns):
            values = (
                df.with_columns(
                    pl.col(geography_type_col).cast(pl.Utf8),
                    pl.col(geography_id_col).cast(pl.Utf8),
                )
                .filter(pl.col(geography_type_col) == geo_level)
                .select(geography_id_col)
                .drop_nulls()
                .unique()
                .to_series()
                .to_list()
            )
            available.update(str(value) for value in values)
        elif {geography_level_col, geography_col}.issubset(df.columns):
            values = (
                df.with_columns(
                    pl.col(geography_level_col).cast(pl.Utf8),
                    pl.col(geography_col).cast(pl.Utf8),
                )
                .filter(pl.col(geography_level_col) == geo_level)
                .select(geography_col)
                .drop_nulls()
                .unique()
                .to_series()
                .to_list()
            )
            available.update(str(value) for value in values)
        elif {origin_level_col, origin_id_col}.issubset(df.columns):
            values = (
                df.with_columns(
                    pl.col(origin_level_col).cast(pl.Utf8),
                    pl.col(origin_id_col).cast(pl.Utf8),
                )
                .filter(pl.col(origin_level_col) == geo_level)
                .select(origin_id_col)
                .drop_nulls()
                .unique()
                .to_series()
                .to_list()
            )
            available.update(str(value) for value in values)
    return available


def geography_options_for_level(
    geo_level: str,
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
    all_within_level_label: str = ALL_WITHIN_LEVEL_VALUE,
) -> list[str]:
    """Return geography-id selector options for one chosen geography level."""
    if geo_level in {"Total", "All"}:
        return [all_within_level_label]
    if is_all_geographies(geo_level):
        return [AGGREGATE_GEOGRAPHY_LEVEL]

    available_sets = [
        geography_id_option_set(summary, geo_level)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [available for available in available_sets if available]
    if not available_sets:
        return [all_within_level_label]

    ordered = config.ordered_values("geography", sorted(set().union(*available_sets)))
    return [all_within_level_label] + ordered if ordered else [all_within_level_label]


def export_geography_options(
    geography_opts_by_level: dict[str, list[str]],
    *,
    config: Config,
    all_within_level_label: str = ALL_WITHIN_LEVEL_VALUE,
) -> list[str]:
    """Flatten export-mode geography options across levels into one selector domain."""
    values: set[str] = set()
    for options in geography_opts_by_level.values():
        for option in options:
            option_str = str(option)
            if option_str in {all_within_level_label, AGGREGATE_GEOGRAPHY_LEVEL}:
                continue
            values.add(option_str)
    ordered = config.ordered_values("geography", sorted(values))
    return [all_within_level_label] + ordered if ordered else [all_within_level_label]


def filter_geography_level(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    geo_level: str,
    *,
    geography_level_col: str = DEFAULT_GEO_LEVEL_COL,
    geography_type_col: str = DEFAULT_GEO_TYPE_COL,
    origin_level_col: str = "origin_geography_level",
    destination_level_col: str = "destination_geography_level",
) -> list[tuple[str, pl.DataFrame]]:
    """Filter a run-indexed summary list to one geography level."""
    if not data_list:
        return []
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if geo_level not in {"Total", "All"}:
            if geography_level_col in filtered.columns:
                filtered = filtered.with_columns(
                    pl.col(geography_level_col).cast(pl.Utf8)
                ).filter(pl.col(geography_level_col) == geo_level)
            elif geography_type_col in filtered.columns:
                filtered = filtered.with_columns(
                    pl.col(geography_type_col).cast(pl.Utf8)
                ).filter(pl.col(geography_type_col) == geo_level)
            elif {origin_level_col, destination_level_col}.issubset(filtered.columns):
                filtered = filtered.with_columns(
                    pl.col(origin_level_col).cast(pl.Utf8),
                    pl.col(destination_level_col).cast(pl.Utf8),
                ).filter(
                    (pl.col(origin_level_col) == geo_level)
                    & (pl.col(destination_level_col) == geo_level)
                )
        out.append((label, filtered))
    return out


def filter_geography(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    geography: str,
    *,
    geography_col: str = DEFAULT_GEO_COL,
    geography_id_col: str = DEFAULT_GEO_ID_COL,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter a run-indexed summary list to one geography id when requested."""
    if not data_list:
        return []
    if is_all_within_level(geography):
        return nonempty(data_list)

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if geography_col in filtered.columns:
            filtered = filtered.with_columns(pl.col(geography_col).cast(pl.Utf8)).filter(
                pl.col(geography_col) == geography
            )
        elif geography_id_col in filtered.columns:
            filtered = filtered.with_columns(
                pl.col(geography_id_col).cast(pl.Utf8)
            ).filter(pl.col(geography_id_col) == geography)
        out.append((label, filtered))
    return out


def filter_origin_geography(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    geography: str,
    *,
    origin_id_col: str = "origin_geography_id",
    geography_col: str = DEFAULT_GEO_COL,
    geography_id_col: str = DEFAULT_GEO_ID_COL,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter by origin geography id when present, falling back to generic geography ids."""
    if not data_list:
        return []
    if is_all_within_level(geography):
        return nonempty(data_list)

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if origin_id_col in filtered.columns:
            filtered = filtered.with_columns(pl.col(origin_id_col).cast(pl.Utf8)).filter(
                pl.col(origin_id_col) == geography
            )
        elif geography_col in filtered.columns:
            filtered = filtered.with_columns(pl.col(geography_col).cast(pl.Utf8)).filter(
                pl.col(geography_col) == geography
            )
        elif geography_id_col in filtered.columns:
            filtered = filtered.with_columns(
                pl.col(geography_id_col).cast(pl.Utf8)
            ).filter(pl.col(geography_id_col) == geography)
        out.append((label, filtered))
    return out


def geography_column_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    column: str,
    *,
    config: Config | None = None,
    total_label: str = "All",
    include_all_geographies: bool = False,
) -> list[str]:
    """Return selector options for one geography-related column from the first usable frame."""
    first_df = first_nonempty_frame(data_list, column)
    if first_df is None:
        return [total_label]

    values = (
        first_df.select(column).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    if column == DEFAULT_GEO_TYPE_COL and config is not None:
        if include_all_geographies:
            detail_values = sorted(value for value in values if value != AGGREGATE_GEOGRAPHY_LEVEL)
            return (
                [AGGREGATE_GEOGRAPHY_LEVEL] + detail_values
                if AGGREGATE_GEOGRAPHY_LEVEL in values
                else detail_values or [total_label]
            )
        ordered = detail_geography_levels(values, config=config)
        return ordered or [total_label]

    ordered = sorted(value for value in values if value != total_label)
    return [total_label] + ordered
