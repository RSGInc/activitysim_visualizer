"""Traffic validation page with count and screenline comparison charts."""

from __future__ import annotations

import math

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, scatter_chart, selector_row
from dashboard.helpers.category_helpers import (
    label_category_data,
    label_category_frame,
    nonempty,
    raw_display_options,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config

DEMO_TRAFFIC_TIME_PERIODS = {
    "AM": "am_vol",
    "MD": "md_vol",
    "PM": "pm_vol",
    "Day": "day_vol",
}

FACILITY_TYPE_CATEGORY_ID = "facility_type"


def validation_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate one validation summary list to one observed/modeled point per id."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df
        id_col = None
        if "count_location_id" in filtered.columns:
            id_col = "count_location_id"
        elif "screenline_id" in filtered.columns:
            id_col = "screenline_id"
        if id_col is not None:
            filtered = (
                filtered.group_by(id_col)
                .agg(
                    observed_volume=pl.col("observed_volume").sum(),
                    modeled_volume=pl.col("modeled_volume").sum(),
                )
                .sort(id_col)
            )
        out.append((label, filtered))
    return out


def demo_facility_options(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
) -> tuple[list[str], dict[str, str | None]]:
    values: list[str] = []
    seen: set[str] = set()
    for data_list in data_lists:
        for _, df in nonempty(data_list or []):
            for column in ("facility_type", "FACTYPE"):
                if column not in df.columns:
                    continue
                for value in df[column].drop_nulls().cast(pl.Utf8).to_list():
                    value_str = str(value)
                    if value_str == "All" or value_str in seen:
                        continue
                    values.append(value_str)
                    seen.add(value_str)
    ordered_values = config.ordered_values(FACILITY_TYPE_CATEGORY_ID, values)
    return raw_display_options(
        ordered_values,
        category_id=FACILITY_TYPE_CATEGORY_ID,
        config=config,
        total_raw="All",
        total_label="All",
    )


def _filter_facility(df: pl.DataFrame, facility_type: str) -> pl.DataFrame:
    if facility_type == "All" or "FACTYPE" not in df.columns:
        return df
    return df.with_columns(pl.col("FACTYPE").cast(pl.Utf8)).filter(
        pl.col("FACTYPE") == facility_type
    )


def demo_count_scatter_data(
    scatter_list: list[tuple[str, pl.DataFrame]],
    *,
    period: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(scatter_list):
        required = {"facility_type", "period", "observed_volume", "modeled_volume"}
        if not required.issubset(set(df.columns)):
            continue
        filtered = df.with_columns(
            pl.col("facility_type").cast(pl.Utf8),
            pl.col("period").cast(pl.Utf8),
        ).filter(pl.col("period") == period)
        if facility_type != "All":
            filtered = filtered.filter(pl.col("facility_type") == facility_type)
        out.append(
            (
                label,
                filtered.select(
                    "id",
                    "facility_type",
                    "period",
                    "observed_volume",
                    "modeled_volume",
                ).sort("id"),
            )
        )
    return out


def demo_count_scatter_data_from_sources(
    count_list: list[tuple[str, pl.DataFrame]],
    volume_list: list[tuple[str, pl.DataFrame]],
    *,
    volume_col: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    volume_by_label = dict(volume_list)
    out: list[tuple[str, pl.DataFrame]] = []
    for label, count_df in nonempty(count_list):
        volume_df = volume_by_label.get(label)
        if volume_df is None or volume_df.is_empty():
            continue
        count_df = _filter_facility(count_df, facility_type)
        volume_df = _filter_facility(volume_df, facility_type)
        if volume_col not in count_df.columns or volume_col not in volume_df.columns:
            continue
        joined = (
            count_df.select(
                "id",
                pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                pl.col(volume_col).alias("observed_volume"),
            )
            .join(
                volume_df.select(
                    "id",
                    pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                    pl.col(volume_col).alias("modeled_volume"),
                ),
                on=["id", "facility_type"],
                how="inner",
            )
            .sort("id")
        )
        out.append((label, joined))
    return out


def demo_count_fit_line_data(
    fit_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    period: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(fit_list or []):
        required = {
            "facility_type",
            "period",
            "slope",
            "intercept",
            "r_squared",
            "n_locations",
            "observed_min",
            "observed_max",
            "equation_label",
            "r_squared_label",
        }
        if not required.issubset(set(df.columns)):
            continue
        selected = (
            df.with_columns(
                pl.col("facility_type").cast(pl.Utf8),
                pl.col("period").cast(pl.Utf8),
            )
            .filter(
                (pl.col("period") == period)
                & (pl.col("facility_type") == str(facility_type))
                & pl.col("slope").is_not_null()
                & pl.col("intercept").is_not_null()
                & pl.col("observed_min").is_not_null()
                & pl.col("observed_max").is_not_null()
            )
            .head(1)
        )
        if selected.is_empty():
            continue
        row = selected.row(0, named=True)
        observed_min = float(row["observed_min"])
        observed_max = float(row["observed_max"])
        slope = float(row["slope"])
        intercept = float(row["intercept"])
        annotation = (
            f"{label}<br>{row['equation_label']}<br>"
            f"{row['r_squared_label']}<br>n = {int(row['n_locations'])}"
        )
        out.append(
            (
                label,
                pl.DataFrame(
                    {
                        "observed_volume": [observed_min, observed_max],
                        "modeled_volume": [
                            slope * observed_min + intercept,
                            slope * observed_max + intercept,
                        ],
                        "annotation": [annotation, annotation],
                    }
                ),
            )
        )
    return out


def _r_squared_from_points(points: pl.DataFrame) -> float | None:
    if points.height < 2:
        return None
    x = [float(value) for value in points["observed_volume"].to_list()]
    y = [float(value) for value in points["modeled_volume"].to_list()]
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    ss_xx = sum((value - x_mean) ** 2 for value in x)
    if math.isclose(ss_xx, 0.0):
        return None
    ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    fitted = [slope * xi + intercept for xi in x]
    sse = sum((yi - yhat) ** 2 for yi, yhat in zip(y, fitted))
    ss_yy = sum((yi - y_mean) ** 2 for yi in y)
    if math.isclose(ss_yy, 0.0):
        return 1.0 if math.isclose(sse, 0.0) else 0.0
    return max(0.0, min(1.0, 1.0 - sse / ss_yy))


def _fit_r_squared_lookup(
    fit_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    label: str,
    period: str,
    facility_type: str,
) -> dict[str, float]:
    if not fit_list:
        return {}
    fit_by_label = dict(fit_list)
    fit_df = fit_by_label.get(label)
    if fit_df is None or fit_df.is_empty():
        return {}
    required = {"facility_type", "period", "r_squared"}
    if not required.issubset(set(fit_df.columns)):
        return {}
    selected = fit_df.with_columns(
        pl.col("facility_type").cast(pl.Utf8),
        pl.col("period").cast(pl.Utf8),
    ).filter(
        (pl.col("period") == period)
        & (pl.col("facility_type") != "All")
        & pl.col("r_squared").is_not_null()
    )
    if facility_type != "All":
        selected = selected.filter(pl.col("facility_type") == facility_type)
    return {
        str(row["facility_type"]): float(row["r_squared"])
        for row in selected.select("facility_type", "r_squared").iter_rows(named=True)
    }


def demo_facility_comparison_table(
    scatter_data: list[tuple[str, pl.DataFrame]],
    fit_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    period: str,
    facility_type: str,
    config: Config,
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate count-location observed/modeled comparisons by facility type."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(scatter_data):
        required = {"facility_type", "observed_volume", "modeled_volume"}
        if df is None or df.is_empty() or not required.issubset(set(df.columns)):
            continue
        points = (
            df.select(
                pl.col("facility_type").cast(pl.Utf8),
                pl.col("observed_volume").cast(pl.Float64),
                pl.col("modeled_volume").cast(pl.Float64),
            )
            .drop_nulls(["facility_type", "observed_volume", "modeled_volume"])
            .filter(pl.col("facility_type") != "All")
        )
        if facility_type != "All":
            points = points.filter(pl.col("facility_type") == facility_type)
        if points.is_empty():
            continue

        r_squared_lookup = _fit_r_squared_lookup(
            fit_list,
            label=label,
            period=period,
            facility_type=facility_type,
        )
        facility_types = config.ordered_values(
            FACILITY_TYPE_CATEGORY_ID,
            [str(value) for value in points["facility_type"].unique().to_list()],
        )
        rows: list[dict[str, object]] = []
        for raw_facility_type in facility_types:
            facility_points = points.filter(
                pl.col("facility_type") == raw_facility_type
            )
            if facility_points.is_empty():
                continue
            observed = [
                float(value)
                for value in facility_points["observed_volume"].to_list()
            ]
            modeled = [
                float(value) for value in facility_points["modeled_volume"].to_list()
            ]
            total_observed = sum(observed)
            total_modeled = sum(modeled)
            differences = [model - observe for observe, model in zip(observed, modeled)]
            rmse = math.sqrt(
                sum(difference**2 for difference in differences) / len(differences)
            )
            percent_value = (
                None
                if total_observed == 0.0
                else ((total_modeled - total_observed) / total_observed) * 100.0
            )
            percent_difference = (
                "" if percent_value is None else f"{percent_value:.2f}%"
            )
            rows.append(
                {
                    "Facility Type": config.label_value(
                        FACILITY_TYPE_CATEGORY_ID,
                        raw_facility_type,
                    ),
                    "Total Observed Count": total_observed,
                    "Total Modeled Count": total_modeled,
                    "% Difference": percent_difference,
                    "RMSE": rmse,
                    "R^2": r_squared_lookup.get(raw_facility_type)
                    if raw_facility_type in r_squared_lookup
                    else _r_squared_from_points(facility_points),
                }
            )
        if rows:
            out.append((label, pl.DataFrame(rows)))
    return out


def demo_link_aggregate_data(
    link_list: list[tuple[str, pl.DataFrame]],
    *,
    volume_col: str,
    facility_type: str,
    config: Config | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(link_list):
        if volume_col not in df.columns:
            continue
        filtered = _filter_facility(df, facility_type)
        chart_df = (
            filtered.with_columns(pl.col("FACTYPE").cast(pl.Utf8))
            .group_by("FACTYPE")
            .agg(pl.col(volume_col).sum().alias("volume"))
            .sort("FACTYPE")
        )
        if config is not None:
            chart_df = label_category_frame(
                chart_df,
                source_col="FACTYPE",
                category_id=FACILITY_TYPE_CATEGORY_ID,
                config=config,
                target_col="facility_type_label",
            )
        out.append((label, chart_df))
    return out


def demo_volume_comparison_table(
    count_list: list[tuple[str, pl.DataFrame]],
    volume_list: list[tuple[str, pl.DataFrame]],
    *,
    link_list: list[tuple[str, pl.DataFrame]] | None = None,
    volume_col: str,
    facility_type: str,
    top_n: int,
) -> list[tuple[str, pl.DataFrame]]:
    volume_by_label = dict(volume_list)
    link_by_label = dict(link_list or [])
    quantity_a_column = "Observed Link Volume"
    quantity_b_column = "Modeled Link Volume"
    difference_column = "Difference"
    percent_difference_column = "% Difference"
    out: list[tuple[str, pl.DataFrame]] = []
    for label, count_df in nonempty(count_list):
        volume_df = volume_by_label.get(label)
        if volume_df is None or volume_df.is_empty():
            continue
        if volume_col not in count_df.columns or volume_col not in volume_df.columns:
            continue
        required = {"id", "FACTYPE"}
        if not required.issubset(count_df.columns) or not required.issubset(
            volume_df.columns
        ):
            continue

        count_filtered = _filter_facility(count_df, facility_type)
        volume_filtered = _filter_facility(volume_df, facility_type)
        joined = (
            count_filtered.select(
                pl.col("id").cast(pl.Int64, strict=False),
                pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                pl.col(volume_col).cast(pl.Float64).alias("_quantity_a"),
            )
            .join(
                volume_filtered.select(
                    pl.col("id").cast(pl.Int64, strict=False),
                    pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                    pl.col(volume_col).cast(pl.Float64).alias("_quantity_b"),
                ),
                on=["id", "facility_type"],
                how="inner",
            )
            .filter(
                pl.col("id").is_not_null()
                & pl.col("facility_type").is_not_null()
                & pl.col("_quantity_a").is_not_null()
                & pl.col("_quantity_b").is_not_null()
            )
        )
        link_df = link_by_label.get(label)
        has_link_metadata = (
            link_df is not None
            and {"id", "From_Node", "To_Node"}.issubset(link_df.columns)
        )
        if has_link_metadata:
            link_metadata = (
                link_df.select(
                    pl.col("id").cast(pl.Int64, strict=False),
                    pl.col("From_Node"),
                    pl.col("To_Node"),
                )
                .drop_nulls("id")
                .unique("id")
            )
            joined = joined.join(link_metadata, on="id", how="left")

        joined = (
            joined.sort(["_quantity_b", "id"], descending=[True, False])
            .head(top_n)
        )
        metadata_columns: list[str] = []
        if has_link_metadata:
            for column in ("From_Node", "To_Node"):
                if joined.select(pl.col(column).is_not_null().any()).item():
                    metadata_columns.append(column)
        rows = []
        for row in joined.iter_rows(named=True):
            observed = float(row["_quantity_a"])
            modeled = float(row["_quantity_b"])
            difference = modeled - observed
            percent_difference = (
                ""
                if observed == 0.0
                else f"{(difference / observed) * 100.0:.2f}%"
            )
            table_row = {
                "link_id": row["id"],
                "facility_type": row["facility_type"],
                quantity_a_column: observed,
                quantity_b_column: modeled,
                difference_column: difference,
                percent_difference_column: percent_difference,
            }
            for metadata_column in metadata_columns:
                table_row[metadata_column] = row.get(metadata_column)
            rows.append(table_row)
        columns = [
            "link_id",
            "facility_type",
            *metadata_columns,
            quantity_a_column,
            quantity_b_column,
            difference_column,
            percent_difference_column,
        ]
        table = pl.DataFrame(rows).select(columns) if rows else pl.DataFrame()
        if not table.is_empty():
            out.append((label, table))
    return out


class TrafficValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        demo_link_list = self.state.get_summary_table_set(
            "demo_link_summary", "weighted"
        )
        demo_count_list = self.state.get_summary_table_set(
            "demo_count_location_counts", "weighted"
        )
        demo_volume_list = self.state.get_summary_table_set(
            "demo_count_location_volumes", "weighted"
        )
        demo_scatter_list = self.state.get_summary_table_set(
            "demo_count_location_scatter", "weighted"
        )
        demo_fit_list = self.state.get_summary_table_set(
            "demo_count_location_fit", "weighted"
        )
        facility_opts, self.demo_facility_raw_by_label = demo_facility_options(
            demo_link_list,
            demo_count_list,
            demo_volume_list,
            demo_scatter_list,
            demo_fit_list,
            config=self.config,
        )
        self.demo_period_sel = self.selector(
            "demo_period",
            widget=pn.widgets.Select(
                name="Period",
                options=list(DEMO_TRAFFIC_TIME_PERIODS),
                value="Day",
            ),
            label="Period",
        )
        self.demo_facility_sel = self.selector(
            "demo_facility_type",
            widget=pn.widgets.Select(
                name="Facility Type",
                options=facility_opts,
                value=facility_opts[0],
            ),
            label="Facility Type",
        )
        self.demo_top_period_sel = self.selector(
            "demo_top_period",
            widget=pn.widgets.Select(
                name="Period",
                options=list(DEMO_TRAFFIC_TIME_PERIODS),
                value="Day",
            ),
            label="Period",
        )
        self.demo_top_n_sel = self.selector(
            "demo_top_n",
            widget=pn.widgets.Select(
                name="Top N by Modeled Volume",
                options=[10, 25, 50, 100],
                value=25,
            ),
            label="Top N by Modeled Volume",
        )
        self._external_volume_body = self.section(
            "traffic_volume_body",
            selectors=(
                "demo_period",
                "demo_facility_type",
            ),
            render=self.render_demo_traffic_section,
        )
        self._external_top_body = self.section(
            "traffic_top_count_body",
            selectors=(
                "demo_facility_type",
                "demo_top_period",
                "demo_top_n",
            ),
            render=self.render_demo_top_count_section,
        )
        self._screenline_body = self.section(
            "screenline_flow_body",
            render=self.render_screenline_flow_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Traffic Validation"),
            selector_row(
                self.demo_period_sel,
                self.demo_facility_sel,
            ),
            self._external_volume_body,
            pn.pane.Markdown("### Top Count Locations by Modeled Volume"),
            selector_row(self.demo_top_period_sel, self.demo_top_n_sel),
            self._external_top_body,
            pn.pane.Markdown("### Screenline Flow Summaries"),
            self._screenline_body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        demo_link_list = self.state.get_summary_table_set(
            "demo_link_summary", self.weighting_key
        )
        demo_count_list = self.state.get_summary_table_set(
            "demo_count_location_counts", self.weighting_key
        )
        demo_volume_list = self.state.get_summary_table_set(
            "demo_count_location_volumes", self.weighting_key
        )
        demo_scatter_list = self.state.get_summary_table_set(
            "demo_count_location_scatter", self.weighting_key
        )
        demo_fit_list = self.state.get_summary_table_set(
            "demo_count_location_fit", self.weighting_key
        )
        facility_opts, self.demo_facility_raw_by_label = demo_facility_options(
            demo_link_list,
            demo_count_list,
            demo_volume_list,
            demo_scatter_list,
            demo_fit_list,
            config=self.config,
        )
        self.demo_facility_sel.options = facility_opts
        if self.demo_facility_sel.value not in facility_opts:
            self.demo_facility_sel.value = facility_opts[0]

    def selected_facility_type_raw(self) -> str:
        selected = str(self.demo_facility_sel.value)
        raw_value = self.demo_facility_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def render_validation_chart(
        self,
        data_list: list[tuple[str, pl.DataFrame]] | None,
        *,
        cache_key: str,
        title: str,
        detail: str,
        missing_summary_id: str,
    ) -> pn.viewable.Viewable:
        if data_list is None:
            return self.data_not_available_card(
                detail=detail,
                missing_items=[missing_summary_id],
            )
        chart_data = self.get_filtered_view(
            cache_key,
            factory=lambda: validation_chart_data(data_list),
        )
        return scatter_chart(
            chart_data,
            x_col="observed_volume",
            y_col="modeled_volume",
            title=title,
            xaxis_title="Observed Traffic Volume",
            yaxis_title="Modeled Traffic Volume",
        )

    def render_screenline_flow_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]

        return [
            self.render_validation_chart(
                self.state.get_summary_table_set(
                    "screenline_flow_comparisons", self.weighting_key
                ),
                cache_key="screenline_flow_comparisons",
                title="Screenline Flow Comparisons",
                detail="Screenline flow comparisons are unavailable.",
                missing_summary_id="screenline_flow_comparisons",
            )
        ]

    def render_demo_traffic_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return [self.no_runs_message()]

        link_list = self.state.get_summary_table_set(
            "demo_link_summary", self.weighting_key
        )
        count_list = self.state.get_summary_table_set(
            "demo_count_location_counts", self.weighting_key
        )
        volume_list = self.state.get_summary_table_set(
            "demo_count_location_volumes", self.weighting_key
        )
        scatter_list = self.state.get_summary_table_set(
            "demo_count_location_scatter", self.weighting_key
        )
        fit_list = self.state.get_summary_table_set(
            "demo_count_location_fit", self.weighting_key
        )
        if not any((link_list, count_list, volume_list, scatter_list, fit_list)):
            return []
        period = self.demo_period_sel.value
        volume_col = DEMO_TRAFFIC_TIME_PERIODS[str(period)]
        facility_type = self.selected_facility_type_raw()
        facility_label = str(self.demo_facility_sel.value)
        facility_categoryarray = (
            [facility_label]
            if facility_type != "All"
            else [option for option in self.demo_facility_sel.options if option != "All"]
        )
        section: list[pn.viewable.Viewable] = [
            pn.pane.Markdown("### Traffic Volume Summaries")
        ]
        scatter_data_for_table: list[tuple[str, pl.DataFrame]] = []
        if scatter_list is not None:
            scatter_data = self.get_filtered_view(
                "demo_count_scatter",
                (period, facility_type),
                factory=lambda: demo_count_scatter_data(
                    scatter_list,
                    period=str(period),
                    facility_type=facility_type,
                ),
            )
            fit_data = self.get_filtered_view(
                "demo_count_fit",
                (period, facility_type),
                factory=lambda: demo_count_fit_line_data(
                    fit_list,
                    period=str(period),
                    facility_type=facility_type,
                ),
            )
            section.append(
                scatter_chart(
                    scatter_data,
                    x_col="observed_volume",
                    y_col="modeled_volume",
                    title=f"Count Location Observed vs Modeled - {period}",
                    xaxis_title="Observed Count",
                    yaxis_title="Modeled Volume",
                    fit_overlays=fit_data,
                    one_to_one_line=True,
                )
            )
            scatter_data_for_table = scatter_data
        elif count_list is not None and volume_list is not None:
            scatter_data = self.get_filtered_view(
                "demo_count_scatter_fallback",
                (period, facility_type),
                factory=lambda: demo_count_scatter_data_from_sources(
                    count_list,
                    volume_list,
                    volume_col=volume_col,
                    facility_type=facility_type,
                ),
            )
            section.append(
                scatter_chart(
                    scatter_data,
                    x_col="observed_volume",
                    y_col="modeled_volume",
                    title=f"Count Location Observed vs Modeled - {period}",
                    xaxis_title="Observed Count",
                    yaxis_title="Modeled Volume",
                    one_to_one_line=True,
                )
            )
            scatter_data_for_table = scatter_data
        else:
            section.append(
                self.data_not_available_card(
                    detail="Demo count-location counts and volumes are both required for this scatter plot.",
                    missing_items=[
                        "demo_count_location_counts",
                        "demo_count_location_volumes",
                    ],
                )
            )
        if scatter_data_for_table:
            facility_comparison = self.get_filtered_view(
                "demo_count_facility_comparison",
                (period, facility_type),
                factory=lambda: demo_facility_comparison_table(
                    scatter_data_for_table,
                    fit_list,
                    period=str(period),
                    facility_type=facility_type,
                    config=self.config,
                ),
            )
            if facility_comparison:
                section.append(
                    data_table(
                        facility_comparison,
                        title="Count Location Summary by Facility Type",
                        numeric_precision_by_column={"RMSE": 3, "R^2": 3},
                        column_sorters={"RMSE": "number", "R^2": "number"},
                    )
                )
        if link_list is not None:
            aggregate_data = self.get_filtered_view(
                "demo_link_aggregate",
                (period, facility_type),
                factory=lambda: demo_link_aggregate_data(
                    link_list,
                    volume_col=volume_col,
                    facility_type=facility_type,
                    config=self.config,
                ),
            )
            section.append(
                bar_chart(
                    aggregate_data,
                    x_col="facility_type_label",
                    y_col="volume",
                    title=f"Link Volume by Facility Type - {period}",
                    xaxis_title="Facility Type",
                    yaxis_title="Volume",
                    xaxis_categoryarray=facility_categoryarray,
                )
            )
        else:
            section.append(
                self.data_not_available_card(
                    detail="Demo link summaries are unavailable.",
                    missing_items=["demo_link_summary"],
                )
            )
        return section

    def render_demo_top_count_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return [self.no_runs_message()]

        link_list = self.state.get_summary_table_set(
            "demo_link_summary", self.weighting_key
        )
        count_list = self.state.get_summary_table_set(
            "demo_count_location_counts", self.weighting_key
        )
        volume_list = self.state.get_summary_table_set(
            "demo_count_location_volumes", self.weighting_key
        )
        if not any((link_list, count_list, volume_list)):
            return []

        facility_type = self.selected_facility_type_raw()
        top_period = self.demo_top_period_sel.value
        top_volume_col = DEMO_TRAFFIC_TIME_PERIODS[str(top_period)]
        top_n = int(self.demo_top_n_sel.value)

        if count_list is not None and volume_list is not None:
            volume_comparison = self.get_filtered_view(
                "demo_volume_comparison",
                (top_period, facility_type, top_n),
                factory=lambda: label_category_data(
                    demo_volume_comparison_table(
                        count_list,
                        volume_list,
                        link_list=link_list,
                        volume_col=top_volume_col,
                        facility_type=facility_type,
                        top_n=top_n,
                    ),
                    source_col="facility_type",
                    category_id=FACILITY_TYPE_CATEGORY_ID,
                    config=self.config,
                    target_col="facility_type",
                ),
            )
            return [
                pn.pane.Markdown(
                    "#### Observed vs Modeled Volumes - "
                    f"{top_period} (Top {top_n} by Modeled Volume)"
                ),
                data_table(
                    volume_comparison,
                    column_sorters={"Difference": "number"},
                ),
            ]
        if link_list is not None:
            return [
                self.data_not_available_card(
                    detail="Demo count-location counts and volumes are both required for this comparison table.",
                    missing_items=[
                        "demo_count_location_counts",
                        "demo_count_location_volumes",
                    ],
                )
            ]
        return []


PAGE = DashboardPageDefinition(
    page_id="traffic",
    title="Traffic Validation",
    group_id="validation",
    order=52,
    page_cls=TrafficValidationPage,
    required_summary_ids=(
        "screenline_flow_comparisons",
    ),
    optional_summary_ids=(
        "demo_link_summary",
        "demo_count_location_counts",
        "demo_count_location_volumes",
        "demo_count_location_scatter",
        "demo_count_location_fit",
    ),
)

TrafficValidationPage.definition = PAGE
