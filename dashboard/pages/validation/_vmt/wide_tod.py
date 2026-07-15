"""Commercial and external wide time-of-day VMT transformations."""

from __future__ import annotations

import polars as pl

from dashboard.helpers.category_helpers import nonempty, raw_display_options

from .contracts import (
    COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
    EXTERNAL_COMMERCIAL_COLUMNS,
    EXTERNAL_COMMERCIAL_DAILY_PERIOD,
    EXTERNAL_COMMERCIAL_TIME_ORDER,
    EXTERNAL_TOD_ORDER,
    EXTERNAL_TRAVEL_COLUMNS,
    EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
    EXTERNAL_TRAVEL_TOTAL_COLUMN,
)
from .segmented import _ordered_values


def _with_value_percent_of_daily(chart_df: pl.DataFrame) -> pl.DataFrame:
    """Add percent values using Daily as the denominator when present."""
    if chart_df.is_empty() or not {"category", "value"}.issubset(chart_df.columns):
        return chart_df

    daily_total = chart_df.filter(
        pl.col("category") == EXTERNAL_COMMERCIAL_DAILY_PERIOD
    )["value"].sum()
    denominator = (
        daily_total if daily_total and daily_total > 0 else chart_df["value"].sum()
    )
    if not denominator or denominator <= 0:
        return chart_df.with_columns(pl.lit(0.0).alias("value_percent"))

    return chart_df.with_columns(
        (pl.col("value") / denominator * 100.0).alias("value_percent")
    )


def wide_tod_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    tod_col: str,
    value_columns: list[str],
    exclude_total_period: bool = True,
) -> list[tuple[str, pl.DataFrame]]:
    """Return long chart-ready rows from external wide time-of-day summaries."""
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
        if breakdown != "Time Period" and time_period not in (
            "All",
            EXTERNAL_COMMERCIAL_DAILY_PERIOD,
        ):
            long_df = long_df.filter(pl.col("time_period") == time_period)
        if breakdown != "Commercial Vehicle Type" and commercial_vehicle_type != "All":
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
