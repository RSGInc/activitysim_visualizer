"""Trip and stop time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart, selector_row
from dashboard.helpers.category_helpers import column_options, nonempty
from dashboard.helpers.time_distance_helpers import max_timebin, timebin_label
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


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
    trip_data = []
    stop_data = []
    for label, df in nonempty(data_list):
        trip_data.append(
            (
                label,
                profile_chart_frame(
                    df,
                    value_col="departure_trip_count",
                    purpose=tour_purpose,
                    observed_max_timebin=observed_max_timebin,
                ),
            )
        )
        stop_data.append(
            (
                label,
                profile_chart_frame(
                    df,
                    value_col="departure_stop_count",
                    purpose=tour_purpose,
                    observed_max_timebin=observed_max_timebin,
                ),
            )
        )
    return trip_data, stop_data


class TripStopTimePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        purpose_opts, self._purpose_to_raw = column_options(
            self.state.get_summary_table_set("trip_departure_time_by_purpose", "weighted")
            or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_stop_time",
                "trip_departure_time_by_purpose",
                "tour_purpose",
                "weighted",
            ),
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        if not purpose_opts:
            purpose_opts = [self.TOTAL_PURPOSE_LABEL]
            self._purpose_to_raw = {self.TOTAL_PURPOSE_LABEL: "all_tour_purposes"}
        self.tour_purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_opts,
                value=purpose_opts[0],
            ),
            label="Tour Purpose",
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

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        purpose_opts, self._purpose_to_raw = column_options(
            summaries["trip_departure_time_by_purpose"],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_stop_time",
                "trip_departure_time_by_purpose",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        self.tour_purpose_sel.options = purpose_opts or [self.TOTAL_PURPOSE_LABEL]
        if self.tour_purpose_sel.value not in self.tour_purpose_sel.options:
            self.tour_purpose_sel.value = self.tour_purpose_sel.options[0]

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
        cache_key: str,
        title: str,
        y_col: str,
        yaxis_title: str,
    ) -> pn.viewable.Viewable:
        trip_data, stop_data = self.get_filtered_view(
            "trip_stop_departure_time",
            raw_purpose,
            tuple(label for label, _ in data_list),
            factory=lambda: trip_stop_time_chart_data(data_list, raw_purpose),
        )
        chart_data = trip_data if y_col == "departure_trip_count" else stop_data
        return density_chart(
            chart_data,
            x_col="clock_time",
            y_col=y_col,
            title=f"{title} - {display_purpose}",
            xaxis_title="Clock Time (start at 03:00)",
            normalize=False,
            yaxis_title=yaxis_title,
            hover_xaxis_title="Clock Time",
            as_percent=self.as_percent,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
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
                    cache_key="trip_departure",
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
                    cache_key="stop_departure",
                    title="Stop Departure Time Distribution",
                    y_col="departure_stop_count",
                    yaxis_title="Stops",
                ),
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_stop_time",
    title="Trip and Stop Time",
    group_id="trip_summaries",
    order=49,
    page_cls=TripStopTimePage,
    required_summary_ids=("trip_departure_time_by_purpose",),
)

TripStopTimePage.definition = PAGE
