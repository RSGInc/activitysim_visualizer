"""Tour time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import nonempty_runs
from dashboard.pages._shared.purposes import raw_tour_purpose, tour_purpose_options
from dashboard.pages._shared.time_distance import (
    duration_hours,
    max_timebin,
    time_label,
)


def tour_time_chart_data(data_list: list[tuple[str, pl.DataFrame]], purpose: str):
    maxbin = max_timebin(data_list)
    dep_data = []
    arr_data = []
    dur_data = []
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8)).filter(
            pl.col("tour_purpose") == purpose
        )
        dep_data.append(
            (
                label,
                df.select(pl.col("time_bin"), pl.col("departure_tour_count"))
                .sort("time_bin")
                .with_columns(
                    pl.col("time_bin")
                    .map_elements(
                        lambda tb: time_label(int(tb), maxbin), return_dtype=pl.Utf8
                    )
                    .alias("clock_time")
                ),
            )
        )
        arr_data.append(
            (
                label,
                df.select(pl.col("time_bin"), pl.col("arrival_tour_count"))
                .sort("time_bin")
                .with_columns(
                    pl.col("time_bin")
                    .map_elements(
                        lambda tb: time_label(int(tb), maxbin), return_dtype=pl.Utf8
                    )
                    .alias("clock_time")
                ),
            )
        )
        dur_data.append(
            (
                label,
                df.select(pl.col("time_bin"), pl.col("duration_tour_count"))
                .sort("time_bin")
                .with_columns(
                    pl.col("time_bin")
                    .map_elements(
                        lambda tb: duration_hours(int(tb), maxbin),
                        return_dtype=pl.Float64,
                    )
                    .alias("duration_hours")
                ),
            )
        )
    return dep_data, arr_data, dur_data


class TourTimePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        purpose_opts = self._purpose_options()
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose", options=purpose_opts, value=purpose_opts[0]
            ),
            label="Tour Purpose",
        )
        self._body = self.section(
            "tour_time_body", selectors=("tour_purpose",), render=self.render_body
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Time"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purpose_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "tour_time_of_day_by_tour_purpose", "weighted"
        )
        return tour_purpose_options(data) if data is not None else ["Total"]

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        purpose_opts = tour_purpose_options(
            summaries["tour_time_of_day_by_tour_purpose"]
        )
        self.purpose_sel.options = purpose_opts
        if self.purpose_sel.value not in purpose_opts:
            self.purpose_sel.value = purpose_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
        tod_list = summaries["tour_time_of_day_by_tour_purpose"]
        purpose = self.purpose_sel.value
        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_time",
            raw_tour_purpose(purpose),
            factory=lambda: tour_time_chart_data(tod_list, raw_tour_purpose(purpose)),
        )
        return [
            density_chart(
                dep_data,
                "clock_time",
                "departure_tour_count",
                f"Tour Departure Time Distribution - {purpose}",
                "Clock Time (start at 03:00)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
            density_chart(
                arr_data,
                "clock_time",
                "arrival_tour_count",
                f"Tour Arrival Time Distribution - {purpose}",
                "Clock Time (start at 03:00)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
            density_chart(
                dur_data,
                "duration_hours",
                "duration_tour_count",
                f"Tour Duration Distribution - {purpose}",
                "Tour Duration (hours)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_time",
    title="Tour Time",
    group_id="tour_summaries",
    order=43,
    page_cls=TourTimePage,
    required_summary_ids=("tour_time_of_day_by_tour_purpose",),
)

TourTimePage.definition = PAGE
