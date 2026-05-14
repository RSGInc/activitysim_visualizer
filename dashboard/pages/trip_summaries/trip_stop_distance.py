"""Trip and stop distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import nonempty_runs
from dashboard.pages._shared.purposes import raw_tour_purpose, tour_purpose_options
from dashboard.pages._shared.time_distance import distance_bin_sort_expr


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    x_col: str,
    y_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        df = df.filter(pl.col("tour_purpose") == tour_purpose)
        out.append(
            (
                label,
                df.select(
                    pl.col(x_col).alias("distance_bin"),
                    pl.col(y_col).alias("freq"),
                )
                .with_columns(
                    distance_bin_sort_expr("distance_bin").alias("_sort_distance")
                )
                .sort("_sort_distance")
                .drop("_sort_distance"),
            )
        )
    return out


class TripStopDistancePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        trip_dist_data = self.state.get_summary_table_set(
            "trip_distance_by_purpose",
            "weighted",
        )
        purpose_opts = tour_purpose_options(trip_dist_data or [])
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
            "trip_stop_distance_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip and Stop Distance"),
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
        trip_dist_list = summaries["trip_distance_by_purpose"]
        purpose_opts = tour_purpose_options(trip_dist_list)
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

        trip_dist_list = summaries["trip_distance_by_purpose"]
        stop_ood_list = summaries["stop_out_of_direction_distance_by_tour_purpose"]
        tour_purpose = self.tour_purpose_sel.value
        raw_purpose = raw_tour_purpose(tour_purpose)

        trip_distance_data = self.get_filtered_view(
            "trip_distance",
            raw_purpose,
            factory=lambda: distance_chart_data(
                trip_dist_list,
                raw_purpose,
                x_col="distance_bin",
                y_col="trip_count",
            ),
        )
        stop_ood_data = self.get_filtered_view(
            "stop_out_of_direction_distance",
            raw_purpose,
            factory=lambda: distance_chart_data(
                stop_ood_list,
                raw_purpose,
                x_col="distance_bin",
                y_col="stop_count",
            ),
        )

        return [
            density_chart(
                trip_distance_data,
                x_col="distance_bin",
                y_col="freq",
                title=f"Trip Distance Distribution - {tour_purpose}",
                xaxis_title="Distance (miles)",
                yaxis_title="Trips",
                normalize=False,
                as_percent=self.as_percent,
            ),
            density_chart(
                stop_ood_data,
                x_col="distance_bin",
                y_col="freq",
                title=f"Stop Out-of-Direction Distance Distribution - {tour_purpose}",
                xaxis_title="Out-of-Direction Distance (miles)",
                yaxis_title="Stops",
                normalize=False,
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_stop_distance",
    title="Trip and Stop Distance",
    group_id="trip_summaries",
    order=50,
    page_cls=TripStopDistancePage,
    required_summary_ids=(
        "trip_distance_by_purpose",
        "stop_out_of_direction_distance_by_tour_purpose",
    ),
)

TripStopDistancePage.definition = PAGE
