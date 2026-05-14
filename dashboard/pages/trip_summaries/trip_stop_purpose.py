"""Trip and stop purpose page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_value_union, nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping


def stop_purpose_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if tour_purpose == "all_tour_purposes":
            if (
                "all_tour_purposes"
                in df["tour_purpose"].cast(pl.Utf8).unique().to_list()
            ):
                df = df.filter(pl.col("tour_purpose") == "all_tour_purposes")
            else:
                df = (
                    df.group_by("stop_destination_purpose")
                    .agg(stop_count=pl.col("stop_count").sum())
                    .with_columns(pl.col("stop_destination_purpose").cast(pl.Utf8))
                    .sort("stop_destination_purpose")
                )
        else:
            df = df.filter(pl.col("tour_purpose") == tour_purpose)
        out.append((label, df))
    return out


class TripStopPurposePage(DashboardPage):
    def _purpose_options_and_mapping(
        self,
        data_list: list[tuple[str, pl.DataFrame]],
    ) -> tuple[list[str], dict[str, str]]:
        return tour_purpose_mapping(
            column_value_union(data_list, "tour_purpose"),
            total_display="All",
            config=self.config,
        )

    def build_page(self) -> pn.viewable.Viewable:
        stop_data = self.state.get_summary_table_set(
            "stop_destination_purpose_by_tour_purpose",
            "weighted",
        )
        purpose_opts, self._tour_purpose_to_raw = self._purpose_options_and_mapping(
            stop_data or []
        )
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
        stop_purpose_list = summaries["stop_destination_purpose_by_tour_purpose"]
        purpose_opts, self._tour_purpose_to_raw = self._purpose_options_and_mapping(
            stop_purpose_list
        )
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

        trip_purpose_data = nonempty_runs(summaries["trip_purpose_distribution"])
        stop_purpose_list = summaries["stop_destination_purpose_by_tour_purpose"]
        tour_purpose = self.tour_purpose_sel.value
        raw_purpose = self._tour_purpose_to_raw.get(str(tour_purpose), str(tour_purpose))

        stop_purpose_data = self.get_filtered_view(
            "stop_destination_purpose",
            raw_purpose,
            factory=lambda: stop_purpose_chart_data(
                stop_purpose_list,
                raw_purpose,
            ),
        )

        return [
            pn.Column(
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(
                        control_row(
                            pn.pane.Markdown("**Tour Purpose:**"),
                            self.tour_purpose_sel,
                        )
                    ),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    bar_chart(
                        trip_purpose_data,
                        x_col="trip_purpose",
                        y_col="trip_count",
                        title="Trip Purpose",
                        xaxis_title="Trip Purpose",
                        yaxis_title="Trips",
                        pct_col="pct",
                        as_percent=self.as_percent,
                    ),
                    bar_chart(
                        stop_purpose_data,
                        x_col="stop_destination_purpose",
                        y_col="stop_count",
                        title=f"Stop Destination Purpose by Tour Purpose - {tour_purpose}",
                        xaxis_title="Stop Destination Purpose",
                        yaxis_title="Stops",
                        pct_col="pct",
                        as_percent=self.as_percent,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
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

TripStopPurposePage.definition = PAGE
