"""Tour time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.helpers.category_helpers import column_options, nonempty
from dashboard.helpers.time_distance_helpers import (
    max_timebin,
    timebin_duration_hours,
    timebin_label,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def tour_time_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build departure, arrival, and duration distributions for one tour purpose."""
    observed_max_timebin = max_timebin(data_list)
    dep_data = []
    arr_data = []
    dur_data = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8)).filter(
            pl.col("tour_purpose") == purpose
        )
        dep_data.append(
            (
                label,
                filtered.select("time_bin", "departure_tour_count")
                .sort("time_bin")
                .with_columns(
                    pl.col("time_bin")
                    .map_elements(
                        lambda value: timebin_label(int(value), observed_max_timebin),
                        return_dtype=pl.Utf8,
                    )
                    .alias("clock_time")
                ),
            )
        )
        arr_data.append(
            (
                label,
                filtered.select("time_bin", "arrival_tour_count")
                .sort("time_bin")
                .with_columns(
                    pl.col("time_bin")
                    .map_elements(
                        lambda value: timebin_label(int(value), observed_max_timebin),
                        return_dtype=pl.Utf8,
                    )
                    .alias("clock_time")
                ),
            )
        )
        dur_data.append(
            (
                label,
                filtered.select("time_bin", "duration_tour_count")
                .sort("time_bin")
                .with_columns(
                    pl.col("time_bin")
                    .map_elements(
                        lambda value: timebin_duration_hours(
                            int(value), observed_max_timebin
                        ),
                        return_dtype=pl.Float64,
                    )
                    .alias("duration_hours")
                ),
            )
        )
    return dep_data, arr_data, dur_data


class TourTimePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=self._purpose_options(),
                value=self._purpose_options()[0],
            ),
            label="Tour Purpose",
        )
        self._body = self.section(
            "tour_time_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Time"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purpose_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "tour_time_of_day_by_tour_purpose",
            "weighted",
        )
        if data is None:
            self._purpose_to_raw = {"Total": "all_tour_purposes"}
            return ["Total"]
        options, self._purpose_to_raw = column_options(
            data,
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_time",
                "tour_time_of_day_by_tour_purpose",
                "tour_purpose",
                "weighted",
            ),
            total_raw="all_tour_purposes",
            total_label="Total",
        )
        return options or ["Total"]

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        purpose_opts, self._purpose_to_raw = column_options(
            summaries["tour_time_of_day_by_tour_purpose"],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_time",
                "tour_time_of_day_by_tour_purpose",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw="all_tour_purposes",
            total_label="Total",
        )
        self.purpose_sel.options = purpose_opts or ["Total"]
        if self.purpose_sel.value not in self.purpose_sel.options:
            self.purpose_sel.value = self.purpose_sel.options[0]

    def _selected_purpose(self) -> tuple[str, str]:
        display_purpose = self.purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(display_purpose, "all_tour_purposes")
        return display_purpose, str(raw_purpose)

    def _time_charts(
        self,
        tod_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_purpose: str,
        display_purpose: str,
    ) -> tuple[pn.viewable.Viewable, pn.viewable.Viewable, pn.viewable.Viewable]:
        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_time",
            raw_purpose,
            factory=lambda: tour_time_chart_data(tod_list, raw_purpose),
        )
        return (
            density_chart(
                dep_data,
                "clock_time",
                "departure_tour_count",
                f"Tour Departure Time Distribution - {display_purpose}",
                "Clock Time (start at 03:00)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
            density_chart(
                arr_data,
                "clock_time",
                "arrival_tour_count",
                f"Tour Arrival Time Distribution - {display_purpose}",
                "Clock Time (start at 03:00)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
            density_chart(
                dur_data,
                "duration_hours",
                "duration_tour_count",
                f"Tour Duration Distribution - {display_purpose}",
                "Tour Duration (hours)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [self.summary_only_unavailable_card()]
        display_purpose, raw_purpose = self._selected_purpose()
        departure_chart, arrival_chart, duration_chart = self._time_charts(
            summaries["tour_time_of_day_by_tour_purpose"],
            raw_purpose=raw_purpose,
            display_purpose=display_purpose,
        )
        return [departure_chart, arrival_chart, duration_chart]


PAGE = DashboardPageDefinition(
    page_id="tour_time",
    title="Tour Time",
    group_id="tour_summaries",
    order=43,
    page_cls=TourTimePage,
    required_summary_ids=("tour_time_of_day_by_tour_purpose",),
)

TourTimePage.definition = PAGE
