"""Trip and stop distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import SelectorSpec, SingleSelectorSummaryPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_value_union, nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping
from dashboard.pages._shared.time_distance import distance_bin_sort_expr


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    x_col: str,
    y_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    ordered_bins = (
        pl.DataFrame({"distance_bin": column_value_union(data_list, x_col)})
        .with_columns(distance_bin_sort_expr("distance_bin").alias("_sort_distance"))
        .sort("_sort_distance")
        .drop("_sort_distance")
    )
    out = []
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        df = df.filter(pl.col("tour_purpose") == tour_purpose)
        out.append(
            (
                label,
                ordered_bins.join(
                    df.select(
                        pl.col(x_col).cast(pl.Utf8).alias("distance_bin"),
                        pl.col(y_col).alias("freq"),
                    ),
                    on="distance_bin",
                    how="left",
                ).with_columns(pl.col("freq").fill_null(0.0)),
            )
        )
    return out


class TripStopDistancePage(SingleSelectorSummaryPage):
    body_section_id = "trip_stop_distance_body"

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        self._tour_purpose_to_raw = {"Total": "all_tour_purposes"}
        return (
            SelectorSpec(
                selector_id="tour_purpose",
                label="Tour Purpose",
                attr_name="tour_purpose_sel",
                options_factory=lambda page: page._purpose_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Tour Purpose",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _purpose_options(self) -> list[str]:
        raw_values = self.state.get_summary_column_values(
            "trip_distance_by_purpose",
            "tour_purpose",
            self.weighting_key,
        )
        options, self._tour_purpose_to_raw = tour_purpose_mapping(
            raw_values,
            config=self.config,
        )
        return options or ["Total"]

    def render_ready(self, summaries: dict[str, object]):
        trip_dist_list = summaries["trip_distance_by_purpose"]
        stop_ood_list = summaries["stop_out_of_direction_distance_by_tour_purpose"]
        tour_purpose = self.tour_purpose_sel.value
        raw_purpose = self._tour_purpose_to_raw.get(str(tour_purpose), str(tour_purpose))

        trip_distance_data = self.filtered_view(
            "trip_distance",
            raw_purpose,
            factory=lambda: distance_chart_data(
                trip_dist_list,
                raw_purpose,
                x_col="distance_bin",
                y_col="trip_count",
            ),
        )
        stop_ood_data = self.filtered_view(
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
