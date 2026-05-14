"""Trip and stop time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping
from dashboard.pages._shared.time_distance import max_timebin, time_label


def purpose_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    purposes_set = set()
    for _, df in nonempty_runs(data_list):
        if "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
    return sorted(str(purpose) for purpose in purposes_set) if purposes_set else []


def _profile(
    df: pl.DataFrame,
    val_col: str,
    purpose: str,
    maxbin: int,
) -> pl.DataFrame:
    return (
        df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        .filter(pl.col("tour_purpose") == purpose)
        .select(
            pl.col("time_bin"),
            pl.col(val_col),
        )
        .sort("time_bin")
        .with_columns(
            pl.col("time_bin")
            .map_elements(
                lambda tb: time_label(int(tb), maxbin),
                return_dtype=pl.Utf8,
            )
            .alias("clock_time")
        )
    )


def trip_stop_time_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
) -> tuple[list[tuple[str, pl.DataFrame]], list[tuple[str, pl.DataFrame]]]:
    maxbin = max_timebin(data_list)
    trip_data = []
    stop_data = []
    for label, df in nonempty_runs(data_list):
        trip_data.append(
            (label, _profile(df, "departure_trip_count", tour_purpose, maxbin))
        )
        stop_data.append(
            (label, _profile(df, "departure_stop_count", tour_purpose, maxbin))
        )
    return trip_data, stop_data


class TripStopTimePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        tod_data = self.state.get_summary_table_set(
            "trip_departure_time_by_purpose",
            "weighted",
        )
        raw_purposes = purpose_options(tod_data or [])
        purpose_opts, self._purpose_to_raw = tour_purpose_mapping(raw_purposes)
        if not purpose_opts:
            purpose_opts = ["Total"]
            self._purpose_to_raw = {"Total": "all_tour_purposes"}
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
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.tour_purpose_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        tod_list = summaries["trip_departure_time_by_purpose"]
        raw_purposes = purpose_options(tod_list)
        purpose_opts, self._purpose_to_raw = tour_purpose_mapping(raw_purposes)
        if not purpose_opts:
            purpose_opts = sorted(
                purpose for purpose in raw_purposes if purpose != "all_tour_purposes"
            )
            self._purpose_to_raw = {purpose: purpose for purpose in purpose_opts}
        if purpose_opts:
            self.tour_purpose_sel.options = purpose_opts
            if self.tour_purpose_sel.value not in purpose_opts:
                self.tour_purpose_sel.value = purpose_opts[0]

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

        tod_list = summaries["trip_departure_time_by_purpose"]
        raw_purposes = purpose_options(tod_list)
        if not self.tour_purpose_sel.options:
            purpose_opts, self._purpose_to_raw = tour_purpose_mapping(raw_purposes)
            if not purpose_opts:
                purpose_opts = sorted(
                    purpose
                    for purpose in raw_purposes
                    if purpose != "all_tour_purposes"
                )
                self._purpose_to_raw = {purpose: purpose for purpose in purpose_opts}
            if not purpose_opts:
                return [pn.pane.Markdown("No trip/stop time data available.")]
            self.tour_purpose_sel.options = purpose_opts
            self.tour_purpose_sel.value = purpose_opts[0]

        tour_purpose = self.tour_purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(tour_purpose, tour_purpose)

        trip_data, stop_data = self.get_filtered_view(
            "trip_stop_departure_time",
            raw_purpose,
            tuple(label for label, _ in tod_list),
            factory=lambda: trip_stop_time_chart_data(tod_list, str(raw_purpose)),
        )

        return [
            density_chart(
                trip_data,
                x_col="clock_time",
                y_col="departure_trip_count",
                title=f"Trip Departure Time Distribution - {tour_purpose}",
                xaxis_title="Clock Time (start at 03:00)",
                normalize=False,
                yaxis_title="Trips",
                as_percent=self.as_percent,
            ),
            density_chart(
                stop_data,
                x_col="clock_time",
                y_col="departure_stop_count",
                title=f"Stop Departure Time Distribution - {tour_purpose}",
                xaxis_title="Clock Time (start at 03:00)",
                normalize=False,
                yaxis_title="Stops",
                as_percent=self.as_percent,
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
