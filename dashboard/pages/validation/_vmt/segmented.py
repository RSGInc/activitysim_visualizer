"""Personal-auto and non-motorized VMT transformations and option domains."""

from __future__ import annotations

import polars as pl

from dashboard.helpers.category_helpers import (
    column_value_union,
    nonempty,
    raw_display_options,
)

from .contracts import (
    NON_MOTORIZED_VMT_MODE_ORDER,
    PERSONAL_AUTO_VMT_ALL_MODES,
    PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS,
    PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
    PERSONAL_AUTO_VMT_MODE_ORDER,
    PERSONAL_AUTO_VMT_TIME_ORDER,
    PERSONAL_AUTO_VMT_TOP_GEOGRAPHIES,
)


def _prefer_daily_rows_for_all_time_periods(
    df: pl.DataFrame,
    *,
    breakdown_col: str,
    selected_time_period: str,
) -> pl.DataFrame:
    """Use Daily total rows for all-day non-period breakdowns when available."""
    if (
        df.is_empty()
        or breakdown_col == "time_period"
        or selected_time_period != "All"
        or "time_period" not in df.columns
    ):
        return df

    group_cols = [
        column
        for column in (
            "geography_type",
            "geography_id",
            "mode",
            "income_segment",
            "household_size",
        )
        if column in df.columns
    ]
    daily_rows = df.filter(pl.col("time_period") == "Daily")
    if daily_rows.is_empty() or not group_cols:
        return df

    daily_groups = daily_rows.select(group_cols).unique()
    period_rows_without_daily_total = df.filter(pl.col("time_period") != "Daily").join(
        daily_groups, on=group_cols, how="anti"
    )
    return pl.concat([daily_rows, period_rows_without_daily_total], how="vertical")


def _with_time_period_percent_of_daily(
    chart_df: pl.DataFrame,
) -> pl.DataFrame:
    """Add percent VMT values using Daily as the denominator when present."""
    if chart_df.is_empty() or not {"category", "auto_vmt"}.issubset(chart_df.columns):
        return chart_df

    daily_total = chart_df.filter(pl.col("category") == "Daily")["auto_vmt"].sum()
    denominator = (
        daily_total if daily_total and daily_total > 0 else chart_df["auto_vmt"].sum()
    )
    if not denominator or denominator <= 0:
        return chart_df.with_columns(pl.lit(0.0).alias("auto_vmt_percent"))

    return chart_df.with_columns(
        (pl.col("auto_vmt") / denominator * 100.0).alias("auto_vmt_percent")
    )


def _ordered_values(
    values: list[str],
    *,
    preferred: list[str] | None = None,
) -> list[str]:
    """Return stable selector/chart values with preferred values first."""
    preferred = preferred or []
    preferred_index = {value: index for index, value in enumerate(preferred)}
    return sorted(
        values,
        key=lambda value: (
            0 if value in preferred_index else 1,
            preferred_index.get(value, 0),
            value.lower(),
            value,
        ),
    )


def _selector_values(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    column: str,
    *,
    include_all: bool = False,
    preferred: list[str] | None = None,
) -> list[str]:
    values = _ordered_values(
        column_value_union(data_list or [], column),
        preferred=preferred,
    )
    return ["All", *values] if include_all else values


def _chart_category_order(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    preferred: list[str],
    category_col: str = "category",
) -> list[str]:
    values = [
        str(value)
        for _, df in data_list
        if category_col in df.columns and not df.is_empty()
        for value in df[category_col].drop_nulls().cast(pl.Utf8).to_list()
    ]
    return _ordered_values(list(dict.fromkeys(values)), preferred=preferred)


def personal_auto_mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    config,
) -> tuple[list[str], dict[str, str | None]]:
    values = column_value_union(data_list or [], "mode")
    ordered_values = config.ordered_values(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, values)
    return raw_display_options(
        ordered_values,
        category_id=PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
        config=config,
        total_raw="All",
        total_label="All",
    )


def non_motorized_mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    config,
) -> tuple[list[str], dict[str, str | None]]:
    values = [str(value) for value in column_value_union(data_list or [], "mode")]
    preferred = [value for value in NON_MOTORIZED_VMT_MODE_ORDER if value in values]
    remaining = config.ordered_values(
        PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
        [value for value in values if value not in preferred],
    )
    return raw_display_options(
        [*preferred, *remaining],
        category_id=PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
        config=config,
        total_raw="All",
        total_label="All",
    )


