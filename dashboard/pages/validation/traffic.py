"""Traffic validation page with count and screenline comparison charts."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import scatter_chart
from dashboard.helpers.category_helpers import common_column_options, nonempty
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def validation_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
    count_period: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter one validation summary list and aggregate to one observed/modeled point per id."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df
        if "direction" in filtered.columns and direction != "All":
            filtered = filtered.with_columns(pl.col("direction").cast(pl.Utf8)).filter(
                pl.col("direction") == direction
            )
        if "count_period" in filtered.columns and count_period != "All":
            filtered = filtered.with_columns(
                pl.col("count_period").cast(pl.Utf8)
            ).filter(pl.col("count_period") == count_period)

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


class TrafficValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        direction_opts, _ = common_column_options(
            self.state.get_summary_table_set("traffic_count_comparisons", "weighted"),
            self.state.get_summary_table_set("screenline_flow_comparisons", "weighted"),
            column="direction",
            total_raw="All",
            total_label="All",
        )
        period_opts, _ = common_column_options(
            self.state.get_summary_table_set("traffic_count_comparisons", "weighted"),
            self.state.get_summary_table_set("screenline_flow_comparisons", "weighted"),
            column="count_period",
            total_raw="All",
            total_label="All",
        )
        self.direction_sel = self.selector(
            "direction",
            widget=pn.widgets.Select(
                name="Direction",
                options=direction_opts or ["All"],
                value=(direction_opts or ["All"])[0],
            ),
            label="Direction",
        )
        self.count_period_sel = self.selector(
            "count_period",
            widget=pn.widgets.Select(
                name="Count Period",
                options=period_opts or ["All"],
                value=(period_opts or ["All"])[0],
            ),
            label="Count Period",
        )
        self._body = self.section(
            "traffic_body",
            selectors=("direction", "count_period"),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Traffic Validation"),
            pn.Row(
                pn.pane.Markdown("**Direction:**"),
                self.direction_sel,
                pn.pane.Markdown("**Count Period:**"),
                self.count_period_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        traffic_list = self.state.get_summary_table_set(
            "traffic_count_comparisons",
            self.weighting_key,
        )
        screenline_list = self.state.get_summary_table_set(
            "screenline_flow_comparisons",
            self.weighting_key,
        )
        direction_opts, _ = common_column_options(
            traffic_list,
            screenline_list,
            column="direction",
            total_raw="All",
            total_label="All",
        )
        period_opts, _ = common_column_options(
            traffic_list,
            screenline_list,
            column="count_period",
            total_raw="All",
            total_label="All",
        )
        self.direction_sel.options = direction_opts or ["All"]
        if self.direction_sel.value not in self.direction_sel.options:
            self.direction_sel.value = self.direction_sel.options[0]
        self.count_period_sel.options = period_opts or ["All"]
        if self.count_period_sel.value not in self.count_period_sel.options:
            self.count_period_sel.value = self.count_period_sel.options[0]

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
        direction = self.direction_sel.value
        count_period = self.count_period_sel.value
        chart_data = self.get_filtered_view(
            cache_key,
            (direction, count_period),
            factory=lambda: validation_chart_data(data_list, direction, count_period),
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

        return [
            pn.Row(
                self.render_validation_chart(
                    self.state.get_summary_table_set(
                        "traffic_count_comparisons", self.weighting_key
                    ),
                    cache_key="traffic_count_comparisons",
                    title="Traffic Count Comparisons",
                    detail="Traffic count comparisons are unavailable.",
                    missing_summary_id="traffic_count_comparisons",
                ),
                self.render_validation_chart(
                    self.state.get_summary_table_set(
                        "screenline_flow_comparisons", self.weighting_key
                    ),
                    cache_key="screenline_flow_comparisons",
                    title="Screenline Flow Comparisons",
                    detail="Screenline flow comparisons are unavailable.",
                    missing_summary_id="screenline_flow_comparisons",
                ),
                sizing_mode="stretch_width",
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="traffic",
    title="Traffic Validation",
    group_id="validation",
    order=52,
    page_cls=TrafficValidationPage,
    required_summary_ids=(
        "traffic_count_comparisons",
        "screenline_flow_comparisons",
    ),
)

TrafficValidationPage.definition = PAGE
