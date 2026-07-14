"""Trip and stop purpose page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import control_row, control_row_spacer
from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    column_options,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard import DashboardPage, dashboard_page


def order_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    column: str,
    ordered_values: list[str],
) -> list[tuple[str, pl.DataFrame]]:
    """Order chart rows by one configured category sequence."""
    if not ordered_values:
        return data_list
    order_index = {str(value): idx for idx, value in enumerate(ordered_values)}

    def order(frame: pl.DataFrame) -> pl.DataFrame:
        if column not in frame.columns:
            return frame
        return (
            frame.with_columns(
                pl.col(column)
                .cast(pl.Utf8)
                .map_elements(
                    lambda value: order_index.get(str(value), len(order_index)),
                    return_dtype=pl.Int64,
                )
                .alias("_category_order")
            )
            .sort("_category_order")
            .drop("_category_order")
        )

    return RunTables.from_runs(data_list).map(order)


def stop_purpose_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-purpose distributions for the selected tour purpose."""

    def shape(frame: pl.DataFrame) -> pl.DataFrame:
        filtered = frame.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if tour_purpose is None:
            filtered = (
                filtered.group_by("stop_destination_purpose")
                .agg(stop_count=pl.col("stop_count").sum())
                .with_columns(pl.col("stop_destination_purpose").cast(pl.Utf8))
                .sort("stop_destination_purpose")
            )
        else:
            filtered = filtered.filter(pl.col("tour_purpose") == tour_purpose)
        return filtered

    return RunTables.from_runs(data_list).map(shape)


def trip_purpose_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build trip-purpose distributions for the selected tour purpose."""

    def shape(frame: pl.DataFrame) -> pl.DataFrame:
        filtered = frame.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if tour_purpose is None:
            if (
                "all_tour_purposes"
                in filtered["tour_purpose"].cast(pl.Utf8).unique().to_list()
            ):
                filtered = filtered.filter(
                    pl.col("tour_purpose") == "all_tour_purposes"
                )
            else:
                filtered = (
                    filtered.group_by("trip_purpose")
                    .agg(trip_count=pl.col("trip_count").sum())
                    .with_columns(pl.col("trip_purpose").cast(pl.Utf8))
                    .sort("trip_purpose")
                )
                return filtered
        else:
            filtered = filtered.filter(pl.col("tour_purpose") == tour_purpose)
        return filtered

    return RunTables.from_runs(data_list).map(shape)


@dashboard_page(
    page_id="trip_stop_purpose",
    title="Trip and Stop Purpose",
    group_id="trip_summaries",
    order=47,
    required_summary_ids=(
        "trip_purpose_distribution",
        "stop_destination_purpose_by_tour_purpose",
    ),
)
class TripStopPurposePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def _trip_purpose_title(self, display_purpose: str) -> str:
        """Return the chart title for the selected tour-purpose slice."""
        purpose_label = self._tour_slice_title_label(display_purpose)
        return f"Trip Purpose for {purpose_label}"

    def _stop_purpose_title(self, display_purpose: str) -> str:
        """Return the stop-destination chart title for the selected tour-purpose slice."""
        purpose_label = self._tour_slice_title_label(display_purpose)
        return f"Stop Destination Purpose for {purpose_label}"

    def _tour_slice_title_label(self, display_purpose: str) -> str:
        """Return a display label such as All Tours or Work Tours."""
        if display_purpose in {self.TOTAL_PURPOSE_LABEL, "All Trip Purposes"}:
            return "All Tours"
        purpose_label = str(display_purpose)
        if not purpose_label.casefold().endswith(" tours"):
            purpose_label = f"{purpose_label} Tours"
        return purpose_label

    def build_page(self) -> pn.viewable.Viewable:
        self.tour_purpose_sel = self.select(
            "tour_purpose",
            "Tour Purpose",
            options=self._purpose_options,
        )
        self._body = self.section(
            "trip_stop_purpose_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip and Stop Purpose"),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        purpose_opts, self._tour_purpose_to_raw = column_options(
            self.data.summary(
                "stop_destination_purpose_by_tour_purpose", self.weighting_key
            )
            or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            total_raw=None,
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        return purpose_opts or [self.TOTAL_PURPOSE_LABEL]

    def _selected_purpose(self) -> tuple[str, str | None]:
        display_purpose = self.tour_purpose_sel.value
        return display_purpose, self._tour_purpose_to_raw.get(display_purpose)

    def render_trip_purpose_chart(
        self,
        trip_purpose_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_tour_purpose: str | None,
        display_purpose: str,
    ) -> pn.viewable.Viewable:
        chart_data = self.query(
            lambda: trip_purpose_chart_data(trip_purpose_list, raw_tour_purpose)
        )
        raw_values = ordered_category_values(
            nonempty(trip_purpose_list),
            "trip_purpose",
            category_id="trip_purpose",
            config=self.config,
        )
        label_values = self.config.ordered_labels("trip_purpose", raw_values)
        chart_data = order_chart_data(
            label_category_data(
                chart_data,
                category_id="trip_purpose",
                config=self.config,
                source_col="trip_purpose",
                target_col="trip_purpose",
            ),
            column="trip_purpose",
            ordered_values=label_values,
        )
        return self.plot.bar(
            chart_data,
            x="trip_purpose",
            y="trip_count",
            title=self._trip_purpose_title(display_purpose),
            x_title="Trip Purpose",
            y_title="Trips",
            category_order=label_values,
        )

    def render_stop_purpose_chart(
        self,
        stop_purpose_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_tour_purpose: str | None,
        display_purpose: str,
    ) -> pn.viewable.Viewable:
        chart_data = self.query(
            lambda: stop_purpose_chart_data(stop_purpose_list, raw_tour_purpose)
        )
        raw_values = ordered_category_values(
            nonempty(stop_purpose_list),
            "stop_destination_purpose",
            category_id="stop_purpose",
            config=self.config,
        )
        label_values = self.config.ordered_labels("stop_purpose", raw_values)
        chart_data = order_chart_data(
            label_category_data(
                chart_data,
                category_id="stop_purpose",
                config=self.config,
                source_col="stop_destination_purpose",
                target_col="stop_destination_purpose",
            ),
            column="stop_destination_purpose",
            ordered_values=label_values,
        )
        return self.plot.bar(
            chart_data,
            x="stop_destination_purpose",
            y="stop_count",
            title=self._stop_purpose_title(display_purpose),
            x_title="Stop Destination Purpose",
            y_title="Stops",
            category_order=label_values,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.data.summaries(*self.required_summary_ids)
        if not all(summaries.values()):
            return [self.summary_only_unavailable_card()]
        display_purpose, raw_tour_purpose = self._selected_purpose()
        return [
            pn.Column(
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(control_row(self.tour_purpose_sel)),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    self.render_trip_purpose_chart(
                        summaries["trip_purpose_distribution"],
                        raw_tour_purpose=raw_tour_purpose,
                        display_purpose=display_purpose,
                    ),
                    self.render_stop_purpose_chart(
                        summaries["stop_destination_purpose_by_tour_purpose"],
                        raw_tour_purpose=raw_tour_purpose,
                        display_purpose=display_purpose,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            )
        ]