def non_motorized_vmt_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    breakdown: str,
    geography_type: str,
    geography_id: str,
    time_period: str,
    income_segment: str,
    household_size: str,
    mode: str = "All",
    mode_order: list[str] | None = None,
    top_geographies: int = PERSONAL_AUTO_VMT_TOP_GEOGRAPHIES,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter and aggregate non-motorized VMT rows for the selected breakdown."""
    normalized: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        if "non_motorized_vmt" not in df.columns:
            continue
        normalized.append((label, df.rename({"non_motorized_vmt": "auto_vmt"})))
    chart_data = personal_auto_vmt_chart_data(
        normalized,
        breakdown=breakdown,
        geography_type=geography_type,
        geography_id=geography_id,
        time_period=time_period,
        mode=mode,
        income_segment=income_segment,
        household_size=household_size,
        mode_order=mode_order or NON_MOTORIZED_VMT_MODE_ORDER,
        top_geographies=top_geographies,
    )
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in chart_data:
        rename_map = {"auto_vmt": "non_motorized_vmt"}
        if "auto_vmt_percent" in df.columns:
            rename_map["auto_vmt_percent"] = "non_motorized_vmt_percent"
        out.append((label, df.rename(rename_map)))
    return out


def personal_auto_vmt_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    breakdown: str,
    geography_type: str,
    geography_id: str,
    time_period: str,
    income_segment: str,
    household_size: str,
    mode: str = "All",
    mode_order: list[str] | None = None,
    top_geographies: int = PERSONAL_AUTO_VMT_TOP_GEOGRAPHIES,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter and aggregate personal auto VMT rows for the selected breakdown."""
    breakdown_col = PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS[breakdown]
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        missing = [
            column
            for column in (
                "geography_type",
                "geography_id",
                "income_segment",
                "household_size",
                "time_period",
                "auto_vmt",
                "trip_count",
            )
            if column not in df.columns
        ]
        if missing:
            continue
        filtered = df.with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("income_segment").cast(pl.Utf8),
            pl.col("household_size").cast(pl.Utf8),
            pl.col("time_period").cast(pl.Utf8),
            (
                pl.col("mode").cast(pl.Utf8).fill_null(PERSONAL_AUTO_VMT_ALL_MODES)
                if "mode" in df.columns
                else pl.lit(PERSONAL_AUTO_VMT_ALL_MODES)
            ).alias("mode"),
        )
        if geography_type != "All":
            filtered = filtered.filter(pl.col("geography_type") == geography_type)
        if breakdown_col != "geography_id" and geography_id != "All":
            filtered = filtered.filter(pl.col("geography_id") == geography_id)
        if breakdown_col != "time_period" and time_period != "All":
            filtered = filtered.filter(pl.col("time_period") == time_period)
        if breakdown_col != "mode" and mode != "All":
            filtered = filtered.filter(pl.col("mode") == mode)
        if breakdown_col != "income_segment" and income_segment != "All":
            filtered = filtered.filter(pl.col("income_segment") == income_segment)
        if breakdown_col != "household_size" and household_size != "All":
            filtered = filtered.filter(pl.col("household_size") == household_size)
        filtered = _prefer_daily_rows_for_all_time_periods(
            filtered,
            breakdown_col=breakdown_col,
            selected_time_period=time_period,
        )

        if filtered.is_empty():
            out.append(
                (
                    label,
                    pl.DataFrame(
                        {
                            "category": pl.Series([], dtype=pl.Utf8),
                            "auto_vmt": pl.Series([], dtype=pl.Float64),
                            "trip_count": pl.Series([], dtype=pl.Float64),
                        }
                    ),
                )
            )
            continue

        chart_df = (
            filtered.group_by(breakdown_col)
            .agg(
                pl.col("auto_vmt").sum().alias("auto_vmt"),
                pl.col("trip_count").sum().alias("trip_count"),
            )
            .rename({breakdown_col: "category"})
            .with_columns(pl.col("category").cast(pl.Utf8))
        )
        if breakdown_col == "geography_id":
            chart_df = chart_df.sort("auto_vmt", descending=True).head(top_geographies)
        elif breakdown_col == "time_period":
            chart_df = (
                chart_df.with_columns(
                    pl.col("category")
                    .replace_strict(
                        {
                            value: index
                            for index, value in enumerate(PERSONAL_AUTO_VMT_TIME_ORDER)
                        },
                        default=len(PERSONAL_AUTO_VMT_TIME_ORDER),
                        return_dtype=pl.Int64,
                    )
                    .alias("_sort_order")
                )
                .sort("_sort_order", "category")
                .drop("_sort_order")
            )
            chart_df = _with_time_period_percent_of_daily(chart_df)
        elif breakdown_col == "mode":
            mode_order = mode_order or PERSONAL_AUTO_VMT_MODE_ORDER
            chart_df = (
                chart_df.with_columns(
                    pl.col("category")
                    .replace_strict(
                        {value: index for index, value in enumerate(mode_order)},
                        default=len(mode_order),
                        return_dtype=pl.Int64,
                    )
                    .alias("_sort_order")
                )
                .sort("_sort_order", "category")
                .drop("_sort_order")
            )
        elif breakdown_col == "household_size":
            chart_df = (
                chart_df.with_columns(
                    pl.col("category")
                    .cast(pl.Float64, strict=False)
                    .alias("_sort_order")
                )
                .sort("_sort_order", "category", nulls_last=True)
                .drop("_sort_order")
            )
        else:
            chart_df = chart_df.sort("category")
        out.append((label, chart_df))
    return out
