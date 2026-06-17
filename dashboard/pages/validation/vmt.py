"""VMT validation page with personal auto, commercial, and bicycle VMT charts."""

from __future__ import annotations

import panel as pn
import polars as pl
import plotly.graph_objects as go

from dashboard.components import bar_chart, data_table, selector_row
from dashboard.helpers.category_helpers import column_value_union, nonempty
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

VMT_VIEW_OPTIONS = [
    "Total Commercial VMT",
    "External VMT Only",
    "Internal VMT Only",
    "External minus Internal VMT",
]
EXTERNAL_TOD_ORDER = ["EA", "AM", "MD", "PM", "EV", "EV1", "EV2"]
EXTERNAL_AUTO_MODE_COLUMNS = ["SOV", "HOV2", "HOV3", "Truck"]
EXTERNAL_COMMERCIAL_COLUMNS = ["car", "mu", "su"]
EXTERNAL_PURPOSE_COLUMNS = [
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
EXTERNAL_CATEGORY_COLORS = [
    "#4E79A7",
    "#F28E2B",
    "#59A14F",
    "#E15759",
    "#76B7B2",
    "#EDC948",
    "#B07AA1",
    "#9C755F",
    "#BAB0AC",
]
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
PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS = {
    "Time Period": "time_period",
    "Income Segment": "income_segment",
    "Household Size": "household_size",
    "Home Geography": "geography_id",
}
PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES = {
    "Time Period": "Time Period",
    "Income Segment": "Income Segment",
    "Household Size": "Household Size",
    "Home Geography": "Home Geography",
}
PERSONAL_AUTO_VMT_TIME_ORDER = ["EA", "AM", "MD", "PM", "EV", "EV1", "EV2", "Daily"]
PERSONAL_AUTO_VMT_TOP_GEOGRAPHIES = 25


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


def geography_id_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    geography_type: str,
) -> list[str]:
    """Return geography id selector options for the selected geography type."""
    values: list[str] = []
    seen: set[str] = set()
    for _, df in nonempty(data_list or []):
        if not {"geography_type", "geography_id"}.issubset(df.columns):
            continue
        filtered = df.with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
        )
        if geography_type != "All":
            filtered = filtered.filter(pl.col("geography_type") == geography_type)
        for value in filtered["geography_id"].drop_nulls().to_list():
            value_str = str(value)
            if value_str in seen:
                continue
            seen.add(value_str)
            values.append(value_str)
    values = _ordered_values(
        values,
        preferred=["all_geographies"] if geography_type == "all_geographies" else None,
    )
    if geography_type == "all_geographies":
        return values or ["all_geographies"]
    return ["All", *values] if values else ["All"]


def personal_auto_vmt_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    breakdown: str,
    geography_type: str,
    geography_id: str,
    time_period: str,
    income_segment: str,
    household_size: str,
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
        )
        if geography_type != "All":
            filtered = filtered.filter(pl.col("geography_type") == geography_type)
        if breakdown_col != "geography_id" and geography_id != "All":
            filtered = filtered.filter(pl.col("geography_id") == geography_id)
        if breakdown_col != "time_period" and time_period != "All":
            filtered = filtered.filter(pl.col("time_period") == time_period)
        if breakdown_col != "income_segment" and income_segment != "All":
            filtered = filtered.filter(pl.col("income_segment") == income_segment)
        if breakdown_col != "household_size" and household_size != "All":
            filtered = filtered.filter(pl.col("household_size") == household_size)

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
        elif breakdown_col == "household_size":
            chart_df = chart_df.with_columns(
                pl.col("category").cast(pl.Float64, strict=False).alias("_sort_order")
            ).sort("_sort_order", "category", nulls_last=True).drop("_sort_order")
        else:
            chart_df = chart_df.sort("category")
        out.append((label, chart_df))
    return out


