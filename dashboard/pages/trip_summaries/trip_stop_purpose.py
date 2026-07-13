"""Trip and stop purpose page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer
from dashboard.helpers.category_helpers import (
    column_options,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


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
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in data_list:
        if df is None or column not in df.columns:
            out.append((label, df))
            continue
        out.append(
            (
                label,
                df.with_columns(
                    pl.col(column)
                    .cast(pl.Utf8)
                    .map_elements(
                        lambda value: order_index.get(str(value), len(order_index)),
                        return_dtype=pl.Int64,
                    )
                    .alias("_category_order")
                )
                .sort("_category_order")
                .drop("_category_order"),
            )
        )
    return out


def stop_purpose_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-purpose distributions for the selected tour purpose."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if tour_purpose is None:
            filtered = (
                filtered.group_by("stop_destination_purpose")
                .agg(stop_count=pl.col("stop_count").sum())
                .with_columns(pl.col("stop_destination_purpose").cast(pl.Utf8))
                .sort("stop_destination_purpose")
            )
        else:
            filtered = filtered.filter(pl.col("tour_purpose") == tour_purpose)
        out.append((label, filtered))
    return out


def trip_purpose_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build trip-purpose distributions for the selected tour purpose."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if tour_purpose is None:
            if "all_tour_purposes" in filtered["tour_purpose"].cast(pl.Utf8).unique().to_list():
                filtered = filtered.filter(pl.col("tour_purpose") == "all_tour_purposes")
            else:
                filtered = (
                    filtered.group_by("trip_purpose")
                    .agg(trip_count=pl.col("trip_count").sum())
                    .with_columns(pl.col("trip_purpose").cast(pl.Utf8))
                    .sort("trip_purpose")
                )
                out.append((label, filtered))
                continue
        else:
            filtered = filtered.filter(pl.col("tour_purpose") == tour_purpose)
        out.append((label, filtered))
    return out


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
        purpose_opts, self._tour_purpose_to_raw = column_options(
            self.state.get_summary_table_set(
                "stop_destination_purpose_by_tour_purpose", "weighted"
            )
            or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_stop_purpose",
                "stop_destination_purpose_by_tour_purpose",
                "tour_purpose",
                "weighted",
            ),
            total_raw=None,
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        self.tour_purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_opts or [self.TOTAL_PURPOSE_LABEL],
                value=(purpose_opts or [self.TOTAL_PURPOSE_LABEL])[0],
            ),
            label="Tour Purpose",
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

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        purpose_opts, self._tour_purpose_to_raw = column_options(
            summaries["stop_destination_purpose_by_tour_purpose"],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_stop_purpose",
                "stop_destination_purpose_by_tour_purpose",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw=None,
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        self.tour_purpose_sel.options = purpose_opts or [self.TOTAL_PURPOSE_LABEL]
        if self.tour_purpose_sel.value not in self.tour_purpose_sel.options:
            self.tour_purpose_sel.value = self.tour_purpose_sel.options[0]

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
        chart_data = self.get_filtered_view(
            "trip_purpose",
            raw_tour_purpose,
            factory=lambda: trip_purpose_chart_data(trip_purpose_list, raw_tour_purpose),
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
        return bar_chart(
            chart_data,
            x_col="trip_purpose",
            y_col="trip_count",
            title=self._trip_purpose_title(display_purpose),
            xaxis_title="Trip Purpose",
            yaxis_title="Trips",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=label_values,
        )

    def render_stop_purpose_chart(
        self,
        stop_purpose_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_tour_purpose: str | None,
        display_purpose: str,
    ) -> pn.viewable.Viewable:
        chart_data = self.get_filtered_view(
            "stop_destination_purpose",
            raw_tour_purpose,
            factory=lambda: stop_purpose_chart_data(stop_purpose_list, raw_tour_purpose),
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
        return bar_chart(
            chart_data,
            x_col="stop_destination_purpose",
            y_col="stop_count",
            title=self._stop_purpose_title(display_purpose),
            xaxis_title="Stop Destination Purpose",
            yaxis_title="Stops",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=label_values,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
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


PAGE = DashboardPageDefinition(
    page_id="trip_stop_purpose",
    title="Trip and Stop Purpose",
    group_id="trip_summaries",
    order=47,
    page_cls=TripStopPurposePage,
    required_summary_ids=(
        "trip_purpose_distribution",
        "stop_destination_purpose_by_tour_purpose",
    ),
)
