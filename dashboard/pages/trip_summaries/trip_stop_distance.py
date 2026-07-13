"""Trip and stop distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart, selector_row
from dashboard.data_access import RunTableView
from dashboard.helpers.category_helpers import (
    cap_numeric_category_frame,
    column_options,
)
from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard.helpers.time_distance_helpers import distance_sort_expr
from dashboard import DashboardPage, dashboard_page


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    x_col: str,
    y_col: str,
    *,
    cap_at: int | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter one distribution summary to a tour purpose and order the distance bins."""
    def shape(frame: pl.DataFrame) -> pl.DataFrame:
        chart = (
            frame.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
            .filter(pl.col("tour_purpose") == tour_purpose)
            .select(
                pl.col(x_col).alias("distance_bin"),
                pl.col(y_col).alias("freq"),
            )
        )
        if cap_at is not None:
            chart = cap_numeric_category_frame(
                chart,
                category_col="distance_bin",
                cap_value=cap_at,
                value_cols=("freq",),
            )
        return (
            chart.with_columns(distance_sort_expr("distance_bin").alias("_sort_distance"))
            .sort("_sort_distance")
            .drop("_sort_distance")
        )
    return RunTableView.from_runs(data_list).map(shape).collect()


@dashboard_page(
    page_id="trip_stop_distance",
    title="Trip and Stop Distance",
    group_id="trip_summaries",
    order=50,
    required_summary_ids=(
        "trip_distance_by_purpose",
        "stop_out_of_direction_distance_by_tour_purpose",
    ),
)
class TripStopDistancePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def _tour_slice_title_label(self, display_purpose: str) -> str:
        """Return a display label such as All Tours or Work Tours."""
        if display_purpose == self.TOTAL_PURPOSE_LABEL:
            return "All Tours"
        purpose_label = str(display_purpose)
        if not purpose_label.casefold().endswith(" tours"):
            purpose_label = f"{purpose_label} Tours"
        return purpose_label

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
        self.trip_stop_distance_range = DistanceRangeControls.create(
            self,
            "trip_stop_distance",
            max_options=capped_distance_max_options(),
            reset_label="Reset distance range",
        )
        self._body = self.section(
            "trip_stop_distance_body",
            selectors=("tour_purpose", *self.trip_stop_distance_range.selector_ids),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip and Stop Distance"),
            selector_row(self.tour_purpose_sel),
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
        cap_at: int | None = None,
        x_range: tuple[float, float] | None = None,
    ) -> pn.viewable.Viewable:
        chart_data = self.get_filtered_view(
            cache_key,
            (raw_purpose, cap_at),
            factory=lambda: distance_chart_data(
                summary_data,
                raw_purpose,
                x_col,
                y_col,
                cap_at=cap_at,
            ),
        )
        axis_data = with_distance_axis(chart_data)
        tickvals, ticktext = fixed_distance_axis_ticks()
        return density_chart(
            axis_data,
            x_col="_distance_axis",
            y_col="freq",
            title=f"{title} for {self._tour_slice_title_label(display_purpose)}",
            xaxis_title=xaxis_title,
            yaxis_title=yaxis_title,
            normalize=False,
            as_percent=self.as_percent,
            xaxis_range=x_range,
            xaxis_tickvals=tickvals,
            xaxis_ticktext=ticktext,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [self.summary_only_unavailable_card()]

        display_purpose, raw_purpose = self._selected_purpose()
        trip_distance_data = self.get_filtered_view(
            "trip_distance",
            (raw_purpose, None),
            factory=lambda: distance_chart_data(
                summaries["trip_distance_by_purpose"],
                raw_purpose,
                "distance_bin",
                "trip_count",
                cap_at=None,
            ),
        )
        stop_distance_data = self.get_filtered_view(
            "stop_out_of_direction_distance",
            (raw_purpose, 40),
            factory=lambda: distance_chart_data(
                summaries["stop_out_of_direction_distance_by_tour_purpose"],
                raw_purpose,
                "distance_bin",
                "stop_count",
                cap_at=40,
            ),
        )
        observed_bounds = distance_axis_bounds([*trip_distance_data, *stop_distance_data])
        bounds = (0.0, 40.0) if observed_bounds is not None else None
        self.trip_stop_distance_range.sync(
            (raw_purpose, self.weighting_key),
            bounds,
        )
        x_range = self.trip_stop_distance_range.current_range()
        if bounds is not None and x_range is None:
            return [
                self.trip_stop_distance_range.row(),
                self.data_not_available_card(
                    detail="Trip and stop distance controls require finite values with min less than max.",
                    title="Trip and Stop Distance Data Not Available",
                ),
            ]
        return [
            self.trip_stop_distance_range.row(),
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
                x_range=x_range,
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
                cap_at=40,
                x_range=x_range,
            ),
        ]
