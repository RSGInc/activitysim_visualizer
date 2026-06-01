"""Trip and stop distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.helpers.category_helpers import column_options, nonempty
from dashboard.helpers.time_distance_helpers import distance_sort_expr
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    x_col: str,
    y_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter one distribution summary to a tour purpose and order the distance bins."""
    out = []
    for label, df in nonempty(data_list):
        out.append(
            (
                label,
                df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
                .filter(pl.col("tour_purpose") == tour_purpose)
                .select(
                    pl.col(x_col).alias("distance_bin"),
                    pl.col(y_col).alias("freq"),
                )
                .with_columns(distance_sort_expr("distance_bin").alias("_sort_distance"))
                .sort("_sort_distance")
                .drop("_sort_distance"),
            )
        )
    return out


class TripStopDistancePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        purpose_opts, self._tour_purpose_to_raw = column_options(
            self.state.get_summary_table_set("trip_distance_by_purpose", "weighted") or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_stop_distance",
                "trip_distance_by_purpose",
                "tour_purpose",
                "weighted",
            ),
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        purpose_opts = purpose_opts or [self.TOTAL_PURPOSE_LABEL]
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
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.tour_purpose_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        purpose_opts, self._tour_purpose_to_raw = column_options(
            summaries["trip_distance_by_purpose"],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_stop_distance",
                "trip_distance_by_purpose",
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
        raw_purpose = self._tour_purpose_to_raw.get(display_purpose, "all_tour_purposes")
        return display_purpose, raw_purpose

    def render_distance_chart(
        self,
        *,
        summary_data: list[tuple[str, pl.DataFrame]],
        cache_key: str,
        raw_purpose: str,
        display_purpose: str,
        x_col: str,
        y_col: str,
        title: str,
        xaxis_title: str,
        yaxis_title: str,
    ) -> pn.viewable.Viewable:
        chart_data = self.get_filtered_view(
            cache_key,
            raw_purpose,
            factory=lambda: distance_chart_data(summary_data, raw_purpose, x_col, y_col),
        )
        return density_chart(
            chart_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"{title} - {display_purpose}",
            xaxis_title=xaxis_title,
            yaxis_title=yaxis_title,
            normalize=False,
            as_percent=self.as_percent,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [self.summary_only_unavailable_card()]

        display_purpose, raw_purpose = self._selected_purpose()
        return [
            self.render_distance_chart(
                summary_data=summaries["trip_distance_by_purpose"],
                cache_key="trip_distance",
                raw_purpose=raw_purpose,
                display_purpose=display_purpose,
                x_col="distance_bin",
                y_col="trip_count",
                title="Trip Distance Distribution",
                xaxis_title="Distance (miles)",
                yaxis_title="Trips",
            ),
            self.render_distance_chart(
                summary_data=summaries["stop_out_of_direction_distance_by_tour_purpose"],
                cache_key="stop_out_of_direction_distance",
                raw_purpose=raw_purpose,
                display_purpose=display_purpose,
                x_col="distance_bin",
                y_col="stop_count",
                title="Stop Out-of-Direction Distance Distribution",
                xaxis_title="Out-of-Direction Distance (miles)",
                yaxis_title="Stops",
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
