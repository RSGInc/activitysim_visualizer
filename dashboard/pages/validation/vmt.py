"""VMT validation page with personal auto, commercial, and bicycle VMT charts."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, selector_row
from dashboard.helpers.category_helpers import (
    column_value_union,
    label_category_data,
    nonempty,
    raw_display_options,
)
from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    ALL_GEOGRAPHY_TYPES_VALUE,
    GEOGRAPHY_NAME_SELECTOR_LABEL,
    GEOGRAPHY_TYPE_SELECTOR_LABEL,
    geography_name_options_for_type,
    geography_name_selector_label,
    geography_type_options,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

EXTERNAL_TOD_ORDER = ["EA", "AM", "MD", "PM", "EV", "EV1", "EV2"]
EXTERNAL_COMMERCIAL_COLUMNS = ["car", "mu", "su"]
EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS = ["Time Period", "Commercial Vehicle Type"]
EXTERNAL_COMMERCIAL_DAILY_PERIOD = "Daily"
EXTERNAL_COMMERCIAL_TIME_ORDER = [*EXTERNAL_TOD_ORDER, EXTERNAL_COMMERCIAL_DAILY_PERIOD]
COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID = "commercial_vehicle_type"
EXTERNAL_TRAVEL_COLUMNS = [
    "hbcoll",
    "hbo",
    "hbr",
    "hbs",
    "hbsch",
    "hbw",
    "nhbnw",
    "nhbw",
    "truck",
]
EXTERNAL_TRAVEL_TOTAL_COLUMN = "Total"
EXTERNAL_TRAVEL_BREAKDOWN_OPTIONS = ["Time Period", "Trip Purpose"]
EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID = "trip_purpose"
PERSONAL_AUTO_VMT_SUMMARY_ID = "auto_vmt_by_home_geography_income_hhsize_time_period"
NON_MOTORIZED_VMT_SUMMARY_ID = (
    "non_motorized_vmt_by_home_geography_income_hhsize_time_period"
)
EXTERNAL_VMT_SUMMARY_ID = "external_vmt_validation_summary"
COMMERCIAL_VMT_SUMMARY_ID = "commercial_vehicle_vmt_validation_summary"
PERSONAL_AUTO_VMT_REQUIRED_COLUMNS = (
    "geography_type",
    "geography_id",
    "income_segment",
    "household_size",
    "time_period",
    "auto_vmt",
    "trip_count",
    "distance_source",
    "time_period_source",
)
NON_MOTORIZED_VMT_REQUIRED_COLUMNS = (
    "geography_type",
    "geography_id",
    "income_segment",
    "household_size",
    "time_period",
    "mode",
    "non_motorized_vmt",
    "trip_count",
    "distance_source",
    "time_period_source",
)
PERSONAL_AUTO_VMT_ALL_MODES = "All Auto"
PERSONAL_AUTO_VMT_MODE_CATEGORY_ID = "mode"
NON_MOTORIZED_VMT_MODE_ORDER = ["WALK", "BIKE", "EBIKE"]
PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS = {
    "Time Period": "time_period",
    "Mode": "mode",
    "Income Segment": "income_segment",
    "Household Size": "household_size",
    "Home Geography": "geography_id",
}
PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES = {
    "Time Period": "Time Period",
    "Mode": "Mode",
    "Income Segment": "Income Segment",
    "Household Size": "Household Size",
    "Home Geography": "Home Geography",
}
PERSONAL_AUTO_VMT_TIME_ORDER = ["EA", "AM", "MD", "PM", "EV", "EV1", "EV2", "Daily"]
PERSONAL_AUTO_VMT_MODE_ORDER = ["SOV", "HOV2", "HOV3"]
PERSONAL_AUTO_VMT_TOP_GEOGRAPHIES = 25
VMT_OVERVIEW_ROWS = ("Personal Auto", "Non-Motorized", "External", "Commercial")


def _sum_float_column(df: pl.DataFrame, column: str) -> float:
    if df.is_empty() or column not in df.columns:
        return 0.0
    value = df.select(pl.col(column).cast(pl.Float64).sum()).item()
    return float(value or 0.0)


def _total_segmented_vmt(df: pl.DataFrame, value_col: str) -> float:
    if df.is_empty() or value_col not in df.columns:
        return 0.0

    filtered = df
    if {"geography_type", "geography_id"}.issubset(filtered.columns):
        all_geography_rows = filtered.filter(
            (pl.col("geography_type").cast(pl.Utf8) == ALL_GEOGRAPHY_TYPES_VALUE)
            & (pl.col("geography_id").cast(pl.Utf8) == ALL_GEOGRAPHY_TYPES_VALUE)
        )
        if not all_geography_rows.is_empty():
            filtered = all_geography_rows

    if "time_period" in filtered.columns:
        daily_rows = filtered.filter(pl.col("time_period").cast(pl.Utf8) == "Daily")
        if not daily_rows.is_empty():
            filtered = daily_rows

    return _sum_float_column(filtered, value_col)


def _total_wide_tod_vmt(
    df: pl.DataFrame,
    *,
    value_columns: list[str],
    total_column: str | None = None,
    tod_col: str = "tod",
) -> float:
    if df.is_empty():
        return 0.0

    filtered = df
    if tod_col in filtered.columns:
        daily_rows = filtered.filter(
            pl.col(tod_col).cast(pl.Utf8).str.to_lowercase() == "daily"
        )
        if not daily_rows.is_empty():
            filtered = daily_rows

    if total_column and total_column in filtered.columns:
        return _sum_float_column(filtered, total_column)

    available_columns = [column for column in value_columns if column in filtered.columns]
    if not available_columns:
        return 0.0
    value = filtered.select(
        pl.sum_horizontal([pl.col(column).cast(pl.Float64) for column in available_columns])
        .sum()
        .alias("vmt")
    ).item()
    return float(value or 0.0)


def vmt_overview_table_data(
    *,
    personal_auto_vmt: list[tuple[str, pl.DataFrame]] | None,
    non_motorized_vmt: list[tuple[str, pl.DataFrame]] | None,
    external_vmt: list[tuple[str, pl.DataFrame]] | None,
    commercial_vmt: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one VMT/share overview table per run label."""
    personal_auto_vmt = personal_auto_vmt or []
    non_motorized_vmt = non_motorized_vmt or []
    external_vmt = external_vmt or []
    commercial_vmt = commercial_vmt or []
    labels = list(
        dict.fromkeys(
            label
            for data_list in (
                personal_auto_vmt,
                non_motorized_vmt,
                external_vmt,
                commercial_vmt,
            )
            for label, _ in data_list
        )
    )
    personal_by_label = dict(personal_auto_vmt)
    non_motorized_by_label = dict(non_motorized_vmt)
    external_by_label = dict(external_vmt)
    commercial_by_label = dict(commercial_vmt)

    out: list[tuple[str, pl.DataFrame]] = []
    for label in labels:
        totals = {
            "Personal Auto": _total_segmented_vmt(
                personal_by_label.get(label, pl.DataFrame()),
                "auto_vmt",
            ),
            "Non-Motorized": _total_segmented_vmt(
                non_motorized_by_label.get(label, pl.DataFrame()),
                "non_motorized_vmt",
            ),
            "External": _total_wide_tod_vmt(
                external_by_label.get(label, pl.DataFrame()),
                value_columns=EXTERNAL_TRAVEL_COLUMNS,
                total_column=EXTERNAL_TRAVEL_TOTAL_COLUMN,
            ),
            "Commercial": _total_wide_tod_vmt(
                commercial_by_label.get(label, pl.DataFrame()),
                value_columns=EXTERNAL_COMMERCIAL_COLUMNS,
            ),
        }
        grand_total = sum(totals.values())
        share_values = [
            (totals[row] / grand_total * 100.0) if grand_total > 0 else 0.0
            for row in VMT_OVERVIEW_ROWS
        ]
        out.append(
            (
                label,
                pl.DataFrame(
                    {
                        "Category": list(VMT_OVERVIEW_ROWS),
                        "VMT": [totals[row] for row in VMT_OVERVIEW_ROWS],
                        "% Share of Total": share_values,
                    }
                ),
            )
        )
    return out


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
    period_rows_without_daily_total = df.filter(
        pl.col("time_period") != "Daily"
    ).join(daily_groups, on=group_cols, how="anti")
    return pl.concat([daily_rows, period_rows_without_daily_total], how="vertical")


