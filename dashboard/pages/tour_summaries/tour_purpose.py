"""Tour summary page showing overall tour category and purpose distributions."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.helpers.category_helpers import (
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard import DashboardPage, dashboard_page


def render_distribution_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    source_col: str,
    category_id: str,
    title: str,
    xaxis_title: str,
    config,
    plot,
) -> pn.viewable.Viewable:
    """Build one labeled distribution chart from a summary table list."""
    values = ordered_category_values(
        data_list,
        source_col,
        category_id=category_id,
        config=config,
    )
    labeled_data = label_category_data(
        data_list,
        source_col=source_col,
        category_id=category_id,
        config=config,
        target_col=f"{source_col}_label",
    )
    return plot.bar(
        labeled_data,
        x=f"{source_col}_label",
        y="tour_count",
        title=title,
        x_title=xaxis_title,
        y_title="Tours",
        category_order=config.ordered_labels(category_id, values),
    )


@dashboard_page(
    page_id="tour_purpose",
    title="Tour Purpose",
    group_id="tour_summaries",
    order=41,
    required_summary_ids=(
        "tour_category_distribution",
        "tour_purpose_distribution",
    ),
)
class TourPurposePage(DashboardPage):
    """Simple reference page for summary-only chart sections with no selectors."""

    def build_page(self) -> pn.viewable.Viewable:
        self._body = self.section("tour_purpose_body", render=self.render_body)
        return self.new_section(
            pn.pane.Markdown("## Tour Purpose"),
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self.data.summaries(*self.required_summary_ids)
        if not all(summaries.values()):
            return [self.summary_only_unavailable_card()]

        category_data = nonempty(summaries["tour_category_distribution"])
        purpose_data = nonempty(summaries["tour_purpose_distribution"])
        return [
            pn.Row(
                render_distribution_chart(
                    category_data,
                    source_col="tour_category",
                    category_id="tour_category",
                    title="Tour Category",
                    xaxis_title="Tour Category",
                    config=self.config,
                    plot=self.plot,
                ),
                render_distribution_chart(
                    purpose_data,
                    source_col="tour_purpose",
                    category_id="tour_purpose",
                    title="Tour Purpose",
                    xaxis_title="Tour Purpose",
                    config=self.config,
                    plot=self.plot,
                ),
                sizing_mode="stretch_width",
            )
        ]
