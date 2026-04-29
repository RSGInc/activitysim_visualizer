"""Trip and stop purpose page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
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


def stop_purpose_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))

        if tour_purpose == "All":
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
    def __init__(self, state, config: Config) -> None:
        super().__init__("Trip and Stop Purpose", state, config)

        stop_data = self.state.get_summary_table_set(
            "stop_destination_purpose_by_tour_purpose",
            "weighted",
        )
        purpose_opts = purpose_options(stop_data or [])
        # TODO: Consider updating with page group-level selector
        self.tour_purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=purpose_opts,
            value=purpose_opts[0],
        )
        self._watch_widget(self.tour_purpose_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Trip and Stop Purpose"),
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

        trip_purpose_data = _nonempty(summaries["trip_purpose_distribution"])
        stop_purpose_list = summaries["stop_destination_purpose_by_tour_purpose"]

        purpose_opts = purpose_options(stop_purpose_list)
        self.tour_purpose_sel.options = purpose_opts
        if self.tour_purpose_sel.value not in purpose_opts:
            self.tour_purpose_sel.value = purpose_opts[0]
        tour_purpose = self.tour_purpose_sel.value

        stop_purpose_data = self.get_filtered_view(
            "stop_destination_purpose",
            tour_purpose,
            factory=lambda: stop_purpose_chart_data(
                stop_purpose_list,
                tour_purpose,
            ),
        )

        trip_purpose_chart = bar_chart(
            trip_purpose_data,
            x_col="trip_purpose",
            y_col="trip_count",
            title="Trip Purpose",
            xaxis_title="Trip Purpose",
            yaxis_title="Trips",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        stop_purpose_chart = bar_chart(
            stop_purpose_data,
            x_col="stop_destination_purpose",
            y_col="stop_count",
            title=f"Stop Destination Purpose by Tour Purpose - {tour_purpose}",
            xaxis_title="Stop Destination Purpose",
            yaxis_title="Stops",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
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
                    trip_purpose_chart,
                    stop_purpose_chart,
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_stop_purpose",
    title="Trip and Stop Purpose",
    group_id="trip_summaries",
    child_id="trip_stop_purpose",
    order=47,
    controller_cls=TripStopPurposePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="tour_purpose_sel",
            label="Tour Purpose",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="trip_stop_purpose_body",
            view_attr="_body",
            selector_ids=("tour_purpose",),
        ),
    ),
    required_summary_ids=(
        "trip_purpose_distribution",
        "stop_destination_purpose_by_tour_purpose",
    ),
)

TripStopPurposePage.definition = PAGE
