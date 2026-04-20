"""Stop frequency page built from canonical summary-table columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def purpose_options(stop_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect available purpose options from stop summaries."""
    purposes_set = set()
    for _, df in stop_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
    return sorted(str(purpose) for purpose in purposes_set) if purposes_set else []


def purpose_mapping(raw_purposes: list[str]) -> tuple[list[str], dict[str, str | None]]:
    """Build selector display values for tour-purpose summaries."""
    mapping: dict[str, str | None] = {}
    if "all_tour_purposes" in raw_purposes:
        mapping["Total"] = "all_tour_purposes"
    else:
        mapping["Total"] = None
    for purpose in raw_purposes:
        if purpose not in {"all_tour_purposes", "Total"}:
            mapping[purpose] = purpose
    return list(mapping), mapping


def frequency_chart_data(
    stop_list: list[tuple[str, pl.DataFrame]],
    purp: str | None,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build outbound, inbound, and total stop-frequency datasets."""
    if purp is None:
        ob_data = [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose")
                    .cast(pl.Utf8)
                    .is_in(["all_tour_purposes", "Total"])
                )
                .group_by("outbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("outbound_stop_count")
                .with_columns(
                    pl.col("outbound_stop_count").cast(pl.Utf8).alias("stops")
                ),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose")
                    .cast(pl.Utf8)
                    .is_in(["all_tour_purposes", "Total"])
                )
                .group_by("inbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("inbound_stop_count")
                .with_columns(pl.col("inbound_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose")
                    .cast(pl.Utf8)
                    .is_in(["all_tour_purposes", "Total"])
                )
                .group_by("total_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("total_stop_count")
                .with_columns(pl.col("total_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    else:
        ob_data = [
            (
                label,
                df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp)
                .group_by("outbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("outbound_stop_count")
                .with_columns(
                    pl.col("outbound_stop_count").cast(pl.Utf8).alias("stops")
                ),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp)
                .group_by("inbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("inbound_stop_count")
                .with_columns(pl.col("inbound_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp)
                .group_by("total_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("total_stop_count")
                .with_columns(pl.col("total_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    return ob_data, ib_data, tot_data


def purpose_chart_data(
    purp_by_tp: list[tuple[str, pl.DataFrame]],
    purp: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-purpose chart data for the selected tour purpose."""
    if purp is None:
        return [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose")
                    .cast(pl.Utf8)
                    .is_in(["all_tour_purposes", "Total"])
                )
                .group_by("stop_destination_purpose")
                .agg(pl.col("stop_count").sum().alias("stop_count")),
            )
            for label, df in purp_by_tp
        ]
    return [
        (label, df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp))
        for label, df in purp_by_tp
    ]


class StopFreqPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Frequency", state, config)
        purp_opts = self._purpose_options()
        _, self._purpose_to_raw = purpose_mapping(
            [] if purp_opts == ["Total"] else purp_opts
        )
        if not self._purpose_to_raw:
            self._purpose_to_raw = {"Total": None}
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
        stop_list = self.state.get_summary_table_set(
            "tour_stop_frequency_by_tour_purpose", "weighted"
        )
        if stop_list is None:
            return ["Total"]
        raw_purposes = purpose_options(stop_list)
        options, _ = purpose_mapping(raw_purposes)
        return options or ["Total"]

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

        stop_list = summaries["tour_stop_frequency_by_tour_purpose"]
        purp_by_tp = summaries["stop_destination_purpose_by_tour_purpose"]
        purp = self.purp_sel.value
        raw_purposes = purpose_options(stop_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)

        ob_data, ib_data, tot_data, purp_chart_data = self.get_filtered_view(
            "stop_freq",
            raw_purpose,
            factory=lambda: (
                *frequency_chart_data(stop_list, raw_purpose),
                purpose_chart_data(purp_by_tp, raw_purpose),
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
                "stop_destination_purpose",
                "stop_count",
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
    required_summary_ids=(
        "tour_stop_frequency_by_tour_purpose",
        "stop_destination_purpose_by_tour_purpose",
    ),
)

StopFreqPage.definition = PAGE
