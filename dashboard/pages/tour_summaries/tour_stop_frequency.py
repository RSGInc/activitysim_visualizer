"""Tour stop frequency page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import (
    column_options,
    label_category_data,
    nonempty,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

DIRECTION_OPTIONS = ["Both", "Outbound", "Inbound"]


def _options(
    data_list: list[tuple[str, pl.DataFrame]], col: str, total_label: str = "All"
) -> list[str]:
    if col == "direction":
        return DIRECTION_OPTIONS
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]
    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    return [total_label] + sorted(v for v in vals if v != total_label)


def stop_frequency_chart_data(
    data_list: list[tuple[str, pl.DataFrame]], purpose: str, direction: str
):
    stop_col = {
        "Both": "total_stop_count",
        "Outbound": "outbound_stop_count",
        "Inbound": "inbound_stop_count",
    }[direction]
    out = []
    for label, df in nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if purpose is None:
            if (
                "all_tour_purposes"
                in df["tour_purpose"].cast(pl.Utf8).unique().to_list()
            ):
                df = df.filter(pl.col("tour_purpose") == "all_tour_purposes")
            else:
                df = df.group_by(stop_col).agg(tour_count=pl.col("tour_count").sum())
                df = (
                    df.with_columns(
                        pl.col(stop_col).cast(pl.Utf8).alias("stop_frequency")
                    )
                    .select("stop_frequency", "tour_count")
                    .sort("stop_frequency")
                )
                out.append((label, df))
                continue
        else:
            df = df.filter(pl.col("tour_purpose") == purpose)
        df = df.group_by(stop_col).agg(tour_count=pl.col("tour_count").sum())
        df = (
            df.with_columns(pl.col(stop_col).cast(pl.Utf8).alias("stop_frequency"))
            .select("stop_frequency", "tour_count")
            .sort("stop_frequency")
        )
        out.append((label, df))
    return out


class TourStopFrequencyPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        stop_data = self.state.get_summary_table_set(
            "tour_stop_frequency_by_tour_purpose", "weighted"
        )
        purpose_opts, self._purpose_to_raw = column_options(
            stop_data or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_stop_frequency",
                "tour_stop_frequency_by_tour_purpose",
                "tour_purpose",
                "weighted",
            ),
            total_raw=None,
            total_label="All",
        )
        if not purpose_opts:
            purpose_opts = ["All"]
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_opts,
                value=purpose_opts[0],
            ),
            label="Tour Purpose",
        )
        self._body = self.section(
            "tour_stop_frequency_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Stop Frequency"),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        stop_list = summaries["tour_stop_frequency_by_tour_purpose"]
        purpose_opts, self._purpose_to_raw = column_options(
            stop_list,
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_stop_frequency",
                "tour_stop_frequency_by_tour_purpose",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw=None,
            total_label="All",
        )
        self.purpose_sel.options = purpose_opts
        if self.purpose_sel.value not in purpose_opts:
            self.purpose_sel.value = purpose_opts[0]

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
        stop_list = summaries["tour_stop_frequency_by_tour_purpose"]
        atwork_list = nonempty(summaries["atwork_subtour_frequency_distribution"])
        purpose = self.purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(purpose)
        stop_frequency_charts: list[pn.viewable.Viewable] = []
        for direction in DIRECTION_OPTIONS:
            stop_data = self.get_filtered_view(
                "tour_stop_frequency",
                (raw_purpose, direction),
                factory=lambda direction=direction: stop_frequency_chart_data(
                    stop_list,
                    raw_purpose,
                    direction,
                ),
            )
            stop_col = {
                "Both": "total_stop_count",
                "Outbound": "outbound_stop_count",
                "Inbound": "inbound_stop_count",
            }[direction]
            stop_frequency_raw_values = sorted(
                {
                    str(value)
                    for _, df in nonempty(stop_list)
                    for value in (
                        df[stop_col].cast(pl.Utf8).to_list()
                        if stop_col in df.columns
                        else []
                    )
                },
                key=lambda value: int(value) if value.isdigit() else 999,
            )
            stop_frequency_values = self.config.ordered_labels(
                "stop_frequency",
                stop_frequency_raw_values,
            )
            stop_frequency_charts.append(
                bar_chart(
                    label_category_data(
                        stop_data,
                        source_col="stop_frequency",
                        category_id="stop_frequency",
                        config=self.config,
                        target_col="stop_frequency_label",
                    ),
                    "stop_frequency_label",
                    "tour_count",
                    f"Tour Stop Frequency - Purpose: {purpose}, Direction: {direction}",
                    "Stop Count",
                    pct_col="pct",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                    xaxis_categoryarray=stop_frequency_values,
                )
            )
        return [
            pn.pane.Markdown("### Tour Stop Frequency"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.purpose_sel,
            ),
            *stop_frequency_charts,
            pn.pane.Markdown("### At-Work Sub-Tour Frequency"),
            bar_chart(
                label_category_data(
                    atwork_list,
                    source_col="atwork_subtour_frequency_category",
                    category_id="atwork_subtour_frequency_category",
                    config=self.config,
                    target_col="atwork_subtour_frequency_label",
                ),
                "atwork_subtour_frequency_label",
                "atwork_subtour_count",
                "At-Work Sub-Tour Frequency",
                "At-Work Sub-Tour Frequency",
                pct_col="pct",
                yaxis_title="At-Work Sub-Tours",
                as_percent=self.as_percent,
                xaxis_categoryarray=self.config.ordered_labels(
                    "atwork_subtour_frequency_category",
                    [
                        str(value)
                        for _, df in atwork_list
                        for value in (
                            df["atwork_subtour_frequency_category"]
                            .cast(pl.Utf8)
                            .to_list()
                            if "atwork_subtour_frequency_category" in df.columns
                            else []
                        )
                    ],
                ),
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_stop_frequency",
    title="Tour Stop Frequency",
    group_id="tour_summaries",
    order=45,
    page_cls=TourStopFrequencyPage,
    required_summary_ids=(
        "tour_stop_frequency_by_tour_purpose",
        "atwork_subtour_frequency_distribution",
    ),
)

TourStopFrequencyPage.definition = PAGE
