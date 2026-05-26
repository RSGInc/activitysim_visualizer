"""Tour purpose page."""

from __future__ import annotations

import panel as pn
import polars as pl
from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import (
    label_category_data,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


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

        category_data = _nonempty(summaries["tour_category_distribution"])
        purpose_data = _nonempty(summaries["tour_purpose_distribution"])
        purpose_x_values = ordered_category_values(
            purpose_data,
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
        )
        purpose_label_values = self.config.ordered_labels(
            "tour_purpose",
            purpose_x_values,
        )
        labeled_purpose_data = label_category_data(
            purpose_data,
            source_col="tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            target_col="tour_purpose_label",
        )

        category_x_values = ordered_category_values(
            category_data,
            "tour_category",
            category_id="tour_category",
            config=self.config,
        )
        category_label_values = self.config.ordered_labels(
            "tour_category",
            category_x_values,
        )
        labeled_category_data = label_category_data(
            category_data,
            source_col="tour_category",
            category_id="tour_category",
            config=self.config,
            target_col="tour_category_label",
        )

        category_chart = bar_chart(
            labeled_category_data,
            x_col="tour_category_label",
            y_col="tour_count",
            title="Tour Category",
            xaxis_title="Tour Category",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=category_label_values,
        )

        purpose_chart = bar_chart(
            labeled_purpose_data,
            x_col="tour_purpose_label",
            y_col="tour_count",
            title="Tour Purpose",
            xaxis_title="Tour Purpose",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=purpose_label_values,
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
