"""Tour time page."""

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


def tour_time_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    dep_data = []
    arr_data = []
    dur_data = []

    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))

        if purpose != "All":
            df = df.filter(pl.col("tour_purpose") == purpose)

        dep_data.append(
            (
                label,
                df.select(
                    pl.col("time_bin"),
                    pl.col("departure_tour_count"),
                ).sort("time_bin"),
            )
        )

        arr_data.append(
            (
                label,
                df.select(
                    pl.col("time_bin"),
                    pl.col("arrival_tour_count"),
                ).sort("time_bin"),
            )
        )

        dur_data.append(
            (
                label,
                df.select(
                    pl.col("time_bin"),
                    pl.col("duration_tour_count"),
                ).sort("time_bin"),
            )
        )

    return dep_data, arr_data, dur_data


class TourTimePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Time", state, config)

        purpose_opts = self._purpose_options()
        self.purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=purpose_opts,
            value=purpose_opts[0],
        )
        self._watch_widget(self.purpose_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Time"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.purpose_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "tour_time_of_day_by_tour_purpose", "weighted"
        )
        if data is None:
            return ["All"]
        return purpose_options(data)

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

        tod_list = summaries["tour_time_of_day_by_tour_purpose"]

        purpose_opts = purpose_options(tod_list)
        self.purpose_sel.options = purpose_opts
        if self.purpose_sel.value not in purpose_opts:
            self.purpose_sel.value = purpose_opts[0]
        purpose = self.purpose_sel.value

        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_time",
            purpose,
            factory=lambda: tour_time_chart_data(tod_list, purpose),
        )

        dep_chart = density_chart(
            dep_data,
            x_col="time_bin",
            y_col="departure_tour_count",
            title=f"Tour Departure Time Distribution - {purpose}",
            xaxis_title="Time of Day",
            normalize=False,
            as_percent=self.as_percent,
        )

        arr_chart = density_chart(
            arr_data,
            x_col="time_bin",
            y_col="arrival_tour_count",
            title=f"Tour Arrival Time Distribution - {purpose}",
            xaxis_title="Time of Day",
            normalize=False,
            as_percent=self.as_percent,
        )

        dur_chart = density_chart(
            dur_data,
            x_col="time_bin",
            y_col="duration_tour_count",
            title=f"Tour Duration Distribution - {purpose}",
            xaxis_title="Tour Duration (hours)",
            normalize=False,
            as_percent=self.as_percent,
        )

        self._body.objects = [
            dep_chart,
            arr_chart,
            dur_chart,
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_time",
    title="Tour Time",
    group_id="tour_summaries",
    child_id="tour_time",
    order=43,
    controller_cls=TourTimePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="purpose_sel",
            label="Tour Purpose",
        ),
    ),
    required_summary_ids=("tour_time_of_day_by_tour_purpose",),
)

TourTimePage.definition = PAGE
