"""Trip and stop time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import selector_row
from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import column_options
from dashboard.helpers.time_distance_helpers import max_timebin, timebin_label
from dashboard import DashboardPage, dashboard_page


def profile_chart_frame(
    df: pl.DataFrame,
    *,
    value_col: str,
    purpose: str,
    observed_max_timebin: int,
) -> pl.DataFrame:
    """Return one clock-time distribution for one selected tour purpose."""
    return (
        df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        .filter(pl.col("tour_purpose") == purpose)
        .select(pl.col("time_bin"), pl.col(value_col))
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


def trip_stop_time_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
) -> tuple[list[tuple[str, pl.DataFrame]], list[tuple[str, pl.DataFrame]]]:
    """Build chart-ready trip and stop departure distributions for one purpose."""
    observed_max_timebin = max_timebin(data_list)
    view = RunTables.from_runs(data_list)

    def profile(value_col: str) -> list[tuple[str, pl.DataFrame]]:
        return view.map(
            lambda frame: profile_chart_frame(
                frame,
                value_col=value_col,
                purpose=tour_purpose,
                observed_max_timebin=observed_max_timebin,
            )
        )

    return profile("departure_trip_count"), profile("departure_stop_count")


@dashboard_page(
    page_id="trip_stop_time",
    title="Trip and Stop Time",
    group_id="trip_summaries",
    order=49,
    required_summary_ids=("trip_departure_time_by_purpose",),
)
class TripStopTimePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        self.tour_purpose_sel = self.select(
            "tour_purpose",
            "Tour Purpose",
            options=self._purpose_options,
        )
        self._body = self.section(
            "trip_stop_time_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip and Stop Time"),
            selector_row(self.tour_purpose_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        purpose_opts, self._purpose_to_raw = column_options(
            self.data.summary("trip_departure_time_by_purpose", self.weighting_key)
            or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        if not purpose_opts:
            purpose_opts = [self.TOTAL_PURPOSE_LABEL]
            self._purpose_to_raw = {self.TOTAL_PURPOSE_LABEL: "all_tour_purposes"}
        return purpose_opts

    def _selected_purpose(self) -> tuple[str, str]:
        display_purpose = self.tour_purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(display_purpose, display_purpose)
        return display_purpose, str(raw_purpose)

    def render_time_chart(
        self,
        data_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_purpose: str,
        display_purpose: str,
        title: str,
        y_col: str,
        yaxis_title: str,
    ) -> pn.viewable.Viewable:
        trip_data, stop_data = self.query(
            lambda: trip_stop_time_chart_data(data_list, raw_purpose)
        )
        chart_data = trip_data if y_col == "departure_trip_count" else stop_data
        return self.plot.density(
            chart_data,
            x="clock_time",
            y=y_col,
            title=f"{title} - {display_purpose}",
            x_title="Clock Time (start at 03:00)",
            y_title=yaxis_title,
            hover_x_title="Clock Time",
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.data.summaries(*self.required_summary_ids)
        if not all(summaries.values()):
            return [self.summary_only_unavailable_card()]
        display_purpose, raw_purpose = self._selected_purpose()
        tod_list = summaries["trip_departure_time_by_purpose"]
        return [
            self.noted_view(
                "trip_stop_time.trips",
                self.render_time_chart(
                    tod_list,
                    raw_purpose=raw_purpose,
                    display_purpose=display_purpose,
                    title="Trip Departure Time Distribution",
                    y_col="departure_trip_count",
                    yaxis_title="Trips",
                ),
            ),
            self.noted_view(
                "trip_stop_time.stops",
                self.render_time_chart(
                    tod_list,
                    raw_purpose=raw_purpose,
                    display_purpose=display_purpose,
                    title="Stop Departure Time Distribution",
                    y_col="departure_stop_count",
                    yaxis_title="Stops",
                ),
            ),
        ]
