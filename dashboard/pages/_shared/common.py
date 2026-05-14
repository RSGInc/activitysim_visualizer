"""Common helper utilities reused across dashboard page modules."""

from __future__ import annotations

import polars as pl

from runtime.config import Config


def nonempty_runs(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Return only runs with non-empty DataFrames."""
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def first_nonempty_frame(
    *data_lists: list[tuple[str, pl.DataFrame]],
) -> pl.DataFrame | None:
    """Return the first non-empty DataFrame across one or more run lists."""
    for data_list in data_lists:
        for _, df in nonempty_runs(data_list):
            return df
    return None


def column_options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    *,
    total_label: str = "All",
    include_total: bool = True,
    exclude: tuple[str, ...] = (),
    category_id: str | None = None,
    config: Config | None = None,
    total_raw: str | None = None,
) -> list[str]:
    """Build selector options from the union of raw values across runs."""
    raw_values = column_value_union(data_list, col)
    if not raw_values:
        return [total_label] if include_total else []
    if category_id and config is not None:
        options, _ = selector_domain(
            raw_values,
            category_id=category_id,
            config=config,
            include_total=include_total,
            total_raw=total_raw,
            total_display=total_label,
            exclude=exclude,
        )
        return options

    excluded = {total_label, *exclude}
    options = sorted(value for value in raw_values if value not in excluded)
    if include_total:
        return [total_label] + options
    return options


def column_value_union(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
) -> list[str]:
    """Return the union of column values across runs in first-seen order."""
    values: list[str] = []
    for _, df in nonempty_runs(data_list):
        if col not in df.columns:
            continue
        for value in (
            df.select(col).drop_nulls().to_series().cast(pl.Utf8).to_list()
        ):
            if value not in values:
                values.append(value)
    return values


def category_display_mapping(
    raw_values: list[str],
    *,
    category_id: str,
    config: Config,
    include_total: bool = True,
    total_raw: str | None = None,
    total_display: str = "All",
    exclude: tuple[str, ...] = (),
) -> tuple[list[str], dict[str, str]]:
    """Return display options plus raw mapping for a configured category family."""
    return selector_domain(
        raw_values,
        category_id=category_id,
        config=config,
        include_total=include_total,
        total_raw=total_raw,
        total_display=total_display,
        exclude=exclude,
    )


def category_selector_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    column: str,
    category_id: str,
    config: Config,
    total_raw: str | None = None,
    total_display: str = "All",
    include_total: bool | None = None,
    exclude: tuple[str, ...] = (),
) -> tuple[list[str], dict[str, str]]:
    """Build selector options for one category from the union of raw values across runs."""
    raw_values = column_value_union(data_list, column)
    include_total_value = (
        include_total if include_total is not None else total_raw in raw_values or not raw_values
    )
    return category_display_mapping(
        raw_values,
        category_id=category_id,
        config=config,
        include_total=include_total_value,
        total_raw=total_raw,
        total_display=total_display,
        exclude=exclude,
    )


def selector_domain(
    raw_values: list[str],
    *,
    category_id: str | None = None,
    config: Config | None = None,
    include_total: bool = True,
    total_raw: str | None = None,
    total_display: str = "All",
    exclude: tuple[str, ...] = (),
) -> tuple[list[str], dict[str, str]]:
    """Return display options plus a display->raw mapping for selector widgets."""
    if category_id and config is not None and hasattr(config, "ordered_values"):
        ordered_raw_values = config.ordered_values(category_id, raw_values)
    elif config is not None:
        ordered_raw_values = list(raw_values)
    else:
        ordered_raw_values = sorted(str(value) for value in raw_values)
    excluded = {str(value) for value in exclude}
    options: list[str] = []
    display_to_raw: dict[str, str] = {}
    if include_total:
        if total_raw is not None and total_raw in ordered_raw_values:
            total_option = total_display
            if category_id and config is not None and hasattr(config, "label_value"):
                configured_total = config.label_value(category_id, total_raw)
                if configured_total != str(total_raw):
                    total_option = configured_total
            options.append(total_option)
            display_to_raw[total_option] = total_raw
        else:
            options.append(total_display)
    for raw_value in ordered_raw_values:
        if raw_value in excluded or raw_value == total_raw:
            continue
        display_value = (
            config.label_value(category_id, raw_value)
            if category_id and config is not None and hasattr(config, "label_value")
            else raw_value
        )
        if display_value in display_to_raw:
            continue
        options.append(display_value)
        display_to_raw[display_value] = raw_value
    return options, display_to_raw


def filter_runs_by_column(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    value: str,
    *,
    total_values: tuple[str, ...] = ("All", "Total"),
) -> list[tuple[str, pl.DataFrame]]:
    """Filter each run by one string-like column unless the value is aggregate."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty_runs(data_list):
        if col in df.columns and value not in total_values:
            df = df.with_columns(pl.col(col).cast(pl.Utf8)).filter(pl.col(col) == value)
        out.append((label, df))
    return out


def category_order(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
    *,
    category_id: str | None = None,
    config: Config | None = None,
) -> list[str]:
    """Return category values in configured or first-seen order across runs."""
    values = column_value_union(data_list, category_col)
    if category_id and config is not None:
        return config.ordered_values(category_id, values)
    return values


def category_axis_order(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    column: str,
    category_id: str,
    config: Config,
    total_raw: str | None = None,
    include_total: bool = False,
) -> list[str]:
    """Return display labels in canonical config-backed category order."""
    ordered_raw_values = config.ordered_values(category_id, column_value_union(data_list, column))
    display_values: list[str] = []
    if include_total and total_raw is not None and total_raw in ordered_raw_values:
        display_values.append(config.label_value(category_id, total_raw))
    for raw_value in ordered_raw_values:
        if raw_value == total_raw:
            continue
        display_value = config.label_value(category_id, raw_value)
        if display_value not in display_values:
            display_values.append(display_value)
    return display_values


def relabel_runs_by_column(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
    *,
    category_id: str,
    config: Config,
    display_col: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Apply a shared config-driven label mapping to one categorical column."""
    target_col = display_col or category_col
    return [
        (
            label,
            df.with_columns(
                pl.col(category_col)
                .cast(pl.Utf8)
                .map_elements(
                    lambda value: config.label_value(category_id, value)
                    if value is not None
                    else None,
                    return_dtype=pl.Utf8,
                )
                .alias(target_col)
            ),
        )
        for label, df in nonempty_runs(data_list)
    ]


def complete_category_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    category_col: str,
    category_values: list[str],
    value_cols: tuple[str, ...] = ("person_count", "pct"),
) -> list[tuple[str, pl.DataFrame]]:
    """Fill missing category/value combinations with zeros for each run."""
    if not category_values:
        return data_list

    base = pl.DataFrame({category_col: category_values})
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in data_list:
        if df is None:
            completed = base
        else:
            available_cols = [col for col in (category_col, *value_cols) if col in df.columns]
            completed = base.join(df.select(available_cols), on=category_col, how="left")
        fill_exprs = []
        for col in value_cols:
            if col in completed.columns:
                fill_exprs.append(pl.col(col).fill_null(0).alias(col))
            else:
                fill_exprs.append(pl.lit(0).alias(col))
        out.append((label, completed.with_columns(fill_exprs)))
    return out
