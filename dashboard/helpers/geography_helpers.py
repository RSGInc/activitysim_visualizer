"""Shared dashboard helpers for geography selector discovery, normalization, and filters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from dashboard.helpers.category_helpers import (
    first_nonempty_frame,
    nonempty,
    raw_display_options,
)

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
ALL_GEOGRAPHY_TYPES_VALUE = AGGREGATE_GEOGRAPHY_LEVEL
ALL_GEOGRAPHY_TYPES_LABEL = "All Geography Types"
ALL_GEOGRAPHIES_LABEL = "All Geographies"
GEOGRAPHY_TYPE_SELECTOR_LABEL = "Geography Type"
GEOGRAPHY_NAME_SELECTOR_LABEL = "Geography Name"
DEFAULT_GEO_LEVEL_COL = "geography_level"
DEFAULT_GEO_COL = "geography"
DEFAULT_GEO_TYPE_COL = "geography_type"
DEFAULT_GEO_ID_COL = "geography_id"


def is_all_geographies(value: str | None) -> bool:
    """Return whether a selector value targets the cross-level aggregate geography."""
    return str(value) in {
        AGGREGATE_GEOGRAPHY_LEVEL,
        ALL_GEOGRAPHIES_LABEL,
    }


def is_all_within_level(value: str | None) -> bool:
    """Return whether a selector value means all members within one level."""
    return str(value) in {ALL_WITHIN_LEVEL_VALUE, "All", "Total"}


def geography_type_label(value: str | None, *, config: Config) -> str:
    """Return the display label for one raw geography type/level value."""
    value_str = str(value)
    if value_str in {ALL_GEOGRAPHY_TYPES_VALUE, "Total"}:
        return ALL_GEOGRAPHY_TYPES_LABEL
    configured = config.label_value("geography", value_str)
    if configured != value_str:
        return configured
    uppercase_labels = {"taz": "TAZ", "maz": "MAZ", "mpo": "MPO"}
    if value_str.lower() in uppercase_labels:
        return uppercase_labels[value_str.lower()]
    return value_str.replace("_", " ").title()


def geography_name_label(value: str | None, *, config: Config) -> str:
    """Return a display label for one geography id/name value."""
    value_str = str(value)
    if is_all_geographies(value_str) or value_str in aggregate_geography_level_values():
        configured = config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)
        return configured if configured != AGGREGATE_GEOGRAPHY_LEVEL else ALL_GEOGRAPHIES_LABEL
    configured = config.label_value("geography", value_str)
    if configured != value_str:
        return configured
    return value_str.replace("_", " ").title()


def with_display_geography_columns(
    df: pl.DataFrame,
    *,
    config: Config,
    geography_level_col: str = DEFAULT_GEO_LEVEL_COL,
    geography_col: str = DEFAULT_GEO_COL,
    geography_type_col: str = DEFAULT_GEO_TYPE_COL,
    geography_id_col: str = DEFAULT_GEO_ID_COL,
    type_display_col: str = GEOGRAPHY_TYPE_SELECTOR_LABEL,
    name_display_col: str = GEOGRAPHY_NAME_SELECTOR_LABEL,
) -> pl.DataFrame:
    """Add friendly geography type/name columns for dashboard tables."""
    level_col = (
        geography_level_col
        if geography_level_col in df.columns
        else geography_type_col
        if geography_type_col in df.columns
        else None
    )
    name_col = (
        geography_col
        if geography_col in df.columns
        else geography_id_col
        if geography_id_col in df.columns
        else None
    )
    exprs: list[pl.Expr] = []
    if level_col is not None:
        exprs.append(
            pl.col(level_col)
            .cast(pl.Utf8)
            .map_elements(
                lambda value: (
                    geography_name_label(value, config=config)
                    if is_all_geographies(str(value))
                    else geography_type_label(value, config=config)
                ),
                return_dtype=pl.Utf8,
            )
            .alias(type_display_col)
        )
    if name_col is not None:
        exprs.append(
            pl.col(name_col)
            .cast(pl.Utf8)
            .map_elements(
                lambda value: geography_name_label(value, config=config),
                return_dtype=pl.Utf8,
            )
            .alias(name_display_col)
        )
    return df.with_columns(exprs) if exprs else df


def normalize_geography_level_value(value: str | None) -> str:
    """Normalize accepted aggregate geography tokens to the canonical raw value."""
    value_str = str(value)
    if value_str in {ALL_GEOGRAPHIES_LABEL, "All", "Total"}:
        return AGGREGATE_GEOGRAPHY_LEVEL
    return value_str


def pluralize_geography_label(label: str) -> str:
    """Return a compact plural display label for a geography type label."""
    label = str(label)
    lower = label.lower()
    explicit = {
        "county": "Counties",
        "geography": "Geographies",
        "all geography": "All Geographies",
    }
    if lower in explicit:
        return explicit[lower]
    if label.isupper():
        return f"{label}s"
    if lower.endswith("y") and (len(lower) < 2 or lower[-2] not in "aeiou"):
        return f"{label[:-1]}ies"
    if lower.endswith(("s", "x", "z")) or lower.endswith(("ch", "sh")):
        return f"{label}es"
    return f"{label}s"


def all_within_geography_type_label(
    geography_type: str | None,
    *,
    config: Config,
) -> str:
    """Return the display label for all geography names within a selected type."""
    if geography_type in {None, ALL_GEOGRAPHY_TYPES_VALUE, "Total"}:
        return config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)
    if is_all_geographies(geography_type):
        return config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)
    return f"All {pluralize_geography_label(geography_type_label(geography_type, config=config))}"


def geography_name_selector_label(
    geography_type: str | None,
    *,
    config: Config,
) -> str:
    """Return the selector label for geography names under one geography type."""
    if geography_type in {None, ALL_GEOGRAPHY_TYPES_VALUE, "Total"}:
        return GEOGRAPHY_NAME_SELECTOR_LABEL
    if is_all_geographies(geography_type):
        return GEOGRAPHY_NAME_SELECTOR_LABEL
    return f"{geography_type_label(geography_type, config=config)} Name"


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
    include_disabled_maz: bool = False,
) -> list[str]:
    """Return selector geography levels, hiding only MAZ when disabled."""
    if include_disabled_maz:
        visible = [str(value).strip() for value in values if str(value).strip()]
        ordered = [value for value in PREFERRED_TYPED_GEO_ORDER if value in visible]
        ordered.extend(sorted(value for value in visible if value not in ordered))
    else:
        ordered = ordered_visible_geography_levels(values, config=config)
    return config.ordered_values("geography", ordered)


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
            available.update(normalize_geography_level_value(value) for value in values)
        elif geography_type_col in df.columns:
            values = (
                df.select(geography_type_col)
                .drop_nulls()
                .unique()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            )
            available.update(normalize_geography_level_value(value) for value in values)
        elif {origin_level_col, destination_level_col}.issubset(df.columns):
            origin_values = set(
                normalize_geography_level_value(value)
                for value in df[origin_level_col].cast(pl.Utf8).drop_nulls().unique().to_list()
            )
            destination_values = set(
                normalize_geography_level_value(value)
                for value in df[destination_level_col]
                .cast(pl.Utf8)
                .drop_nulls()
                .unique()
                .to_list()
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
    return [geography_type_label(value, config=config) for value in ordered] if ordered else [total_label]


def geography_type_options(
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
    include_all_types: bool = False,
    include_disabled_maz: bool = False,
    all_types_label: str = ALL_GEOGRAPHY_TYPES_LABEL,
    fallback_raw: str = AGGREGATE_GEOGRAPHY_LEVEL,
) -> tuple[list[str], dict[str, str | None]]:
    """Return geography type display options plus display-to-raw lookup."""
    available_sets = [
        geography_level_option_set(summary)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [available for available in available_sets if available]
    if not available_sets:
        raw_values = [fallback_raw]
    else:
        raw_values = detail_geography_levels(
            set().union(*available_sets),
            config=config,
            include_disabled_maz=include_disabled_maz,
        )
    raw_by_label: dict[str, str | None] = {}
    if include_all_types:
        raw_by_label[all_types_label] = ALL_GEOGRAPHY_TYPES_VALUE
    for raw_value in raw_values:
        if include_all_types and raw_value == ALL_GEOGRAPHY_TYPES_VALUE:
            continue
        raw_by_label[geography_type_label(raw_value, config=config)] = raw_value
    return list(raw_by_label), raw_by_label


def aggregate_geography_level_values() -> set[str]:
    """Return accepted raw values for aggregate geography levels."""
    return {AGGREGATE_GEOGRAPHY_LEVEL, "All", "Total", ALL_GEOGRAPHIES_LABEL}


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
        return [ALL_GEOGRAPHIES_LABEL]

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


def geography_name_options_for_type(
    geography_type: str,
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
) -> tuple[list[str], dict[str, str | None]]:
    """Return geography name display options plus display-to-raw lookup."""
    if geography_type in {ALL_GEOGRAPHY_TYPES_VALUE, "Total"}:
        display = config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)
        return [display], {display: ALL_WITHIN_LEVEL_VALUE}
    if is_all_geographies(geography_type):
        display = config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)
        return [display], {display: AGGREGATE_GEOGRAPHY_LEVEL}

    available_sets = [
        geography_id_option_set(summary, geography_type)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [available for available in available_sets if available]
    all_label = all_within_geography_type_label(geography_type, config=config)
    if not available_sets:
        return [all_label], {all_label: ALL_WITHIN_LEVEL_VALUE}

    raw_values = config.ordered_values("geography", sorted(set().union(*available_sets)))
    return raw_display_options(
        raw_values,
        category_id="geography",
        config=config,
        total_raw=ALL_WITHIN_LEVEL_VALUE,
        total_label=all_label,
    )


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
            if option_str == all_within_level_label or is_all_geographies(option_str):
                continue
            values.add(option_str)
    ordered = config.ordered_values("geography", sorted(values))
    return [all_within_level_label] + ordered if ordered else [all_within_level_label]


def export_geography_name_options(
    geography_opts_by_level: dict[str, tuple[list[str], dict[str, str | None]]],
    *,
    config: Config,
    all_within_level_label: str = ALL_WITHIN_LEVEL_VALUE,
) -> tuple[list[str], dict[str, str | None]]:
    """Flatten per-level geography display options for export mode."""
    raw_values: set[str] = set()
    for options, raw_by_label in geography_opts_by_level.values():
        for option in options:
            raw_value = raw_by_label.get(str(option), str(option))
            if raw_value is None:
                continue
            raw_value_str = str(raw_value)
            if raw_value_str == all_within_level_label or is_all_geographies(raw_value_str):
                continue
            raw_values.add(raw_value_str)
    ordered = config.ordered_values("geography", sorted(raw_values))
    return raw_display_options(
        ordered,
        category_id="geography",
        config=config,
        total_raw=all_within_level_label,
        total_label=all_within_level_label,
    )


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
    aggregate_values = aggregate_geography_level_values()
    match_aggregate = is_all_geographies(geo_level)
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if geo_level not in {"Total", "All"}:
            if geography_level_col in filtered.columns:
                filtered = filtered.with_columns(
                    pl.col(geography_level_col).cast(pl.Utf8)
                ).filter(
                    pl.col(geography_level_col).is_in(aggregate_values)
                    if match_aggregate
                    else pl.col(geography_level_col) == geo_level
                )
            elif geography_type_col in filtered.columns:
                filtered = filtered.with_columns(
                    pl.col(geography_type_col).cast(pl.Utf8)
                ).filter(
                    pl.col(geography_type_col).is_in(aggregate_values)
                    if match_aggregate
                    else pl.col(geography_type_col) == geo_level
                )
            elif {origin_level_col, destination_level_col}.issubset(filtered.columns):
                filtered = filtered.with_columns(
                    pl.col(origin_level_col).cast(pl.Utf8),
                    pl.col(destination_level_col).cast(pl.Utf8),
                )
                if match_aggregate:
                    filtered = filtered.filter(
                        pl.col(origin_level_col).is_in(aggregate_values)
                        & pl.col(destination_level_col).is_in(aggregate_values)
                    )
                else:
                    filtered = filtered.filter(
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
    aggregate_values = aggregate_geography_level_values()
    match_aggregate = is_all_geographies(geography)

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if geography_col in filtered.columns:
            filtered = filtered.with_columns(pl.col(geography_col).cast(pl.Utf8)).filter(
                pl.col(geography_col).is_in(aggregate_values)
                if match_aggregate
                else pl.col(geography_col) == geography
            )
        elif geography_id_col in filtered.columns:
            filtered = filtered.with_columns(
                pl.col(geography_id_col).cast(pl.Utf8)
            ).filter(
                pl.col(geography_id_col).is_in(aggregate_values)
                if match_aggregate
                else pl.col(geography_id_col) == geography
            )
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
    aggregate_values = aggregate_geography_level_values()
    match_aggregate = is_all_geographies(geography)

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if origin_id_col in filtered.columns:
            filtered = filtered.with_columns(pl.col(origin_id_col).cast(pl.Utf8)).filter(
                pl.col(origin_id_col).is_in(aggregate_values)
                if match_aggregate
                else pl.col(origin_id_col) == geography
            )
        elif geography_col in filtered.columns:
            filtered = filtered.with_columns(pl.col(geography_col).cast(pl.Utf8)).filter(
                pl.col(geography_col).is_in(aggregate_values)
                if match_aggregate
                else pl.col(geography_col) == geography
            )
        elif geography_id_col in filtered.columns:
            filtered = filtered.with_columns(
                pl.col(geography_id_col).cast(pl.Utf8)
            ).filter(
                pl.col(geography_id_col).is_in(aggregate_values)
                if match_aggregate
                else pl.col(geography_id_col) == geography
            )
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
                [config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)] + detail_values
                if AGGREGATE_GEOGRAPHY_LEVEL in values
                else detail_values or [total_label]
            )
        ordered = detail_geography_levels(values, config=config)
        return [
            config.label_value("geography", value) if is_all_geographies(value) else value
            for value in (ordered or [total_label])
        ]

    ordered = sorted(value for value in values if value != total_label)
    if include_all_geographies and config is not None and AGGREGATE_GEOGRAPHY_LEVEL in ordered:
        ordered = [value for value in ordered if value != AGGREGATE_GEOGRAPHY_LEVEL]
        return [config.label_value("geography", AGGREGATE_GEOGRAPHY_LEVEL)] + ordered
    return [total_label] + ordered