def commercial_vmt_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    vmt_view: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Return chart-ready commercial VMT rows for the selected comparison view."""
    value_col = {
        "Total Commercial VMT": "total_vmt",
        "External VMT Only": "external_vmt",
        "Internal VMT Only": "internal_vmt",
        "External minus Internal VMT": "vmt_difference",
    }[vmt_view]
    out = []
    for label, df in nonempty(data_list):
        chart_df = (
            df.with_columns((pl.col("external_vmt") - pl.col("internal_vmt")).alias("vmt"))
            if value_col == "vmt_difference"
            else df.with_columns(pl.col(value_col).alias("vmt"))
        )
        out.append((label, chart_df.select("commercial_vehicle_type", "vmt")))
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


def wide_tod_bar_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    title: str,
    yaxis_title: str,
    barmode: str,
    category_order: list[str],
) -> pn.pane.Plotly:
    fig = go.Figure()
    for _run_index, (label, df) in enumerate(data_list):
        if df.is_empty() or not {"tod", "category", "value"}.issubset(df.columns):
            continue
        for category_index, category in enumerate(category_order):
            category_df = df.filter(pl.col("category") == category)
            if category_df.is_empty():
                continue
            fig.add_trace(
                go.Bar(
                    name=f"{label} - {category}",
                    x=category_df["tod"].to_list(),
                    y=category_df["value"].to_list(),
                    marker_color=EXTERNAL_CATEGORY_COLORS[
                        category_index % len(EXTERNAL_CATEGORY_COLORS)
                    ],
                    opacity=0.9 if len(data_list) == 1 else 0.65,
                    legendgroup=str(label),
                    hovertemplate=(
                        f"{label}<br>Category: {category}<br>"
                        "Time Period: %{x}<br>"
                        f"{yaxis_title}: " + "%{y:,.1f}<extra></extra>"
                    ),
                )
            )
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top"),
        height=420,
        xaxis_title="Time Period",
        yaxis_title=yaxis_title,
        barmode=barmode,
        legend=dict(orientation="h", yanchor="bottom", y=1.12, x=0),
        margin=dict(l=60, r=20, t=90, b=90),
        title_font=dict(size=16),
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
    )
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=EXTERNAL_TOD_ORDER,
        automargin=True,
    )
    fig.update_yaxes(automargin=True)
    return pn.pane.Plotly(fig, sizing_mode="stretch_width")


class VMTValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
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
                name="Geography Type",
                options=["all_geographies"],
                value="all_geographies",
            ),
            label="Geography Type",
        )
        self.personal_vmt_geography_sel = self.selector(
            "personal_auto_vmt_geography",
            widget=pn.widgets.Select(
                name="Geography",
                options=["all_geographies"],
                value="all_geographies",
            ),
            label="Geography",
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
        self.vmt_view_sel = self.selector(
            "commercial_vmt_view",
            widget=pn.widgets.Select(
                name="Commercial VMT View",
                options=VMT_VIEW_OPTIONS,
                value=VMT_VIEW_OPTIONS[0],
            ),
            label="Commercial VMT View",
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
        self.external_trip_metric_sel = self.selector(
            "external_trip_metric",
            widget=pn.widgets.Select(
                name="External Travel Metric",
                options=["Trips", "VMT"],
                value="Trips",
            ),
            label="External Travel Metric",
        )
        self._personal_vmt_body = self.section(
            "personal_auto_vmt_body",
            selectors=(
                "personal_auto_vmt_breakdown",
                "personal_auto_vmt_geography_type",
                "personal_auto_vmt_geography",
                "personal_auto_vmt_time_period",
                "personal_auto_vmt_income_segment",
                "personal_auto_vmt_household_size",
            ),
            render=self.render_personal_auto_vmt_section,
        )
        self._body = self.section(
            "vmt_body",
            selectors=(
                "commercial_vmt_view",
                "external_commercial_metric",
                "external_trip_metric",
            ),
            render=self.render_body,
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
                self.personal_vmt_income_segment_sel,
                self.personal_vmt_household_size_sel,
            ),
            self._personal_vmt_body,
            pn.pane.Markdown("### Commercial and Bicycle VMT"),
            selector_row(self.vmt_view_sel),
            selector_row(
                self.external_commercial_metric_sel,
                self.external_trip_metric_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        personal_vmt = self.state.get_summary_table_set(
            PERSONAL_AUTO_VMT_SUMMARY_ID,
            self.weighting_key,
        )
        geography_type_options = _selector_values(
            personal_vmt,
            "geography_type",
            preferred=["all_geographies"],
        ) or ["all_geographies"]
        self.personal_vmt_geography_type_sel.options = geography_type_options
        if self.personal_vmt_geography_type_sel.value not in geography_type_options:
            self.personal_vmt_geography_type_sel.value = (
                "all_geographies"
                if "all_geographies" in geography_type_options
                else geography_type_options[0]
            )

        geography_options = geography_id_options(
            personal_vmt,
            str(self.personal_vmt_geography_type_sel.value),
        )
        self.personal_vmt_geography_sel.options = geography_options
        if self.personal_vmt_geography_sel.value not in geography_options:
            self.personal_vmt_geography_sel.value = (
                "all_geographies"
                if "all_geographies" in geography_options
                else geography_options[0]
            )

        time_period_options = _selector_values(
            personal_vmt,
            "time_period",
            include_all=True,
            preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
        ) or ["All"]
        self.personal_vmt_time_period_sel.options = time_period_options
        if self.personal_vmt_time_period_sel.value not in time_period_options:
            self.personal_vmt_time_period_sel.value = "All"

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
        self.personal_vmt_income_segment_sel.disabled = False
        self.personal_vmt_household_size_sel.disabled = False
        breakdown_filter_selector = {
            "Time Period": self.personal_vmt_time_period_sel,
            "Income Segment": self.personal_vmt_income_segment_sel,
            "Household Size": self.personal_vmt_household_size_sel,
        }.get(str(self.personal_vmt_breakdown_sel.value))
        if breakdown_filter_selector is not None:
            if "All" in breakdown_filter_selector.options:
                breakdown_filter_selector.value = "All"
            breakdown_filter_selector.disabled = True

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
        geography_type = str(self.personal_vmt_geography_type_sel.value)
        geography_id = str(self.personal_vmt_geography_sel.value)
        time_period = str(self.personal_vmt_time_period_sel.value)
        income_segment = str(self.personal_vmt_income_segment_sel.value)
        household_size = str(self.personal_vmt_household_size_sel.value)
        chart_data = self.get_filtered_view(
            "personal_auto_vmt",
            (
                breakdown,
                geography_type,
                geography_id,
                time_period,
                income_segment,
                household_size,
            ),
            factory=lambda: personal_auto_vmt_chart_data(
                personal_vmt,
                breakdown=breakdown,
                geography_type=geography_type,
                geography_id=geography_id,
                time_period=time_period,
                income_segment=income_segment,
                household_size=household_size,
            ),
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
        else:
            xaxis_categoryarray = list(dict.fromkeys(str(value) for value in category_values))
        chart = bar_chart(
            chart_data,
            x_col="category",
            y_col="auto_vmt",
            title=f"Personal Auto VMT by {breakdown}",
            xaxis_title=PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES[breakdown],
            yaxis_title="Vehicle Miles Traveled",
            as_percent=self.as_percent,
            xaxis_categoryarray=xaxis_categoryarray,
        )
        return [chart]

    def render_commercial_chart(self) -> pn.viewable.Viewable:
        commercial_vmt = self.state.get_summary_table_set(
            "commercial_vmt_totals",
            self.weighting_key,
        )
        if commercial_vmt is None:
            return self.data_not_available_card(
                detail="Commercial VMT summaries are unavailable.",
                missing_items=["commercial_vmt_totals"],
            )
        vmt_view = self.vmt_view_sel.value
        commercial_vehicle_type_values = sorted(
            {
                str(value)
                for _, df in nonempty(commercial_vmt)
                for value in (
                    df["commercial_vehicle_type"].cast(pl.Utf8).to_list()
                    if "commercial_vehicle_type" in df.columns
                    else []
                )
            }
        )
        commercial_vmt_data = self.get_filtered_view(
            "commercial_vmt",
            vmt_view,
            factory=lambda: commercial_vmt_chart_data(commercial_vmt, vmt_view),
        )
        return bar_chart(
            commercial_vmt_data,
            x_col="commercial_vehicle_type",
            y_col="vmt",
            title=f"External vs. Internal Commercial Vehicle VMT - {vmt_view}",
            xaxis_title="Commercial Vehicle Type",
            yaxis_title="Vehicle Miles Traveled",
            as_percent=self.as_percent,
            xaxis_categoryarray=commercial_vehicle_type_values,
        )

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

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        content = [
            self.render_commercial_chart(),
            self.render_bicycle_chart(),
        ]
        content.extend(self.render_external_vmt_section())
        return content

    def render_external_auto_vmt_chart(self) -> pn.viewable.Viewable:
        auto_vmt = self.state.get_summary_table_set(
            "external_auto_vmt_summary",
            self.weighting_key,
        )
        if auto_vmt is None:
            return self.data_not_available_card(
                detail="External auto VMT summaries are unavailable.",
                missing_items=["external_auto_vmt_summary"],
            )
        chart_data = self.get_filtered_view(
            "external_auto_vmt",
            self.weighting_key,
            factory=lambda: wide_tod_chart_data(
                auto_vmt,
                tod_col="TOD",
                value_columns=EXTERNAL_AUTO_MODE_COLUMNS,
            ),
        )
        return wide_tod_bar_chart(
            chart_data,
            title="External Auto VMT by Time Period and Mode",
            yaxis_title="VMT",
            barmode="group",
            category_order=EXTERNAL_AUTO_MODE_COLUMNS,
        )

    def render_external_commercial_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "external_commercial_vehicle_vmt_summary"
            if self.external_commercial_metric_sel.value == "VMT"
            else "external_commercial_vehicle_summary"
        )
        data = self.state.get_summary_table_set(summary_id, self.weighting_key)
        if data is None:
            return self.data_not_available_card(
                detail="External commercial vehicle summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.external_commercial_metric_sel.value
        chart_data = self.get_filtered_view(
            "external_commercial_vehicle",
            (self.weighting_key, metric),
            factory=lambda: wide_tod_chart_data(
                data,
                tod_col="tod",
                value_columns=EXTERNAL_COMMERCIAL_COLUMNS,
            ),
        )
        return wide_tod_bar_chart(
            chart_data,
            title=f"External Commercial Vehicle {metric} by Time Period and Type",
            yaxis_title=metric,
            barmode="group",
            category_order=EXTERNAL_COMMERCIAL_COLUMNS,
        )

    def render_external_trip_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "external_external_vmt_summary"
            if self.external_trip_metric_sel.value == "VMT"
            else "external_external_trip_summary"
        )
        data = self.state.get_summary_table_set(summary_id, self.weighting_key)
        if data is None:
            return self.data_not_available_card(
                detail="External travel summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.external_trip_metric_sel.value
        chart_data = self.get_filtered_view(
            "external_travel",
            (self.weighting_key, metric),
            factory=lambda: wide_tod_chart_data(
                data,
                tod_col="tod",
                value_columns=EXTERNAL_PURPOSE_COLUMNS,
            ),
        )
        return wide_tod_bar_chart(
            chart_data,
            title=f"External Travel {metric} by Time Period and Purpose",
            yaxis_title=metric,
            barmode="stack",
            category_order=EXTERNAL_PURPOSE_COLUMNS,
        )

    def render_external_vmt_section(self) -> list[pn.viewable.Viewable]:
        summary_ids = [
            "external_auto_vmt_summary",
            "external_commercial_vehicle_summary",
            "external_commercial_vehicle_vmt_summary",
            "external_external_trip_summary",
            "external_external_vmt_summary",
        ]
        if not any(
            self.state.get_summary_table_set(summary_id, self.weighting_key)
            for summary_id in summary_ids
        ):
            return []
        auto_vmt = self.state.get_summary_table_set(
            "external_auto_vmt_summary",
            self.weighting_key,
        )
        content: list[pn.viewable.Viewable] = [
            pn.pane.Markdown("### External VMT and Travel Summaries"),
            self.render_external_auto_vmt_chart(),
            pn.Row(
                self.render_external_commercial_chart(),
                self.render_external_trip_chart(),
                sizing_mode="stretch_width",
            ),
        ]
        if auto_vmt is not None:
            content.append(data_table(auto_vmt, "External Auto VMT Summary"))
        return content


PAGE = DashboardPageDefinition(
    page_id="vmt",
    title="VMT Validation",
    group_id="validation",
    order=54,
    page_cls=VMTValidationPage,
    required_summary_ids=(
        PERSONAL_AUTO_VMT_SUMMARY_ID,
        "commercial_vmt_totals",
        "bicycle_vmt_by_facility_type",
    ),
    optional_summary_ids=(
        "external_auto_vmt_summary",
        "external_commercial_vehicle_summary",
        "external_commercial_vehicle_vmt_summary",
        "external_external_trip_summary",
        "external_external_vmt_summary",
    ),
)

VMTValidationPage.definition = PAGE
