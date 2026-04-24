"""Traffic validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, scatter_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    total_label: str = "All",
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    return [total_label] + sorted(v for v in vals if v != total_label)


def validation_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
    count_period: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in _nonempty(data_list):
        if "direction" in df.columns:
            df = df.with_columns(pl.col("direction").cast(pl.Utf8))
            if direction != "All":
                df = df.filter(pl.col("direction") == direction)

        if "count_period" in df.columns:
            df = df.with_columns(pl.col("count_period").cast(pl.Utf8))
            if count_period != "All":
                df = df.filter(pl.col("count_period") == count_period)

        out.append((label, df))

    return out


class TrafficValidationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Traffic Validation", state, config)

        traffic_data = self.state.get_summary_table_set(
            "traffic_count_comparisons",
            "weighted",
        )

        direction_opts = _options(traffic_data or [], "direction")
        period_opts = _options(traffic_data or [], "count_period")

        self.direction_sel = pn.widgets.Select(
            name="Direction",
            options=direction_opts,
            value=direction_opts[0],
        )
        self._watch_widget(self.direction_sel)

        self.count_period_sel = pn.widgets.Select(
            name="Count Period",
            options=period_opts,
            value=period_opts[0],
        )
        self._watch_widget(self.count_period_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
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

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        traffic_list = summaries["traffic_count_comparisons"]
        screenline_list = summaries["screenline_flow_comparisons"]

        direction_opts = _options(traffic_list, "direction")
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = direction_opts[0]

        period_opts = _options(traffic_list, "count_period")
        self.count_period_sel.options = period_opts
        if self.count_period_sel.value not in period_opts:
            self.count_period_sel.value = period_opts[0]

        direction = self.direction_sel.value
        count_period = self.count_period_sel.value

        traffic_data = self.get_filtered_view(
            "traffic_count_comparisons",
            (direction, count_period),
            factory=lambda: validation_chart_data(
                traffic_list,
                direction,
                count_period,
            ),
        )

        screenline_data = self.get_filtered_view(
            "screenline_flow_comparisons",
            (direction, count_period),
            factory=lambda: validation_chart_data(
                screenline_list,
                direction,
                count_period,
            ),
        )

        traffic_chart = scatter_chart(
            traffic_data,
            x_col="observed_volume",
            y_col="modeled_volume",
            title="Traffic Count Comparisons",
            xaxis_title="Observed Traffic Volume",
            yaxis_title="Modeled Traffic Volume",
        )

        screenline_chart = scatter_chart(
            screenline_data,
            x_col="observed_volume",
            y_col="modeled_volume",
            title="Screenline Flow Comparisons",
            xaxis_title="Observed Traffic Volume",
            yaxis_title="Modeled Traffic Volume",
        )

        self._body.objects = [
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
    child_id="traffic",
    order=52,
    controller_cls=TrafficValidationPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="direction",
            widget_attr="direction_sel",
            label="Direction",
        ),
        PageSelectorDefinition(
            selector_id="count_period",
            widget_attr="count_period_sel",
            label="Count Period",
        ),
    ),
    required_summary_ids=(
        "traffic_count_comparisons",
        "screenline_flow_comparisons",
    ),
)

TrafficValidationPage.definition = PAGE
