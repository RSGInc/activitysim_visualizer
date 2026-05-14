"""Traffic validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import scatter_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_options, nonempty_runs


def validation_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
    count_period: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in nonempty_runs(data_list):
        if "direction" in df.columns:
            df = df.with_columns(pl.col("direction").cast(pl.Utf8))
            if direction != "All":
                df = df.filter(pl.col("direction") == direction)

        if "count_period" in df.columns:
            df = df.with_columns(pl.col("count_period").cast(pl.Utf8))
            if count_period != "All":
                df = df.filter(pl.col("count_period") == count_period)

        id_col = None
        if "count_location_id" in df.columns:
            id_col = "count_location_id"
        elif "screenline_id" in df.columns:
            id_col = "screenline_id"
        if id_col is not None:
            df = (
                df.group_by(id_col)
                .agg(
                    observed_volume=pl.col("observed_volume").sum(),
                    modeled_volume=pl.col("modeled_volume").sum(),
                )
                .sort(id_col)
            )

        out.append((label, df))

    return out


class TrafficValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        traffic_data = self.state.get_summary_table_set(
            "traffic_count_comparisons",
            "weighted",
        )
        direction_opts = column_options(traffic_data or [], "direction")
        period_opts = column_options(traffic_data or [], "count_period")
        self.direction_sel = self.selector(
            "direction",
            widget=pn.widgets.Select(
                name="Direction",
                options=direction_opts,
                value=direction_opts[0],
            ),
            label="Direction",
        )
        self.count_period_sel = self.selector(
            "count_period",
            widget=pn.widgets.Select(
                name="Count Period",
                options=period_opts,
                value=period_opts[0],
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
        direction_opts = column_options(
            traffic_list or screenline_list or [], "direction"
        )
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = direction_opts[0]
        period_opts = column_options(
            traffic_list or screenline_list or [], "count_period"
        )
        self.count_period_sel.options = period_opts
        if self.count_period_sel.value not in period_opts:
            self.count_period_sel.value = period_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        traffic_list = self.state.get_summary_table_set(
            "traffic_count_comparisons",
            self.weighting_key,
        )
        screenline_list = self.state.get_summary_table_set(
            "screenline_flow_comparisons",
            self.weighting_key,
        )
        direction = self.direction_sel.value
        count_period = self.count_period_sel.value

        if traffic_list is not None:
            traffic_data = self.get_filtered_view(
                "traffic_count_comparisons",
                (direction, count_period),
                factory=lambda: validation_chart_data(
                    traffic_list,
                    direction,
                    count_period,
                ),
            )
            traffic_chart: pn.viewable.Viewable = scatter_chart(
                traffic_data,
                x_col="observed_volume",
                y_col="modeled_volume",
                title="Traffic Count Comparisons",
                xaxis_title="Observed Traffic Volume",
                yaxis_title="Modeled Traffic Volume",
            )
        else:
            traffic_chart = self.data_not_available_card(
                detail="Traffic count comparisons are unavailable.",
                missing_items=["traffic_count_comparisons"],
            )

        if screenline_list is not None:
            screenline_data = self.get_filtered_view(
                "screenline_flow_comparisons",
                (direction, count_period),
                factory=lambda: validation_chart_data(
                    screenline_list,
                    direction,
                    count_period,
                ),
            )
            screenline_chart: pn.viewable.Viewable = scatter_chart(
                screenline_data,
                x_col="observed_volume",
                y_col="modeled_volume",
                title="Screenline Flow Comparisons",
                xaxis_title="Observed Traffic Volume",
                yaxis_title="Modeled Traffic Volume",
            )
        else:
            screenline_chart = self.data_not_available_card(
                detail="Screenline flow comparisons are unavailable.",
                missing_items=["screenline_flow_comparisons"],
            )

        return [
            pn.Row(
                traffic_chart,
                screenline_chart,
                sizing_mode="stretch_width",
            ),
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
