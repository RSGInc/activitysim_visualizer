"""VMT validation page with personal auto, commercial, and bicycle VMT charts."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, selector_row
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
PERSONAL_AUTO_VMT_SUMMARY_ID = "auto_vmt_by_home_geography_income_hhsize_time_period"
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
PERSONAL_AUTO_VMT_ALL_MODES = "All Auto"
PERSONAL_AUTO_VMT_MODE_CATEGORY_ID = "mode"
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


def external_commercial_vehicle_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    breakdown: str,
    time_period: str = EXTERNAL_COMMERCIAL_DAILY_PERIOD,
    commercial_vehicle_type: str = "All",
    tod_col: str = "tod",
    value_columns: list[str] | None = None,
    exclude_total_period: bool = True,
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate external commercial vehicle summaries for one chart breakdown."""
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


def external_commercial_filter_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    config,
    tod_col: str = "tod",
    value_columns: list[str] | None = None,
) -> tuple[list[str], tuple[list[str], dict[str, str | None]]]:
    """Return time-period and vehicle-type filter options for external commercial data."""
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


class VMTValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        personal_vmt = self.state.get_summary_table_set(
            PERSONAL_AUTO_VMT_SUMMARY_ID,
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
        self.external_commercial_vehicle_type_raw_by_label = {"All": "All"}
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
        self.external_commercial_metric_sel = self.selector(
            "external_commercial_metric",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Metric",
                options=["Trips", "VMT"],
                value="Trips",
            ),
            label="Commercial Vehicle Metric",
        )
        self.external_commercial_breakdown_sel = self.selector(
            "external_commercial_breakdown",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Breakdown",
                options=EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS,
                value=EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS[0],
            ),
            label="Commercial Vehicle Breakdown",
        )
        self.external_commercial_vehicle_type_sel = self.selector(
            "external_commercial_vehicle_type",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Type",
                options=["All"],
                value="All",
            ),
            label="Commercial Vehicle Type",
        )
        self.external_commercial_time_period_sel = self.selector(
            "external_commercial_time_period",
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
        self._body = self.section(
            "vmt_body",
            selectors=(
                "external_commercial_metric",
                "external_commercial_breakdown",
                "external_commercial_vehicle_type",
                "external_commercial_time_period",
            ),
            render=self.render_body,
        )
        self._bicycle_body = self.section(
            "bicycle_vmt_body",
            render=self.render_bicycle_section,
        )
        return self.new_section(
            pn.pane.Markdown("## VMT Validation"),
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
            pn.pane.Markdown("### Commercial VMT and Travel"),
            selector_row(
                self.external_commercial_metric_sel,
                self.external_commercial_breakdown_sel,
                self.external_commercial_vehicle_type_sel,
                self.external_commercial_time_period_sel,
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
        }.get(str(self.personal_vmt_breakdown_sel.value))
        if breakdown_filter_selector is not None:
            if "All" in breakdown_filter_selector.options:
                breakdown_filter_selector.value = "All"
            breakdown_filter_selector.disabled = True

        external_commercial_summary_id = (
            "external_commercial_vehicle_vmt_summary"
            if self.external_commercial_metric_sel.value == "VMT"
            else "external_commercial_vehicle_summary"
        )
        external_commercial_data = self.state.get_summary_table_set(
            external_commercial_summary_id,
            self.weighting_key,
        )
        (
            time_period_options,
            (vehicle_type_options, self.external_commercial_vehicle_type_raw_by_label),
        ) = external_commercial_filter_options(
            external_commercial_data,
            config=self.config,
        )
        for widget, options in (
            (self.external_commercial_time_period_sel, time_period_options),
            (self.external_commercial_vehicle_type_sel, vehicle_type_options),
        ):
            widget.options = options or ["All"]
            if widget.value not in widget.options:
                widget.value = widget.options[0]

        self.external_commercial_time_period_sel.disabled = False
        self.external_commercial_vehicle_type_sel.disabled = False
        external_breakdown_filter_selector = {
            "Time Period": self.external_commercial_time_period_sel,
            "Commercial Vehicle Type": self.external_commercial_vehicle_type_sel,
        }.get(str(self.external_commercial_breakdown_sel.value))
        if external_breakdown_filter_selector is not None:
            if "All" in external_breakdown_filter_selector.options:
                external_breakdown_filter_selector.value = "All"
            elif external_breakdown_filter_selector.options:
                external_breakdown_filter_selector.value = (
                    external_breakdown_filter_selector.options[0]
                )
            external_breakdown_filter_selector.disabled = True

    def selected_personal_vmt_geography_type_raw(self) -> str:
        selected = str(self.personal_vmt_geography_type_sel.value)
        raw_value = self.personal_vmt_geo_type_raw_by_label.get(selected, selected)
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def export_ignored_selectors(
        self,
        section_id: str,
        selected_values: dict[str, str],
    ) -> set[str]:
        if section_id != "personal_auto_vmt_body":
            return set()

        breakdown = selected_values.get("personal_auto_vmt_breakdown")
        if breakdown == "Home Geography":
            return {"personal_auto_vmt_geography"}
        if breakdown:
            return {
                "personal_auto_vmt_geography_type",
                "personal_auto_vmt_geography",
            }
        return set()

    def selected_personal_vmt_geography_raw(self) -> str:
        selected = str(self.personal_vmt_geography_sel.value)
        raw_value = self.personal_vmt_geo_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_personal_vmt_mode_raw(self) -> str:
        selected = str(self.personal_vmt_mode_sel.value)
        raw_value = self.personal_vmt_mode_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_external_commercial_vehicle_type_raw(self) -> str:
        selected = str(self.external_commercial_vehicle_type_sel.value)
        raw_value = self.external_commercial_vehicle_type_raw_by_label.get(
            selected,
            selected,
        )
        return "All" if raw_value is None else str(raw_value)

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
        if not self.state.run_labels:
            return [self.no_runs_message()]
        return self.render_external_vmt_section()

    def render_external_commercial_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "external_commercial_vehicle_vmt_summary"
            if self.external_commercial_metric_sel.value == "VMT"
            else "external_commercial_vehicle_summary"
        )
        data = self.state.get_summary_table_set(summary_id, self.weighting_key)
        if data is None:
            return self.data_not_available_card(
                detail="Commercial vehicle summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.external_commercial_metric_sel.value
        breakdown = str(self.external_commercial_breakdown_sel.value)
        time_period = str(self.external_commercial_time_period_sel.value)
        commercial_vehicle_type = self.selected_external_commercial_vehicle_type_raw()
        chart_data = self.get_filtered_view(
            "external_commercial_vehicle",
            (
                self.weighting_key,
                metric,
                breakdown,
                time_period,
                commercial_vehicle_type,
            ),
            factory=lambda: external_commercial_vehicle_chart_data(
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
            EXTERNAL_COMMERCIAL_TIME_ORDER
            if breakdown == "Time Period"
            else self.config.ordered_labels(
                COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
                EXTERNAL_COMMERCIAL_COLUMNS,
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

    def render_external_vmt_section(self) -> list[pn.viewable.Viewable]:
        summary_ids = [
            "external_commercial_vehicle_summary",
            "external_commercial_vehicle_vmt_summary",
        ]
        if not any(
            self.state.get_summary_table_set(summary_id, self.weighting_key)
            for summary_id in summary_ids
        ):
            return []
        content: list[pn.viewable.Viewable] = [
            self.render_external_commercial_chart(),
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
        "bicycle_vmt_by_facility_type",
    ),
    optional_summary_ids=(
        "external_commercial_vehicle_summary",
        "external_commercial_vehicle_vmt_summary",
    ),
)

VMTValidationPage.definition = PAGE