def _with_time_period_percent_of_daily(
    chart_df: pl.DataFrame,
) -> pl.DataFrame:
    """Add percent VMT values using Daily as the denominator when present."""
    if chart_df.is_empty() or not {"category", "auto_vmt"}.issubset(chart_df.columns):
        return chart_df

    daily_total = chart_df.filter(pl.col("category") == "Daily")["auto_vmt"].sum()
    denominator = daily_total if daily_total and daily_total > 0 else chart_df["auto_vmt"].sum()
    if not denominator or denominator <= 0:
        return chart_df.with_columns(pl.lit(0.0).alias("auto_vmt_percent"))

    return chart_df.with_columns(
        (pl.col("auto_vmt") / denominator * 100.0).alias("auto_vmt_percent")
    )


def _with_value_percent_of_daily(chart_df: pl.DataFrame) -> pl.DataFrame:
    """Add percent values using Daily as the denominator when present."""
    if chart_df.is_empty() or not {"category", "value"}.issubset(chart_df.columns):
        return chart_df

    daily_total = chart_df.filter(
        pl.col("category") == EXTERNAL_COMMERCIAL_DAILY_PERIOD
    )["value"].sum()
    denominator = daily_total if daily_total and daily_total > 0 else chart_df["value"].sum()
    if not denominator or denominator <= 0:
        return chart_df.with_columns(pl.lit(0.0).alias("value_percent"))

    return chart_df.with_columns(
        (pl.col("value") / denominator * 100.0).alias("value_percent")
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
            chart_df = chart_df.with_columns(
                pl.col("category")
                .replace_strict(
                    {value: index for index, value in enumerate(PERSONAL_AUTO_VMT_TIME_ORDER)},
                    default=len(PERSONAL_AUTO_VMT_TIME_ORDER),
                    return_dtype=pl.Int64,
                )
                .alias("_sort_order")
            ).sort("_sort_order", "category").drop("_sort_order")
            chart_df = _with_time_period_percent_of_daily(chart_df)
        elif breakdown_col == "mode":
            mode_order = mode_order or PERSONAL_AUTO_VMT_MODE_ORDER
            chart_df = chart_df.with_columns(
                pl.col("category")
                .replace_strict(
                    {value: index for index, value in enumerate(mode_order)},
                    default=len(mode_order),
                    return_dtype=pl.Int64,
                )
                .alias("_sort_order")
            ).sort("_sort_order", "category").drop("_sort_order")
        elif breakdown_col == "household_size":
            chart_df = chart_df.with_columns(
                pl.col("category").cast(pl.Float64, strict=False).alias("_sort_order")
            ).sort("_sort_order", "category", nulls_last=True).drop("_sort_order")
        else:
            chart_df = chart_df.sort("category")
        out.append((label, chart_df))
    return out


def wide_tod_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    tod_col: str,
    value_columns: list[str],
    exclude_total_period: bool = True,
) -> list[tuple[str, pl.DataFrame]]:
    """Return long chart-ready rows from legacy wide time-of-day summaries."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        available_columns = [column for column in value_columns if column in df.columns]
        if tod_col not in df.columns or not available_columns:
            continue
        filtered = df.with_columns(pl.col(tod_col).cast(pl.Utf8))
        if exclude_total_period:
            filtered = filtered.filter(pl.col(tod_col).str.to_lowercase() != "daily")
        chart_df = filtered.unpivot(
            index=tod_col,
            on=available_columns,
            variable_name="category",
            value_name="value",
        ).rename({tod_col: "tod"})
        out.append((label, chart_df))
    return out


def demo_commercial_vehicle_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    breakdown: str,
    time_period: str = EXTERNAL_COMMERCIAL_DAILY_PERIOD,
    commercial_vehicle_type: str = "All",
    tod_col: str = "tod",
    value_columns: list[str] | None = None,
    exclude_total_period: bool = True,
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate demo commercial vehicle summaries for one chart breakdown."""
    value_columns = value_columns or EXTERNAL_COMMERCIAL_COLUMNS
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        available_columns = [column for column in value_columns if column in df.columns]
        if tod_col not in df.columns or not available_columns:
            continue
        filtered = df.with_columns(pl.col(tod_col).cast(pl.Utf8))
        daily_rows = filtered.filter(
            pl.col(tod_col).str.to_lowercase()
            == EXTERNAL_COMMERCIAL_DAILY_PERIOD.lower()
        )
        if breakdown != "Time Period":
            if (
                time_period == EXTERNAL_COMMERCIAL_DAILY_PERIOD
                and not daily_rows.is_empty()
            ):
                filtered = daily_rows
            elif exclude_total_period:
                filtered = filtered.filter(
                    pl.col(tod_col).str.to_lowercase() != "daily"
                )
        long_df = filtered.unpivot(
            index=tod_col,
            on=available_columns,
            variable_name="commercial_vehicle_type",
            value_name="value",
        ).rename({tod_col: "time_period"})
        if (
            breakdown != "Time Period"
            and time_period not in ("All", EXTERNAL_COMMERCIAL_DAILY_PERIOD)
        ):
            long_df = long_df.filter(pl.col("time_period") == time_period)
        if (
            breakdown != "Commercial Vehicle Type"
            and commercial_vehicle_type != "All"
        ):
            long_df = long_df.filter(
                pl.col("commercial_vehicle_type") == commercial_vehicle_type
            )
        if breakdown == "Commercial Vehicle Type":
            chart_df = (
                long_df.group_by("commercial_vehicle_type")
                .agg(pl.col("value").sum().alias("value"))
                .rename({"commercial_vehicle_type": "category"})
                .with_columns(pl.col("category").cast(pl.Utf8))
            )
            order = value_columns
        else:
            chart_df = (
                long_df.group_by("time_period")
                .agg(pl.col("value").sum().alias("value"))
                .rename({"time_period": "category"})
                .with_columns(pl.col("category").cast(pl.Utf8))
            )
            if (
                EXTERNAL_COMMERCIAL_DAILY_PERIOD not in chart_df["category"].to_list()
                and not chart_df.is_empty()
            ):
                chart_df = pl.concat(
                    [
                        chart_df,
                        pl.DataFrame(
                            {
                                "category": [EXTERNAL_COMMERCIAL_DAILY_PERIOD],
                                "value": [chart_df["value"].sum()],
                            }
                        ),
                    ],
                    how="vertical",
                )
            chart_df = _with_value_percent_of_daily(chart_df)
            order = EXTERNAL_COMMERCIAL_TIME_ORDER
        chart_df = (
            chart_df.with_columns(
                pl.col("category")
                .replace_strict(
                    {value: index for index, value in enumerate(order)},
                    default=len(order),
                    return_dtype=pl.Int64,
                )
                .alias("_sort_order")
            )
            .sort("_sort_order", "category")
            .drop("_sort_order")
        )
        out.append((label, chart_df))
    return out


