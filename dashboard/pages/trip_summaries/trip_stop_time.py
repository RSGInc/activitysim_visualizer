"""Trip and stop time page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import SelectorSpec, SingleSelectorSummaryPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping
from dashboard.pages._shared.time_distance import max_timebin, time_label


def _profile(
    df: pl.DataFrame,
    val_col: str,
    purpose: str,
    maxbin: int,
) -> pl.DataFrame:
    base = pl.DataFrame({"time_bin": list(range(1, maxbin + 1))})
    return (
        base.join(
            df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
            .filter(pl.col("tour_purpose") == purpose)
            .select(
                pl.col("time_bin"),
                pl.col(val_col),
            ),
            on="time_bin",
            how="left",
        )
        .with_columns(pl.col(val_col).fill_null(0.0))
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


class TripStopTimePage(SingleSelectorSummaryPage):
    body_section_id = "trip_stop_time_body"

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        self._purpose_to_raw = {"Total": "all_tour_purposes"}
        return (
            SelectorSpec(
                selector_id="tour_purpose",
                label="Tour Purpose",
                attr_name="tour_purpose_sel",
                options_factory=lambda page: page._display_purpose_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Tour Purpose",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _display_purpose_options(self) -> list[str]:
        raw_purposes = self.state.get_summary_column_values(
            "trip_departure_time_by_purpose",
            "tour_purpose",
            self.weighting_key,
        )
        purpose_opts, self._purpose_to_raw = tour_purpose_mapping(
            raw_purposes,
            config=self.config,
        )
        if not purpose_opts:
            purpose_opts = ["Total"]
            self._purpose_to_raw = {"Total": "all_tour_purposes"}
        return purpose_opts

    def render_ready(self, summaries: dict[str, object]):

        tod_list = summaries["trip_departure_time_by_purpose"]
        if not self.tour_purpose_sel.options:
            purpose_opts, self._purpose_to_raw = tour_purpose_mapping(
                self.state.get_summary_column_values(
                    "trip_departure_time_by_purpose",
                    "tour_purpose",
                    self.weighting_key,
                ),
                config=self.config,
            )
            if not purpose_opts:
                return [pn.pane.Markdown("No trip/stop time data available.")]
            self.tour_purpose_sel.options = purpose_opts
            self.tour_purpose_sel.value = purpose_opts[0]

        tour_purpose = self.tour_purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(tour_purpose, tour_purpose)

        trip_data, stop_data = self.filtered_view(
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
