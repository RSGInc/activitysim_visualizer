"""Traffic validation page with count and screenline comparison charts."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, scatter_chart, selector_row
from dashboard.helpers.category_helpers import (
    label_category_data,
    label_category_frame,
    nonempty,
    raw_display_options,
)
from dashboard.helpers.comparison_helpers import (
    build_ab_comparison_row,
    build_ab_comparison_table,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config

EXTERNAL_TIME_PERIODS = {
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


def external_facility_options(
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


def external_count_scatter_data(
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


def external_count_scatter_data_from_sources(
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


def external_count_fit_line_data(
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


def external_link_aggregate_data(
    link_list: list[tuple[str, pl.DataFrame]],
    *,
    volume_col: str,
    facility_type: str,
    config: Config,
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
        chart_df = label_category_frame(
            chart_df,
            source_col="FACTYPE",
            category_id=FACILITY_TYPE_CATEGORY_ID,
            config=config,
            target_col="facility_type_label",
        )
        out.append((label, chart_df))
    return out


def external_volume_comparison_table(
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
        rows = []
        for row in joined.iter_rows(named=True):
            keys = {
                "id": row["id"],
                "facility_type": row["facility_type"],
            }
            if has_link_metadata:
                keys["From_Node"] = row.get("From_Node")
                keys["To_Node"] = row.get("To_Node")
            rows.append(
                build_ab_comparison_row(
                    keys=keys,
                    quantity_a=row["_quantity_a"],
                    quantity_b=row["_quantity_b"],
                    quantity_a_column=quantity_a_column,
                    quantity_b_column=quantity_b_column,
                )
            )
        key_columns = ["id", "facility_type"]
        if has_link_metadata:
            key_columns.extend(["From_Node", "To_Node"])
        table = build_ab_comparison_table(
            rows,
            key_columns=key_columns,
            quantity_a_column=quantity_a_column,
            quantity_b_column=quantity_b_column,
        )
        if not table.is_empty():
            out.append((label, table))
    return out


class TrafficValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        external_link_list = self.state.get_summary_table_set(
            "external_link_summary", "weighted"
        )
        external_count_list = self.state.get_summary_table_set(
            "external_count_location_counts", "weighted"
        )
        external_volume_list = self.state.get_summary_table_set(
            "external_count_location_volumes", "weighted"
        )
        external_scatter_list = self.state.get_summary_table_set(
            "external_count_location_scatter", "weighted"
        )
        external_fit_list = self.state.get_summary_table_set(
            "external_count_location_fit", "weighted"
        )
        facility_opts, self.external_facility_raw_by_label = external_facility_options(
            external_link_list,
            external_count_list,
            external_volume_list,
            external_scatter_list,
            external_fit_list,
            config=self.config,
        )
        self.external_period_sel = self.selector(
            "external_period",
            widget=pn.widgets.Select(
                name="Period",
                options=list(EXTERNAL_TIME_PERIODS),
                value="Day",
            ),
            label="Period",
        )
        self.external_facility_sel = self.selector(
            "external_facility_type",
            widget=pn.widgets.Select(
                name="Facility Type",
                options=facility_opts,
                value=facility_opts[0],
            ),
            label="Facility Type",
        )
        self.external_top_period_sel = self.selector(
            "external_top_period",
            widget=pn.widgets.Select(
                name="Period",
                options=list(EXTERNAL_TIME_PERIODS),
                value="Day",
            ),
            label="Period",
        )
        self.external_top_n_sel = self.selector(
            "external_top_n",
            widget=pn.widgets.Select(
                name="Top Count Locations",
                options=[10, 25, 50, 100],
                value=25,
            ),
            label="Top Count Locations",
        )
        self._body = self.section(
            "traffic_body",
            selectors=(
                "external_period",
                "external_facility_type",
                "external_top_period",
                "external_top_n",
            ),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Traffic Validation"),
            selector_row(
                self.external_period_sel,
                self.external_facility_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        external_link_list = self.state.get_summary_table_set(
            "external_link_summary", self.weighting_key
        )
        external_count_list = self.state.get_summary_table_set(
            "external_count_location_counts", self.weighting_key
        )
        external_volume_list = self.state.get_summary_table_set(
            "external_count_location_volumes", self.weighting_key
        )
        external_scatter_list = self.state.get_summary_table_set(
            "external_count_location_scatter", self.weighting_key
        )
        external_fit_list = self.state.get_summary_table_set(
            "external_count_location_fit", self.weighting_key
        )
        facility_opts, self.external_facility_raw_by_label = external_facility_options(
            external_link_list,
            external_count_list,
            external_volume_list,
            external_scatter_list,
            external_fit_list,
            config=self.config,
        )
        self.external_facility_sel.options = facility_opts
        if self.external_facility_sel.value not in facility_opts:
            self.external_facility_sel.value = facility_opts[0]

    def selected_facility_type_raw(self) -> str:
        selected = str(self.external_facility_sel.value)
        raw_value = self.external_facility_raw_by_label.get(selected, selected)
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

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]

        content = self.render_external_traffic_section()
        content.append(pn.pane.Markdown("### Screenline Flow Summaries"))
        content.append(
            self.render_validation_chart(
                self.state.get_summary_table_set(
                    "screenline_flow_comparisons", self.weighting_key
                ),
                cache_key="screenline_flow_comparisons",
                title="Screenline Flow Comparisons",
                detail="Screenline flow comparisons are unavailable.",
                missing_summary_id="screenline_flow_comparisons",
            )
        )
        return content

    def render_external_traffic_section(self) -> list[pn.viewable.Viewable]:
        link_list = self.state.get_summary_table_set(
            "external_link_summary", self.weighting_key
        )
        count_list = self.state.get_summary_table_set(
            "external_count_location_counts", self.weighting_key
        )
        volume_list = self.state.get_summary_table_set(
            "external_count_location_volumes", self.weighting_key
        )
        scatter_list = self.state.get_summary_table_set(
            "external_count_location_scatter", self.weighting_key
        )
        fit_list = self.state.get_summary_table_set(
            "external_count_location_fit", self.weighting_key
        )
        if not any((link_list, count_list, volume_list, scatter_list, fit_list)):
            return []
        period = self.external_period_sel.value
        volume_col = EXTERNAL_TIME_PERIODS[str(period)]
        facility_type = self.selected_facility_type_raw()
        facility_label = str(self.external_facility_sel.value)
        top_period = self.external_top_period_sel.value
        top_volume_col = EXTERNAL_TIME_PERIODS[str(top_period)]
        top_n = int(self.external_top_n_sel.value)
        facility_categoryarray = (
            [facility_label]
            if facility_type != "All"
            else [option for option in self.external_facility_sel.options if option != "All"]
        )
        section: list[pn.viewable.Viewable] = [
            pn.pane.Markdown("### Traffic Volume Summaries")
        ]
        if scatter_list is not None:
            scatter_data = self.get_filtered_view(
                "external_count_scatter",
                (period, facility_type),
                factory=lambda: external_count_scatter_data(
                    scatter_list,
                    period=str(period),
                    facility_type=facility_type,
                ),
            )
            fit_data = self.get_filtered_view(
                "external_count_fit",
                (period, facility_type),
                factory=lambda: external_count_fit_line_data(
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
                )
            )
        elif count_list is not None and volume_list is not None:
            scatter_data = self.get_filtered_view(
                "external_count_scatter_fallback",
                (period, facility_type),
                factory=lambda: external_count_scatter_data_from_sources(
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
                )
            )
        else:
            section.append(
                self.data_not_available_card(
                    detail="External count-location counts and volumes are both required for this scatter plot.",
                    missing_items=[
                        "external_count_location_counts",
                        "external_count_location_volumes",
                    ],
                )
            )
        if link_list is not None:
            aggregate_data = self.get_filtered_view(
                "external_link_aggregate",
                (period, facility_type),
                factory=lambda: external_link_aggregate_data(
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
                    detail="External link summaries are unavailable.",
                    missing_items=["external_link_summary"],
                )
            )
        if count_list is not None and volume_list is not None:
            volume_comparison = self.get_filtered_view(
                "external_volume_comparison",
                (top_period, facility_type, top_n),
                factory=lambda: label_category_data(
                    external_volume_comparison_table(
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
            section.append(
                pn.Column(
                    pn.pane.Markdown(
                        f"### Top Count Location Observed vs Modeled Volumes - {top_period}"
                    ),
                    selector_row(self.external_top_period_sel, self.external_top_n_sel),
                    data_table(
                        volume_comparison,
                        column_sorters={"RMSE": "number"},
                    ),
                    sizing_mode="stretch_width",
                ),
            )
        elif link_list is not None:
            section.append(
                self.data_not_available_card(
                    detail="External count-location counts and volumes are both required for this comparison table.",
                    missing_items=[
                        "external_count_location_counts",
                        "external_count_location_volumes",
                    ],
                )
            )
        return section


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
        "external_link_summary",
        "external_count_location_counts",
        "external_count_location_volumes",
        "external_count_location_scatter",
        "external_count_location_fit",
    ),
)

TrafficValidationPage.definition = PAGE
