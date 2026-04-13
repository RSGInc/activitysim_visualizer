"""Stop frequency page built from canonical summary-table columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def purpose_options(stop_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect available purpose options from canonical stop summaries."""
    purposes_set = set()
    for _, df in stop_list:
        if len(df) > 0 and "purpose" in df.columns:
            purposes_set.update(df["purpose"].drop_nulls().cast(pl.Utf8).unique().to_list())
    if purposes_set:
        return ["Total"] + [purpose for purpose in sorted(purposes_set) if purpose != "Total"]
    return ["Total"]


def frequency_chart_data(
    stop_list: list[tuple[str, pl.DataFrame]],
    purp: str,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build outbound, inbound, and total stop-frequency datasets."""
    if purp == "Total":
        ob_data = [
            (
                label,
                df.group_by("ob_stops")
                .agg(pl.col("freq").sum())
                .sort("ob_stops")
                .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.group_by("ib_stops")
                .agg(pl.col("freq").sum())
                .sort("ib_stops")
                .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.group_by("tot_stops")
                .agg(pl.col("freq").sum())
                .sort("tot_stops")
                .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    else:
        ob_data = [
            (
                label,
                df.filter(pl.col("purpose") == purp)
                .group_by("ob_stops")
                .agg(pl.col("freq").sum())
                .sort("ob_stops")
                .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.filter(pl.col("purpose") == purp)
                .group_by("ib_stops")
                .agg(pl.col("freq").sum())
                .sort("ib_stops")
                .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.filter(pl.col("purpose") == purp)
                .group_by("tot_stops")
                .agg(pl.col("freq").sum())
                .sort("tot_stops")
                .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    return ob_data, ib_data, tot_data


def purpose_chart_data(
    purp_by_tp: list[tuple[str, pl.DataFrame]],
    purp: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-purpose chart data for the selected tour purpose."""
    if purp == "Total":
        return [
            (label, df.group_by("stop_purpose").agg(pl.col("freq").sum()))
            for label, df in purp_by_tp
        ]
    return [
        (label, df.filter(pl.col("tour_purpose") == purp))
        for label, df in purp_by_tp
    ]


class StopFreqPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Frequency", state, config)
        purp_opts = self._purpose_options()
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Stop Frequency"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        stop_list = self.state.get_summary_table_set("stop_freq", "weighted")
        if stop_list is None:
            return ["Total"]
        return purpose_options(stop_list)

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

        purp = self.purp_sel.value
        stop_list = summaries["stop_freq"]
        purp_by_tp = summaries["stop_purpose_by_tour_purpose"]
        purp_opts = purpose_options(stop_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value

        ob_data, ib_data, tot_data, purp_chart_data = self.get_filtered_view(
            "stop_freq",
            purp,
            factory=lambda: (
                *frequency_chart_data(stop_list, purp),
                purpose_chart_data(purp_by_tp, purp),
            ),
        )

        self._body.objects = [
            pn.Row(
                bar_chart(
                    ob_data,
                    "stops",
                    "freq",
                    f"Outbound Stops - {purp}",
                    "Stops",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    ib_data,
                    "stops",
                    "freq",
                    f"Inbound Stops - {purp}",
                    "Stops",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    tot_data,
                    "stops",
                    "freq",
                    f"Total Stops - {purp}",
                    "Stops",
                    as_percent=self.as_percent,
                ),
            ),
            bar_chart(
                purp_chart_data,
                "stop_purpose",
                "freq",
                f"Stop Purpose - tour={purp}",
                "Stop Purpose",
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="stop_frequency",
    title="Stop Frequency",
    order=80,
    controller_cls=StopFreqPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="purp_sel",
            label="Tour Purpose",
        ),
    ),
    required_summary_ids=("stop_freq", "stop_purpose_by_tour_purpose"),
)

StopFreqPage.definition = PAGE
