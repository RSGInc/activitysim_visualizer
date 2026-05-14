"""Tour purpose page."""

from __future__ import annotations

import panel as pn

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import (
    category_axis_order,
    nonempty_runs,
    relabel_runs_by_column,
)
from runtime.config import Config


class TourPurposePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Purpose", state, config)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Purpose"),
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

        category_data = nonempty_runs(summaries["tour_category_distribution"])
        purpose_data = nonempty_runs(summaries["tour_purpose_distribution"])
        purpose_display_data = relabel_runs_by_column(
            purpose_data,
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
        )

        category_chart = bar_chart(
            category_data,
            x_col="tour_category",
            y_col="tour_count",
            title="Tour Category",
            xaxis_title="Tour Category",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        purpose_chart = bar_chart(
            purpose_display_data,
            x_col="tour_purpose",
            y_col="tour_count",
            title="Tour Purpose",
            xaxis_title="Tour Purpose",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=category_axis_order(
                purpose_data,
                column="tour_purpose",
                category_id="tour_purpose",
                config=self.config,
            ),
        )

        self._body.objects = [
            pn.Row(category_chart, purpose_chart, sizing_mode="stretch_width"),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_purpose",
    title="Tour Purpose",
    group_id="tour_summaries",
    order=41,
    page_cls=TourPurposePage,
    required_summary_ids=(
        "tour_category_distribution",
        "tour_purpose_distribution",
    ),
)

TourPurposePage.definition = PAGE
