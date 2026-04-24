"""Trip and stop distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def purpose_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "tour_purpose" not in first_df.columns:
        return ["All"]

    vals = (
        first_df.select("tour_purpose")
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return ["All"] + sorted(v for v in vals if v != "All")


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    x_col: str,
    y_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))

        if tour_purpose != "All":
            df = df.filter(pl.col("tour_purpose") == tour_purpose)

        out.append(
            (
                label,
                df.select(
                    pl.col(x_col).alias("distance_bin"),
                    pl.col(y_col).alias("freq"),
                ).sort("distance_bin"),
            )
        )

    return out


class TripStopDistancePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Trip and Stop Distance", state, config)

        trip_dist_data = self.state.get_summary_table_set(
            "trip_distance_by_purpose",
            "weighted",
        )
        purpose_opts = purpose_options(trip_dist_data or [])

        self.tour_purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=purpose_opts,
            value=purpose_opts[0],
        )
        self._watch_widget(self.tour_purpose_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Trip and Stop Distance"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.tour_purpose_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        trip_dist_list = summaries["trip_distance_by_purpose"]
        stop_ood_list = summaries["stop_out_of_direction_distance_by_tour_purpose"]

        purpose_opts = purpose_options(trip_dist_list)
        self.tour_purpose_sel.options = purpose_opts
        if self.tour_purpose_sel.value not in purpose_opts:
            self.tour_purpose_sel.value = purpose_opts[0]
        tour_purpose = self.tour_purpose_sel.value

        trip_distance_data = self.get_filtered_view(
            "trip_distance",
            tour_purpose,
            factory=lambda: distance_chart_data(
                trip_dist_list,
                tour_purpose,
                x_col="distance_bin",
                y_col="trip_count",
            ),
        )

        stop_ood_data = self.get_filtered_view(
            "stop_out_of_direction_distance",
            tour_purpose,
            factory=lambda: distance_chart_data(
                stop_ood_list,
                tour_purpose,
                x_col="distance_bin",
                y_col="stop_count",
            ),
        )

        trip_distance_chart = density_chart(
            trip_distance_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"Trip Distance Distribution - {tour_purpose}",
            xaxis_title="Distance (miles)",
            normalize=False,
            as_percent=self.as_percent,
        )

        stop_ood_chart = density_chart(
            stop_ood_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"Stop Out-of-Direction Distance Distribution - {tour_purpose}",
            xaxis_title="Out-of-Direction Distance (miles)",
            normalize=False,
            as_percent=self.as_percent,
        )

        self._body.objects = [
            trip_distance_chart,
            stop_ood_chart,
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_stop_distance",
    title="Trip and Stop Distance",
    order=50,
    controller_cls=TripStopDistancePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="tour_purpose_sel",
            label="Tour Purpose",
        ),
    ),
    required_summary_ids=(
        "trip_distance_by_purpose",
        "stop_out_of_direction_distance_by_tour_purpose",
    ),
)

TripStopDistancePage.definition = PAGE