def external_travel_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    breakdown: str,
    time_period: str = EXTERNAL_COMMERCIAL_DAILY_PERIOD,
    trip_purpose: str = "All",
    tod_col: str = "tod",
    value_columns: list[str] | None = None,
    total_column: str = EXTERNAL_TRAVEL_TOTAL_COLUMN,
    exclude_total_period: bool = True,
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate external travel summaries for one chart breakdown."""
    value_columns = value_columns or EXTERNAL_TRAVEL_COLUMNS
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        available_columns = [column for column in value_columns if column in df.columns]
        filter_columns = (
            available_columns
            if total_column not in df.columns
            else [*available_columns, total_column]
        )
        if tod_col not in df.columns or not filter_columns:
            continue
        filtered = df.with_columns(pl.col(tod_col).cast(pl.Utf8))
        daily_rows = filtered.filter(
            pl.col(tod_col).str.to_lowercase()
            == EXTERNAL_COMMERCIAL_DAILY_PERIOD.lower()
        )
        if breakdown != "Time Period":
            if (
                time_period == EXTERNAL_COMMERCIAL_DAILY_PERIOD
                and not daily_rows.is_empty()
            ):
                filtered = daily_rows
            elif exclude_total_period:
                filtered = filtered.filter(
                    pl.col(tod_col).str.to_lowercase() != "daily"
                )
        long_df = filtered.unpivot(
            index=tod_col,
            on=filter_columns,
            variable_name="trip_purpose",
            value_name="value",
        ).rename({tod_col: "time_period"})
        if breakdown != "Time Period" and time_period not in (
            "All",
            EXTERNAL_COMMERCIAL_DAILY_PERIOD,
        ):
            long_df = long_df.filter(pl.col("time_period") == time_period)
        if breakdown != "Trip Purpose":
            if trip_purpose != "All" or total_column in filter_columns:
                purpose_column = total_column if trip_purpose == "All" else trip_purpose
                long_df = long_df.filter(pl.col("trip_purpose") == purpose_column)
        else:
            long_df = long_df.filter(pl.col("trip_purpose") != total_column)
        if breakdown == "Trip Purpose":
            chart_df = (
                long_df.group_by("trip_purpose")
                .agg(pl.col("value").sum().alias("value"))
                .rename({"trip_purpose": "category"})
                .with_columns(pl.col("category").cast(pl.Utf8))
            )
            order = value_columns
        else:
            chart_df = (
                long_df.group_by("time_period")
                .agg(pl.col("value").sum().alias("value"))
                .rename({"time_period": "category"})
                .with_columns(pl.col("category").cast(pl.Utf8))
            )
            if (
                EXTERNAL_COMMERCIAL_DAILY_PERIOD not in chart_df["category"].to_list()
                and not chart_df.is_empty()
            ):
                chart_df = pl.concat(
                    [
                        chart_df,
                        pl.DataFrame(
                            {
                                "category": [EXTERNAL_COMMERCIAL_DAILY_PERIOD],
                                "value": [chart_df["value"].sum()],
                            }
                        ),
                    ],
                    how="vertical",
                )
            chart_df = _with_value_percent_of_daily(chart_df)
            order = EXTERNAL_COMMERCIAL_TIME_ORDER
        chart_df = (
            chart_df.with_columns(
                pl.col("category")
                .replace_strict(
                    {value: index for index, value in enumerate(order)},
                    default=len(order),
                    return_dtype=pl.Int64,
                )
                .alias("_sort_order")
            )
            .sort("_sort_order", "category")
            .drop("_sort_order")
        )
        out.append((label, chart_df))
    return out


def demo_commercial_filter_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    config,
    tod_col: str = "tod",
    value_columns: list[str] | None = None,
) -> tuple[list[str], tuple[list[str], dict[str, str | None]]]:
    """Return time-period and vehicle-type filter options for demo commercial data."""
    value_columns = value_columns or EXTERNAL_COMMERCIAL_COLUMNS
    time_periods: set[str] = set()
    vehicle_types: set[str] = set()
    for _, df in nonempty(data_list or []):
        if tod_col in df.columns:
            time_periods.update(
                str(value)
                for value in df[tod_col].drop_nulls().cast(pl.Utf8).to_list()
                if str(value).lower() != "daily"
            )
        vehicle_types.update(column for column in value_columns if column in df.columns)
    ordered_time_periods = _ordered_values(
        list(time_periods),
        preferred=EXTERNAL_TOD_ORDER,
    )
    ordered_vehicle_types = config.ordered_values(
        COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
        [
            *[column for column in value_columns if column in vehicle_types],
            *sorted(column for column in vehicle_types if column not in value_columns),
        ],
    )
    vehicle_options = raw_display_options(
        ordered_vehicle_types,
        category_id=COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
        config=config,
        total_raw="All",
        total_label="All",
    )
    return [EXTERNAL_COMMERCIAL_DAILY_PERIOD, *ordered_time_periods], vehicle_options


def external_travel_filter_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    config,
    tod_col: str = "tod",
    value_columns: list[str] | None = None,
) -> tuple[list[str], tuple[list[str], dict[str, str | None]]]:
    """Return time-period and trip-purpose filter options for external travel data."""
    value_columns = value_columns or EXTERNAL_TRAVEL_COLUMNS
    time_periods: set[str] = set()
    trip_purposes: set[str] = set()
    for _, df in nonempty(data_list or []):
        if tod_col in df.columns:
            time_periods.update(
                str(value)
                for value in df[tod_col].drop_nulls().cast(pl.Utf8).to_list()
                if str(value).lower() != "daily"
            )
        trip_purposes.update(column for column in value_columns if column in df.columns)
    ordered_time_periods = _ordered_values(
        list(time_periods),
        preferred=EXTERNAL_TOD_ORDER,
    )
    ordered_trip_purposes = config.ordered_values(
        EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
        [
            *[column for column in value_columns if column in trip_purposes],
            *sorted(column for column in trip_purposes if column not in value_columns),
        ],
    )
    purpose_options = raw_display_options(
        ordered_trip_purposes,
        category_id=EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
        config=config,
        total_raw="All",
        total_label="All",
    )
    return [EXTERNAL_COMMERCIAL_DAILY_PERIOD, *ordered_time_periods], purpose_options


class VMTValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        personal_vmt = self.state.get_summary_table_set(
            PERSONAL_AUTO_VMT_SUMMARY_ID,
            "weighted",
        )
        non_motorized_vmt = self.state.get_summary_table_set(
            NON_MOTORIZED_VMT_SUMMARY_ID,
            "weighted",
        )
        geography_type_options_display, self.personal_vmt_geo_type_raw_by_label = (
            geography_type_options(
                personal_vmt,
                config=self.config,
                include_all_types=True,
            )
        )
        if not geography_type_options_display:
            geography_type_options_display = [ALL_GEOGRAPHY_TYPES_LABEL]
            self.personal_vmt_geo_type_raw_by_label = {
                ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
            }
        geography_options_display, self.personal_vmt_geo_raw_by_label = (
            geography_name_options_for_type(
                str(self.personal_vmt_geo_type_raw_by_label.get(geography_type_options_display[0], ALL_GEOGRAPHY_TYPES_VALUE)),
                personal_vmt,
                config=self.config,
            )
        )
        if not geography_options_display:
            geography_options_display = ["All Geographies"]
            self.personal_vmt_geo_raw_by_label = {"All Geographies": "All"}
        mode_options, self.personal_vmt_mode_raw_by_label = personal_auto_mode_options(
            personal_vmt,
            config=self.config,
        )
        if not mode_options:
            mode_options = ["All"]
            self.personal_vmt_mode_raw_by_label = {"All": "All"}
        (
            non_motorized_geography_type_options_display,
            self.non_motorized_vmt_geo_type_raw_by_label,
        ) = geography_type_options(
            non_motorized_vmt,
            config=self.config,
            include_all_types=True,
        )
        if not non_motorized_geography_type_options_display:
            non_motorized_geography_type_options_display = [ALL_GEOGRAPHY_TYPES_LABEL]
            self.non_motorized_vmt_geo_type_raw_by_label = {
                ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
            }
        (
            non_motorized_geography_options_display,
            self.non_motorized_vmt_geo_raw_by_label,
        ) = geography_name_options_for_type(
            str(
                self.non_motorized_vmt_geo_type_raw_by_label.get(
                    non_motorized_geography_type_options_display[0],
                    ALL_GEOGRAPHY_TYPES_VALUE,
                )
            ),
            non_motorized_vmt,
            config=self.config,
        )
        if not non_motorized_geography_options_display:
            non_motorized_geography_options_display = ["All Geographies"]
            self.non_motorized_vmt_geo_raw_by_label = {"All Geographies": "All"}
        (
            non_motorized_mode_options_display,
            self.non_motorized_vmt_mode_raw_by_label,
        ) = non_motorized_mode_options(
            non_motorized_vmt,
            config=self.config,
        )
        if not non_motorized_mode_options_display:
            non_motorized_mode_options_display = ["All"]
            self.non_motorized_vmt_mode_raw_by_label = {"All": "All"}
        self.demo_commercial_vehicle_type_raw_by_label = {"All": "All"}
        self.external_travel_trip_purpose_raw_by_label = {"All": "All"}
        self.personal_vmt_breakdown_sel = self.selector(
            "personal_auto_vmt_breakdown",
            widget=pn.widgets.Select(
                name="Breakdown",
                options=list(PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS),
                value="Time Period",
            ),
            label="Breakdown",
        )
        self.personal_vmt_geography_type_sel = self.selector(
            "personal_auto_vmt_geography_type",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_TYPE_SELECTOR_LABEL,
                options=geography_type_options_display,
                value=geography_type_options_display[0],
            ),
            label=GEOGRAPHY_TYPE_SELECTOR_LABEL,
        )
        self.personal_vmt_geography_sel = self.selector(
            "personal_auto_vmt_geography",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_NAME_SELECTOR_LABEL,
                options=geography_options_display,
                value=geography_options_display[0],
            ),
            label=GEOGRAPHY_NAME_SELECTOR_LABEL,
        )
        self.personal_vmt_time_period_sel = self.selector(
            "personal_auto_vmt_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=["All"],
                value="All",
            ),
            label="Time Period",
        )
        self.personal_vmt_mode_sel = self.selector(
            "personal_auto_vmt_mode",
            widget=pn.widgets.Select(
                name="Mode",
                options=mode_options,
                value=mode_options[0],
            ),
            label="Mode",
        )
        self.personal_vmt_income_segment_sel = self.selector(
            "personal_auto_vmt_income_segment",
            widget=pn.widgets.Select(
                name="Income Segment",
                options=["All"],
                value="All",
            ),
            label="Income Segment",
        )
        self.personal_vmt_household_size_sel = self.selector(
            "personal_auto_vmt_household_size",
            widget=pn.widgets.Select(
                name="Household Size",
                options=["All"],
                value="All",
            ),
            label="Household Size",
        )
        self.non_motorized_vmt_breakdown_sel = self.selector(
            "non_motorized_vmt_breakdown",
            widget=pn.widgets.Select(
                name="Breakdown",
                options=list(PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS),
                value="Time Period",
            ),
            label="Breakdown",
        )
        self.non_motorized_vmt_geography_type_sel = self.selector(
            "non_motorized_vmt_geography_type",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_TYPE_SELECTOR_LABEL,
                options=non_motorized_geography_type_options_display,
                value=non_motorized_geography_type_options_display[0],
            ),
            label=GEOGRAPHY_TYPE_SELECTOR_LABEL,
        )
        self.non_motorized_vmt_geography_sel = self.selector(
            "non_motorized_vmt_geography",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_NAME_SELECTOR_LABEL,
                options=non_motorized_geography_options_display,
                value=non_motorized_geography_options_display[0],
            ),
            label=GEOGRAPHY_NAME_SELECTOR_LABEL,
        )
        self.non_motorized_vmt_time_period_sel = self.selector(
            "non_motorized_vmt_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=["All"],
                value="All",
            ),
            label="Time Period",
        )
        self.non_motorized_vmt_mode_sel = self.selector(
            "non_motorized_vmt_mode",
            widget=pn.widgets.Select(
                name="Mode",
                options=non_motorized_mode_options_display,
                value=non_motorized_mode_options_display[0],
            ),
            label="Mode",
        )
        self.non_motorized_vmt_income_segment_sel = self.selector(
            "non_motorized_vmt_income_segment",
            widget=pn.widgets.Select(
                name="Income Segment",
                options=["All"],
                value="All",
            ),
            label="Income Segment",
        )
        self.non_motorized_vmt_household_size_sel = self.selector(
            "non_motorized_vmt_household_size",
            widget=pn.widgets.Select(
                name="Household Size",
                options=["All"],
                value="All",
            ),
            label="Household Size",
        )
        self.demo_commercial_metric_sel = self.selector(
            "demo_commercial_metric",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Metric",
                options=["Trips", "VMT"],
                value="Trips",
            ),
            label="Commercial Vehicle Metric",
        )
        self.demo_commercial_breakdown_sel = self.selector(
            "demo_commercial_breakdown",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Breakdown",
                options=EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS,
                value=EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS[0],
            ),
            label="Commercial Vehicle Breakdown",
        )
        self.demo_commercial_vehicle_type_sel = self.selector(
            "demo_commercial_vehicle_type",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Type",
                options=["All"],
                value="All",
            ),
            label="Commercial Vehicle Type",
        )
        self.demo_commercial_time_period_sel = self.selector(
            "demo_commercial_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=[EXTERNAL_COMMERCIAL_DAILY_PERIOD],
                value=EXTERNAL_COMMERCIAL_DAILY_PERIOD,
            ),
            label="Time Period",
        )
        self.external_travel_metric_sel = self.selector(
            "external_travel_metric",
            widget=pn.widgets.Select(
                name="External Travel Metric",
                options=["Trips", "VMT"],
                value="Trips",
            ),
            label="External Travel Metric",
        )
        self.external_travel_breakdown_sel = self.selector(
            "external_travel_breakdown",
            widget=pn.widgets.Select(
                name="External Travel Breakdown",
                options=EXTERNAL_TRAVEL_BREAKDOWN_OPTIONS,
                value=EXTERNAL_TRAVEL_BREAKDOWN_OPTIONS[0],
            ),
            label="External Travel Breakdown",
        )
        self.external_travel_trip_purpose_sel = self.selector(
            "external_travel_trip_purpose",
            widget=pn.widgets.Select(
                name="Trip Purpose",
                options=["All"],
                value="All",
            ),
            label="Trip Purpose",
        )
        self.external_travel_time_period_sel = self.selector(
            "external_travel_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=[EXTERNAL_COMMERCIAL_DAILY_PERIOD],
                value=EXTERNAL_COMMERCIAL_DAILY_PERIOD,
            ),
            label="Time Period",
        )
        self._personal_vmt_body = self.section(
            "personal_auto_vmt_body",
            selectors=(
                "personal_auto_vmt_breakdown",
                "personal_auto_vmt_geography_type",
                "personal_auto_vmt_geography",
                "personal_auto_vmt_time_period",
                "personal_auto_vmt_mode",
                "personal_auto_vmt_income_segment",
                "personal_auto_vmt_household_size",
            ),
            render=self.render_personal_auto_vmt_section,
        )
        self._non_motorized_vmt_body = self.section(
            "non_motorized_vmt_body",
            selectors=(
                "non_motorized_vmt_breakdown",
                "non_motorized_vmt_geography_type",
                "non_motorized_vmt_geography",
                "non_motorized_vmt_time_period",
                "non_motorized_vmt_mode",
                "non_motorized_vmt_income_segment",
                "non_motorized_vmt_household_size",
            ),
            render=self.render_non_motorized_vmt_section,
        )
        self._body = self.section(
            "commercial_vmt_body",
            selectors=(
                "demo_commercial_metric",
                "demo_commercial_breakdown",
                "demo_commercial_vehicle_type",
                "demo_commercial_time_period",
            ),
            render=self.render_commercial_vmt_section,
        )
        self._external_vmt_body = self.section(
            "external_vmt_body",
            selectors=(
                "external_travel_metric",
                "external_travel_breakdown",
                "external_travel_trip_purpose",
                "external_travel_time_period",
            ),
            render=self.render_external_vmt_section,
        )
        self._bicycle_body = self.section(
            "bicycle_vmt_body",
            render=self.render_bicycle_section,
        )
        self._vmt_overview_body = self.section(
            "vmt_overview_body",
            render=self.render_vmt_overview_section,
        )
        return self.new_section(
            pn.pane.Markdown("## VMT Validation"),
            self._vmt_overview_body,
            pn.pane.Markdown("### Personal Auto VMT"),
            selector_row(
                self.personal_vmt_breakdown_sel,
                self.personal_vmt_geography_type_sel,
                self.personal_vmt_geography_sel,
            ),
            selector_row(
                self.personal_vmt_time_period_sel,
                self.personal_vmt_mode_sel,
                self.personal_vmt_income_segment_sel,
                self.personal_vmt_household_size_sel,
            ),
            self._personal_vmt_body,
            pn.pane.Markdown("### Non-Motorized VMT"),
            selector_row(
                self.non_motorized_vmt_breakdown_sel,
                self.non_motorized_vmt_geography_type_sel,
                self.non_motorized_vmt_geography_sel,
            ),
            selector_row(
                self.non_motorized_vmt_time_period_sel,
                self.non_motorized_vmt_mode_sel,
                self.non_motorized_vmt_income_segment_sel,
                self.non_motorized_vmt_household_size_sel,
            ),
            self._non_motorized_vmt_body,
            pn.pane.Markdown("### External VMT and Travel"),
            selector_row(
                self.external_travel_metric_sel,
                self.external_travel_breakdown_sel,
                self.external_travel_trip_purpose_sel,
                self.external_travel_time_period_sel,
            ),
            self._external_vmt_body,
            pn.pane.Markdown("### Commercial VMT and Travel"),
            selector_row(
                self.demo_commercial_metric_sel,
                self.demo_commercial_breakdown_sel,
                self.demo_commercial_vehicle_type_sel,
                self.demo_commercial_time_period_sel,
            ),
            self._body,
            pn.pane.Markdown("### Bicycle VMT"),
            self._bicycle_body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        personal_vmt = self.state.get_summary_table_set(
            PERSONAL_AUTO_VMT_SUMMARY_ID,
            self.weighting_key,
        )
        geography_type_options_display, self.personal_vmt_geo_type_raw_by_label = geography_type_options(
            personal_vmt,
            config=self.config,
            include_all_types=True,
        )
        if not geography_type_options_display:
            geography_type_options_display = [ALL_GEOGRAPHY_TYPES_LABEL]
            self.personal_vmt_geo_type_raw_by_label = {
                ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
            }
        self.personal_vmt_geography_type_sel.options = geography_type_options_display
        if self.personal_vmt_geography_type_sel.value not in geography_type_options_display:
            self.personal_vmt_geography_type_sel.value = geography_type_options_display[0]

        breakdown = str(self.personal_vmt_breakdown_sel.value)
        geography_type_enabled = breakdown == "Home Geography"
        self.personal_vmt_geography_type_sel.disabled = not geography_type_enabled
        if not geography_type_enabled:
            self.personal_vmt_geography_type_sel.value = geography_type_options_display[0]

        geography_type = self.selected_personal_vmt_geography_type_raw()
        geography_options_display, self.personal_vmt_geo_raw_by_label = (
            geography_name_options_for_type(
                geography_type,
                personal_vmt,
                config=self.config,
            )
        )
        self.personal_vmt_geography_sel.name = geography_name_selector_label(
            geography_type,
            config=self.config,
        )
        self.personal_vmt_geography_sel.options = geography_options_display
        if self.personal_vmt_geography_sel.value not in geography_options_display:
            self.personal_vmt_geography_sel.value = geography_options_display[0]

        time_period_options = _selector_values(
            personal_vmt,
            "time_period",
            include_all=True,
            preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
        ) or ["All"]
        self.personal_vmt_time_period_sel.options = time_period_options
        if self.personal_vmt_time_period_sel.value not in time_period_options:
            self.personal_vmt_time_period_sel.value = "All"

        mode_options, self.personal_vmt_mode_raw_by_label = personal_auto_mode_options(
            personal_vmt,
            config=self.config,
        )
        if not mode_options:
            mode_options = ["All"]
            self.personal_vmt_mode_raw_by_label = {"All": "All"}
        self.personal_vmt_mode_sel.options = mode_options
        if self.personal_vmt_mode_sel.value not in mode_options:
            self.personal_vmt_mode_sel.value = "All"

        income_options = _selector_values(
            personal_vmt,
            "income_segment",
            include_all=True,
        ) or ["All"]
        self.personal_vmt_income_segment_sel.options = income_options
        if self.personal_vmt_income_segment_sel.value not in income_options:
            self.personal_vmt_income_segment_sel.value = "All"

        household_size_options = _selector_values(
            personal_vmt,
            "household_size",
            include_all=True,
        ) or ["All"]
        self.personal_vmt_household_size_sel.options = household_size_options
        if self.personal_vmt_household_size_sel.value not in household_size_options:
            self.personal_vmt_household_size_sel.value = "All"

        self.personal_vmt_time_period_sel.disabled = False
        self.personal_vmt_mode_sel.disabled = False
        self.personal_vmt_income_segment_sel.disabled = False
        self.personal_vmt_household_size_sel.disabled = False
        breakdown_filter_selector = {
            "Time Period": self.personal_vmt_time_period_sel,
            "Mode": self.personal_vmt_mode_sel,
            "Income Segment": self.personal_vmt_income_segment_sel,
            "Household Size": self.personal_vmt_household_size_sel,
        }.get(breakdown)
        if breakdown_filter_selector is not None:
            if "All" in breakdown_filter_selector.options:
                breakdown_filter_selector.value = "All"
            breakdown_filter_selector.disabled = True

        non_motorized_vmt = self.state.get_summary_table_set(
            NON_MOTORIZED_VMT_SUMMARY_ID,
            self.weighting_key,
        )
        (
            non_motorized_geography_type_options_display,
            self.non_motorized_vmt_geo_type_raw_by_label,
        ) = geography_type_options(
            non_motorized_vmt,
            config=self.config,
            include_all_types=True,
        )
        if not non_motorized_geography_type_options_display:
            non_motorized_geography_type_options_display = [
                ALL_GEOGRAPHY_TYPES_LABEL
            ]
            self.non_motorized_vmt_geo_type_raw_by_label = {
                ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
            }
        self.non_motorized_vmt_geography_type_sel.options = (
            non_motorized_geography_type_options_display
        )
        if (
            self.non_motorized_vmt_geography_type_sel.value
            not in non_motorized_geography_type_options_display
        ):
            self.non_motorized_vmt_geography_type_sel.value = (
                non_motorized_geography_type_options_display[0]
            )

        non_motorized_breakdown = str(self.non_motorized_vmt_breakdown_sel.value)
        non_motorized_geography_type_enabled = (
            non_motorized_breakdown == "Home Geography"
        )
        self.non_motorized_vmt_geography_type_sel.disabled = (
            not non_motorized_geography_type_enabled
        )
        if not non_motorized_geography_type_enabled:
            self.non_motorized_vmt_geography_type_sel.value = (
                non_motorized_geography_type_options_display[0]
            )

        non_motorized_geography_type = (
            self.selected_non_motorized_vmt_geography_type_raw()
        )
        (
            non_motorized_geography_options_display,
            self.non_motorized_vmt_geo_raw_by_label,
        ) = geography_name_options_for_type(
            non_motorized_geography_type,
            non_motorized_vmt,
            config=self.config,
        )
        self.non_motorized_vmt_geography_sel.name = geography_name_selector_label(
            non_motorized_geography_type,
            config=self.config,
        )
        self.non_motorized_vmt_geography_sel.options = (
            non_motorized_geography_options_display
        )
        if (
            self.non_motorized_vmt_geography_sel.value
            not in non_motorized_geography_options_display
        ):
            self.non_motorized_vmt_geography_sel.value = (
                non_motorized_geography_options_display[0]
            )

        non_motorized_time_period_options = _selector_values(
            non_motorized_vmt,
            "time_period",
            include_all=True,
            preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
        ) or ["All"]
        self.non_motorized_vmt_time_period_sel.options = (
            non_motorized_time_period_options
        )
        if (
            self.non_motorized_vmt_time_period_sel.value
            not in non_motorized_time_period_options
        ):
            self.non_motorized_vmt_time_period_sel.value = "All"

        (
            non_motorized_mode_options_display,
            self.non_motorized_vmt_mode_raw_by_label,
        ) = non_motorized_mode_options(
            non_motorized_vmt,
            config=self.config,
        )
        if not non_motorized_mode_options_display:
            non_motorized_mode_options_display = ["All"]
            self.non_motorized_vmt_mode_raw_by_label = {"All": "All"}
        self.non_motorized_vmt_mode_sel.options = non_motorized_mode_options_display
        if (
            self.non_motorized_vmt_mode_sel.value
            not in non_motorized_mode_options_display
        ):
            self.non_motorized_vmt_mode_sel.value = "All"

        non_motorized_income_options = _selector_values(
            non_motorized_vmt,
            "income_segment",
            include_all=True,
        ) or ["All"]
        self.non_motorized_vmt_income_segment_sel.options = (
            non_motorized_income_options
        )
        if (
            self.non_motorized_vmt_income_segment_sel.value
            not in non_motorized_income_options
        ):
            self.non_motorized_vmt_income_segment_sel.value = "All"

        non_motorized_household_size_options = _selector_values(
            non_motorized_vmt,
            "household_size",
            include_all=True,
        ) or ["All"]
        self.non_motorized_vmt_household_size_sel.options = (
            non_motorized_household_size_options
        )
        if (
            self.non_motorized_vmt_household_size_sel.value
            not in non_motorized_household_size_options
        ):
            self.non_motorized_vmt_household_size_sel.value = "All"

        self.non_motorized_vmt_time_period_sel.disabled = False
        self.non_motorized_vmt_mode_sel.disabled = False
        self.non_motorized_vmt_income_segment_sel.disabled = False
        self.non_motorized_vmt_household_size_sel.disabled = False
        non_motorized_breakdown_filter_selector = {
            "Time Period": self.non_motorized_vmt_time_period_sel,
            "Mode": self.non_motorized_vmt_mode_sel,
            "Income Segment": self.non_motorized_vmt_income_segment_sel,
            "Household Size": self.non_motorized_vmt_household_size_sel,
        }.get(non_motorized_breakdown)
        if non_motorized_breakdown_filter_selector is not None:
            if "All" in non_motorized_breakdown_filter_selector.options:
                non_motorized_breakdown_filter_selector.value = "All"
            non_motorized_breakdown_filter_selector.disabled = True

        demo_commercial_summary_id = (
            "commercial_vehicle_vmt_validation_summary"
            if self.demo_commercial_metric_sel.value == "VMT"
            else "commercial_vehicle_validation_summary"
        )
        demo_commercial_data = self.state.get_summary_table_set(
            demo_commercial_summary_id,
            self.weighting_key,
        )
        (
            time_period_options,
            (vehicle_type_options, self.demo_commercial_vehicle_type_raw_by_label),
        ) = demo_commercial_filter_options(
            demo_commercial_data,
            config=self.config,
        )
        for widget, options in (
            (self.demo_commercial_time_period_sel, time_period_options),
            (self.demo_commercial_vehicle_type_sel, vehicle_type_options),
        ):
            widget.options = options or ["All"]
            if widget.value not in widget.options:
                widget.value = widget.options[0]

        self.demo_commercial_time_period_sel.disabled = False
        self.demo_commercial_vehicle_type_sel.disabled = False
        demo_breakdown_filter_selector = {
            "Time Period": self.demo_commercial_time_period_sel,
            "Commercial Vehicle Type": self.demo_commercial_vehicle_type_sel,
        }.get(str(self.demo_commercial_breakdown_sel.value))
        if demo_breakdown_filter_selector is not None:
            if "All" in demo_breakdown_filter_selector.options:
                demo_breakdown_filter_selector.value = "All"
            elif demo_breakdown_filter_selector.options:
                demo_breakdown_filter_selector.value = (
                    demo_breakdown_filter_selector.options[0]
                )
            demo_breakdown_filter_selector.disabled = True

        external_travel_summary_id = (
            "external_vmt_validation_summary"
            if self.external_travel_metric_sel.value == "VMT"
            else "external_trip_validation_summary"
        )
        external_travel_data = self.state.get_summary_table_set(
            external_travel_summary_id,
            self.weighting_key,
        )
        (
            external_time_period_options,
            (trip_purpose_options, self.external_travel_trip_purpose_raw_by_label),
        ) = external_travel_filter_options(
            external_travel_data,
            config=self.config,
        )
        for widget, options in (
            (self.external_travel_time_period_sel, external_time_period_options),
            (self.external_travel_trip_purpose_sel, trip_purpose_options),
        ):
            widget.options = options or ["All"]
            if widget.value not in widget.options:
                widget.value = widget.options[0]

        self.external_travel_time_period_sel.disabled = False
        self.external_travel_trip_purpose_sel.disabled = False
        external_travel_breakdown_filter_selector = {
            "Time Period": self.external_travel_time_period_sel,
            "Trip Purpose": self.external_travel_trip_purpose_sel,
        }.get(str(self.external_travel_breakdown_sel.value))
        if external_travel_breakdown_filter_selector is not None:
            if "All" in external_travel_breakdown_filter_selector.options:
                external_travel_breakdown_filter_selector.value = "All"
            elif external_travel_breakdown_filter_selector.options:
                external_travel_breakdown_filter_selector.value = (
                    external_travel_breakdown_filter_selector.options[0]
                )
            external_travel_breakdown_filter_selector.disabled = True

    def selected_personal_vmt_geography_type_raw(self) -> str:
        selected = str(self.personal_vmt_geography_type_sel.value)
        raw_value = self.personal_vmt_geo_type_raw_by_label.get(selected, selected)
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def selected_non_motorized_vmt_geography_type_raw(self) -> str:
        selected = str(self.non_motorized_vmt_geography_type_sel.value)
        raw_value = self.non_motorized_vmt_geo_type_raw_by_label.get(
            selected,
            selected,
        )
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def export_ignored_selectors(
        self,
        section_id: str,
        selected_values: dict[str, str],
    ) -> set[str]:
        section_prefix = {
            "personal_auto_vmt_body": "personal_auto_vmt",
            "non_motorized_vmt_body": "non_motorized_vmt",
        }.get(section_id)
        if section_prefix is None:
            return set()

        breakdown = selected_values.get(f"{section_prefix}_breakdown")
        if breakdown == "Home Geography":
            return {f"{section_prefix}_geography"}
        if breakdown:
            return {
                f"{section_prefix}_geography_type",
                f"{section_prefix}_geography",
            }
        return set()

    def export_canonical_selector_value(
        self,
        section_id: str,
        selector_id: str,
        value: str,
        selected_values: dict[str, str],
    ) -> str:
        section_prefix = {
            "personal_auto_vmt_body": "personal_auto_vmt",
            "non_motorized_vmt_body": "non_motorized_vmt",
        }.get(section_id)
        if (
            section_prefix is not None
            and selector_id == f"{section_prefix}_geography_type"
            and selected_values.get(f"{section_prefix}_breakdown")
            != "Home Geography"
        ):
            return ALL_GEOGRAPHY_TYPES_LABEL
        return value

    def selected_personal_vmt_geography_raw(self) -> str:
        selected = str(self.personal_vmt_geography_sel.value)
        raw_value = self.personal_vmt_geo_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_non_motorized_vmt_geography_raw(self) -> str:
        selected = str(self.non_motorized_vmt_geography_sel.value)
        raw_value = self.non_motorized_vmt_geo_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_personal_vmt_mode_raw(self) -> str:
        selected = str(self.personal_vmt_mode_sel.value)
        raw_value = self.personal_vmt_mode_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_non_motorized_vmt_mode_raw(self) -> str:
        selected = str(self.non_motorized_vmt_mode_sel.value)
        raw_value = self.non_motorized_vmt_mode_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_demo_commercial_vehicle_type_raw(self) -> str:
        selected = str(self.demo_commercial_vehicle_type_sel.value)
        raw_value = self.demo_commercial_vehicle_type_raw_by_label.get(
            selected,
            selected,
        )
        return "All" if raw_value is None else str(raw_value)

    def selected_external_travel_trip_purpose_raw(self) -> str:
        selected = str(self.external_travel_trip_purpose_sel.value)
        raw_value = self.external_travel_trip_purpose_raw_by_label.get(
            selected,
            selected,
        )
        return "All" if raw_value is None else str(raw_value)

    def render_vmt_overview_section(self) -> list[pn.viewable.Viewable]:
        overview_data = vmt_overview_table_data(
            personal_auto_vmt=self.state.get_summary_table_set(
                PERSONAL_AUTO_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
            non_motorized_vmt=self.state.get_summary_table_set(
                NON_MOTORIZED_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
            external_vmt=self.state.get_summary_table_set(
                EXTERNAL_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
            commercial_vmt=self.state.get_summary_table_set(
                COMMERCIAL_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
        )
        if not overview_data:
            return []
        return [
            data_table(
                overview_data,
                height=180,
                numeric_precision_by_column={
                    "VMT": 2,
                    "% Share of Total": 4,
                },
                column_sorters={
                    "VMT": "number",
                    "% Share of Total": "number",
                },
            )
        ]

    def render_personal_auto_vmt_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return []
        selection = self.inspect_summary(
            PERSONAL_AUTO_VMT_SUMMARY_ID,
            required_columns=PERSONAL_AUTO_VMT_REQUIRED_COLUMNS,
        )
        if not selection.has_usable_runs:
            return [
                self.data_not_available_card(
                    detail="Personal auto VMT by home geography, income segment, household size, and time period is unavailable.",
                    missing_items=[PERSONAL_AUTO_VMT_SUMMARY_ID],
                )
            ]
        personal_vmt = [(label, table) for label, table in selection.usable_runs]
        breakdown = str(self.personal_vmt_breakdown_sel.value)
        geography_type = self.selected_personal_vmt_geography_type_raw()
        geography_id = self.selected_personal_vmt_geography_raw()
        time_period = str(self.personal_vmt_time_period_sel.value)
        mode = self.selected_personal_vmt_mode_raw()
        income_segment = str(self.personal_vmt_income_segment_sel.value)
        household_size = str(self.personal_vmt_household_size_sel.value)
        mode_values = [
            value
            for _, df in personal_vmt
            if "mode" in df.columns
            for value in df["mode"].drop_nulls().cast(pl.Utf8).to_list()
        ]
        mode_order = self.config.ordered_values(
            PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
            list(dict.fromkeys(mode_values)),
        )
        chart_data = self.get_filtered_view(
            "personal_auto_vmt",
            (
                breakdown,
                geography_type,
                geography_id,
                time_period,
                mode,
                income_segment,
                household_size,
            ),
            factory=lambda: personal_auto_vmt_chart_data(
                personal_vmt,
                breakdown=breakdown,
                geography_type=geography_type,
                geography_id=geography_id,
                time_period=time_period,
                mode=mode,
                income_segment=income_segment,
                household_size=household_size,
                mode_order=mode_order,
            ),
        )
        if breakdown == "Mode":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        elif breakdown == "Home Geography":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id="geography",
                config=self.config,
                target_col="category",
            )
        category_values = [
            value
            for _, df in chart_data
            for value in (
                df["category"].to_list()
                if "category" in df.columns and not df.is_empty()
                else []
            )
        ]
        if breakdown == "Time Period":
            xaxis_categoryarray = _ordered_values(
                list(dict.fromkeys(str(value) for value in category_values)),
                preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
            )
        elif breakdown == "Mode":
            xaxis_categoryarray = [
                self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                for value in mode_order
                if self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                in {str(category) for category in category_values}
            ]
        else:
            xaxis_categoryarray = list(dict.fromkeys(str(value) for value in category_values))
        use_time_period_percent = self.as_percent and breakdown == "Time Period"
        chart = bar_chart(
            chart_data,
            x_col="category",
            y_col="auto_vmt_percent" if use_time_period_percent else "auto_vmt",
            title=f"Personal Auto VMT by {breakdown}",
            xaxis_title=PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES[breakdown],
            yaxis_title=(
                "Percent of Vehicle Miles Traveled (%)"
                if use_time_period_percent
                else "Vehicle Miles Traveled"
            ),
            as_percent=False if use_time_period_percent else self.as_percent,
            xaxis_categoryarray=xaxis_categoryarray,
        )
        return [chart]

    def render_non_motorized_vmt_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return []
        selection = self.inspect_summary(
            NON_MOTORIZED_VMT_SUMMARY_ID,
            required_columns=NON_MOTORIZED_VMT_REQUIRED_COLUMNS,
        )
        if not selection.has_usable_runs:
            return [
                self.data_not_available_card(
                    detail="Non-motorized VMT by home geography, income segment, household size, and time period is unavailable.",
                    missing_items=[NON_MOTORIZED_VMT_SUMMARY_ID],
                )
            ]
        non_motorized_vmt = [(label, table) for label, table in selection.usable_runs]
        breakdown = str(self.non_motorized_vmt_breakdown_sel.value)
        geography_type = self.selected_non_motorized_vmt_geography_type_raw()
        geography_id = self.selected_non_motorized_vmt_geography_raw()
        time_period = str(self.non_motorized_vmt_time_period_sel.value)
        mode = self.selected_non_motorized_vmt_mode_raw()
        income_segment = str(self.non_motorized_vmt_income_segment_sel.value)
        household_size = str(self.non_motorized_vmt_household_size_sel.value)
        mode_values = [
            value
            for _, df in non_motorized_vmt
            if "mode" in df.columns
            for value in df["mode"].drop_nulls().cast(pl.Utf8).to_list()
        ]
        mode_order = self.config.ordered_values(
            PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
            list(dict.fromkeys(mode_values)),
        )
        chart_data = self.get_filtered_view(
            "non_motorized_vmt",
            (
                breakdown,
                geography_type,
                geography_id,
                time_period,
                mode,
                income_segment,
                household_size,
            ),
            factory=lambda: non_motorized_vmt_chart_data(
                non_motorized_vmt,
                breakdown=breakdown,
                geography_type=geography_type,
                geography_id=geography_id,
                time_period=time_period,
                mode=mode,
                income_segment=income_segment,
                household_size=household_size,
                mode_order=mode_order or NON_MOTORIZED_VMT_MODE_ORDER,
            ),
        )
        if breakdown == "Mode":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        elif breakdown == "Home Geography":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id="geography",
                config=self.config,
                target_col="category",
            )
        category_values = [
            value
            for _, df in chart_data
            for value in (
                df["category"].to_list()
                if "category" in df.columns and not df.is_empty()
                else []
            )
        ]
        if breakdown == "Time Period":
            xaxis_categoryarray = _ordered_values(
                list(dict.fromkeys(str(value) for value in category_values)),
                preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
            )
        elif breakdown == "Mode":
            xaxis_categoryarray = [
                self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                for value in mode_order
                if self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                in {str(category) for category in category_values}
            ]
        else:
            xaxis_categoryarray = list(
                dict.fromkeys(str(value) for value in category_values)
            )
        use_time_period_percent = self.as_percent and breakdown == "Time Period"
        chart = bar_chart(
            chart_data,
            x_col="category",
            y_col=(
                "non_motorized_vmt_percent"
                if use_time_period_percent
                else "non_motorized_vmt"
            ),
            title=f"Non-Motorized VMT by {breakdown}",
            xaxis_title=PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES[breakdown],
            yaxis_title=(
                "Percent of Non-Motorized Miles Traveled (%)"
                if use_time_period_percent
                else "Non-Motorized Miles Traveled"
            ),
            as_percent=False if use_time_period_percent else self.as_percent,
            xaxis_categoryarray=xaxis_categoryarray,
        )
        return [chart]

    def render_bicycle_chart(self) -> pn.viewable.Viewable:
        bicycle_vmt = self.state.get_summary_table_set(
            "bicycle_vmt_by_facility_type",
            self.weighting_key,
        )
        if bicycle_vmt is None:
            return self.data_not_available_card(
                detail="Bicycle VMT summaries are unavailable.",
                missing_items=["bicycle_vmt_by_facility_type"],
            )
        return bar_chart(
            nonempty(bicycle_vmt),
            x_col="facility_type",
            y_col="bicycle_vmt",
            title="Bicycle VMT by Facility Type",
            xaxis_title="Bicycle Facility Type",
            yaxis_title="Bicycle VMT",
            pct_col="pct",
            as_percent=self.as_percent,
        )

    def render_bicycle_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        return [self.render_bicycle_chart()]

    def render_body(self):
        return self.render_commercial_vmt_section()

    def render_commercial_vmt_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summary_ids = [
            "commercial_vehicle_validation_summary",
            "commercial_vehicle_vmt_validation_summary",
        ]
        if not any(
            self.state.get_summary_table_set(summary_id, self.weighting_key)
            for summary_id in summary_ids
        ):
            return []
        return [self.render_demo_commercial_chart()]

    def render_demo_commercial_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "commercial_vehicle_vmt_validation_summary"
            if self.demo_commercial_metric_sel.value == "VMT"
            else "commercial_vehicle_validation_summary"
        )
        data = self.state.get_summary_table_set(summary_id, self.weighting_key)
        if data is None:
            return self.data_not_available_card(
                detail="Commercial vehicle summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.demo_commercial_metric_sel.value
        breakdown = str(self.demo_commercial_breakdown_sel.value)
        time_period = str(self.demo_commercial_time_period_sel.value)
        commercial_vehicle_type = self.selected_demo_commercial_vehicle_type_raw()
        chart_data = self.get_filtered_view(
            "demo_commercial_vehicle",
            (
                self.weighting_key,
                metric,
                breakdown,
                time_period,
                commercial_vehicle_type,
            ),
            factory=lambda: demo_commercial_vehicle_chart_data(
                data,
                breakdown=breakdown,
                time_period=time_period,
                commercial_vehicle_type=commercial_vehicle_type,
                tod_col="tod",
                value_columns=EXTERNAL_COMMERCIAL_COLUMNS,
            ),
        )
        if breakdown == "Commercial Vehicle Type":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        xaxis_categoryarray = (
            _chart_category_order(chart_data, preferred=EXTERNAL_COMMERCIAL_TIME_ORDER)
            if breakdown == "Time Period"
            else _chart_category_order(
                chart_data,
                preferred=self.config.ordered_labels(
                    COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
                    EXTERNAL_COMMERCIAL_COLUMNS,
                ),
            )
        )
        return bar_chart(
            chart_data,
            x_col="category",
            y_col=(
                "value_percent"
                if self.as_percent and breakdown == "Time Period"
                else "value"
            ),
            title=f"Commercial Vehicle {metric} by {breakdown}",
            xaxis_title=breakdown,
            yaxis_title=(
                f"Percent of {metric} (%)"
                if self.as_percent and breakdown == "Time Period"
                else metric
            ),
            as_percent=False if self.as_percent and breakdown == "Time Period" else self.as_percent,
            xaxis_categoryarray=xaxis_categoryarray,
            showlegend=True,
        )

    def render_external_travel_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "external_vmt_validation_summary"
            if self.external_travel_metric_sel.value == "VMT"
            else "external_trip_validation_summary"
        )
        data = self.state.get_summary_table_set(summary_id, self.weighting_key)
        if data is None:
            return self.data_not_available_card(
                detail="External travel summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.external_travel_metric_sel.value
        breakdown = str(self.external_travel_breakdown_sel.value)
        time_period = str(self.external_travel_time_period_sel.value)
        trip_purpose = self.selected_external_travel_trip_purpose_raw()
        chart_data = self.get_filtered_view(
            "external_travel",
            (
                self.weighting_key,
                metric,
                breakdown,
                time_period,
                trip_purpose,
            ),
            factory=lambda: external_travel_chart_data(
                data,
                breakdown=breakdown,
                time_period=time_period,
                trip_purpose=trip_purpose,
                tod_col="tod",
                value_columns=EXTERNAL_TRAVEL_COLUMNS,
            ),
        )
        if breakdown == "Trip Purpose":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        xaxis_categoryarray = (
            _chart_category_order(chart_data, preferred=EXTERNAL_COMMERCIAL_TIME_ORDER)
            if breakdown == "Time Period"
            else _chart_category_order(
                chart_data,
                preferred=self.config.ordered_labels(
                    EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
                    EXTERNAL_TRAVEL_COLUMNS,
                ),
            )
        )
        return bar_chart(
            chart_data,
            x_col="category",
            y_col=(
                "value_percent"
                if self.as_percent and breakdown == "Time Period"
                else "value"
            ),
            title=f"External {metric} by {breakdown}",
            xaxis_title=breakdown,
            yaxis_title=(
                f"Percent of {metric} (%)"
                if self.as_percent and breakdown == "Time Period"
                else metric
            ),
            as_percent=False if self.as_percent and breakdown == "Time Period" else self.as_percent,
            xaxis_categoryarray=xaxis_categoryarray,
            showlegend=True,
        )

    def render_external_vmt_section(self) -> list[pn.viewable.Viewable]:
        summary_ids = [
            "external_trip_validation_summary",
            "external_vmt_validation_summary",
        ]
        if not any(
            self.state.get_summary_table_set(summary_id, self.weighting_key)
            for summary_id in summary_ids
        ):
            return []
        content: list[pn.viewable.Viewable] = [
            self.render_external_travel_chart(),
        ]
        return content


PAGE = DashboardPageDefinition(
    page_id="vmt",
    title="VMT Validation",
    group_id="validation",
    order=54,
    page_cls=VMTValidationPage,
    required_summary_ids=(
        PERSONAL_AUTO_VMT_SUMMARY_ID,
        NON_MOTORIZED_VMT_SUMMARY_ID,
        "bicycle_vmt_by_facility_type",
    ),
    optional_summary_ids=(
        "commercial_vehicle_validation_summary",
        "commercial_vehicle_vmt_validation_summary",
        "external_trip_validation_summary",
        "external_vmt_validation_summary",
    ),
)

VMTValidationPage.definition = PAGE
