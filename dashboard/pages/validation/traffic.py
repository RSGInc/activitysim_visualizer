"""Traffic validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import scatter_chart
from dashboard.page_base import MultiSelectorComparisonPage, SectionSpec, SelectorSpec
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


class TrafficValidationPage(MultiSelectorComparisonPage):
    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="direction",
                label="Direction",
                attr_name="direction_sel",
                options_factory=lambda page: page._direction_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Direction",
                    options=options,
                    value=value,
                ),
            ),
            SelectorSpec(
                selector_id="count_period",
                label="Count Period",
                attr_name="count_period_sel",
                options_factory=lambda page: page._period_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Count Period",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _direction_options(self) -> list[object]:
        traffic_list = self.get_refresh_summary(
            "traffic_count_comparisons",
            optional=True,
        )
        screenline_list = self.get_refresh_summary(
            "screenline_flow_comparisons",
            optional=True,
        )
        return column_options(traffic_list or screenline_list or [], "direction")

    def _period_options(self) -> list[object]:
        traffic_list = self.get_refresh_summary(
            "traffic_count_comparisons",
            optional=True,
        )
        screenline_list = self.get_refresh_summary(
            "screenline_flow_comparisons",
            optional=True,
        )
        return column_options(traffic_list or screenline_list or [], "count_period")

    def build_page(self) -> pn.viewable.Viewable:
        self.register_selectors(*self.selector_specs())
        self.register_sections(
            SectionSpec(
                section_id="traffic_body",
                selector_ids=("direction", "count_period"),
                render=lambda page: page.render_body(),
                attr_name="_body",
            )
        )
        return self.new_section(
            pn.pane.Markdown("## Traffic Validation"),
            self.selector_row("direction", "count_period"),
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        def _ready(_summaries):
            traffic_list = self.get_refresh_summary(
                "traffic_count_comparisons",
                optional=True,
            )
            screenline_list = self.get_refresh_summary(
                "screenline_flow_comparisons",
                optional=True,
            )
            direction = self.direction_sel.value
            count_period = self.count_period_sel.value

            if traffic_list is not None:
                traffic_data = self.filtered_view(
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
                screenline_data = self.filtered_view(
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
                self.two_up(
                    traffic_chart,
                    screenline_chart,
                ),
            ]

        return self.render_summary_page(
            _ready,
            required_summary_ids=(),
            detail="Traffic validation summaries are unavailable.",
        )


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
