"""Tour time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import selector_row
from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import column_options
from dashboard.helpers.time_distance_helpers import (
    max_timebin,
    timebin_duration_hours,
    timebin_label,
)
from dashboard import DashboardPage, dashboard_page


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
    filtered = (
        RunTables.from_runs(data_list)
        .with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        .where(tour_purpose=purpose)
    )

    def clock_profile(value_col: str) -> list[tuple[str, pl.DataFrame]]:
        return (
            filtered.select("time_bin", value_col)
            .sort("time_bin")
            .with_columns(
                pl.col("time_bin")
                .map_elements(
                    lambda value: timebin_label(int(value), observed_max_timebin),
                    return_dtype=pl.Utf8,
                )
                .alias("clock_time")
            )
        )

    duration = (
        filtered.select("time_bin", "duration_tour_count")
        .sort("time_bin")
        .with_columns(
            pl.col("time_bin")
            .map_elements(
                lambda value: timebin_duration_hours(int(value), observed_max_timebin),
                return_dtype=pl.Float64,
            )
            .alias("duration_hours")
        )
    )
    return (
        clock_profile("departure_tour_count"),
        clock_profile("arrival_tour_count"),
        duration,
    )


@dashboard_page(
    page_id="tour_time",
    title="Tour Time",
    group_id="tour_summaries",
    order=43,
    required_summary_ids=("tour_time_of_day_by_tour_purpose",),
)
class TourTimePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        self.purpose_sel = self.select(
            "tour_purpose",
            "Tour Purpose",
            options=self._purpose_options,
        )
        self._body = self.section(
            "tour_time_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Time"),
            selector_row(self.purpose_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        data = self.data.summary(
            "tour_time_of_day_by_tour_purpose",
            self.weighting_key,
        )
        if data is None:
            self._purpose_to_raw = {self.TOTAL_PURPOSE_LABEL: "all_tour_purposes"}
            return [self.TOTAL_PURPOSE_LABEL]
        options, self._purpose_to_raw = column_options(
            data,
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        return options or [self.TOTAL_PURPOSE_LABEL]

    def _selected_purpose(self) -> tuple[str, str]:
        display_purpose = self.purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(display_purpose, "all_tour_purposes")
        return display_purpose, str(raw_purpose)

    def render_time_charts(
        self,
        tod_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_purpose: str,
        display_purpose: str,
    ) -> tuple[pn.viewable.Viewable, pn.viewable.Viewable, pn.viewable.Viewable]:
        dep_data, arr_data, dur_data = self.query(
            lambda: tour_time_chart_data(tod_list, raw_purpose)
        )
        return (
            self.plot.density(
                dep_data,
                x="clock_time",
                y="departure_tour_count",
                title=f"Tour Departure Time Distribution - {display_purpose}",
                x_title="Clock Time (start at 03:00)",
                y_title="Tours",
                hover_x_title="Clock Time",
            ),
            self.plot.density(
                arr_data,
                x="clock_time",
                y="arrival_tour_count",
                title=f"Tour Arrival Time Distribution - {display_purpose}",
                x_title="Clock Time (start at 03:00)",
                y_title="Tours",
                hover_x_title="Clock Time",
            ),
            self.plot.density(
                dur_data,
                x="duration_hours",
                y="duration_tour_count",
                title=f"Tour Duration Distribution - {display_purpose}",
                x_title="Tour Duration (hours)",
                y_title="Tours",
            ),
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.data.summaries(*self.required_summary_ids)
        if not all(summaries.values()):
            return [self.summary_only_unavailable_card()]
        display_purpose, raw_purpose = self._selected_purpose()
        departure_chart, arrival_chart, duration_chart = self.render_time_charts(
            summaries["tour_time_of_day_by_tour_purpose"],
            raw_purpose=raw_purpose,
            display_purpose=display_purpose,
        )
        return [
            self.noted_view("tour_time.departure", departure_chart),
            self.noted_view("tour_time.arrival", arrival_chart),
            self.noted_view("tour_time.duration", duration_chart),
        ]
