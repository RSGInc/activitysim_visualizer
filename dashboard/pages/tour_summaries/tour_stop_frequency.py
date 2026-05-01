"""Tour stop frequency page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
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


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    total_label: str = "All",
) -> list[str]:
    if col == "direction":
        return ["Both", "Outbound", "Inbound"]
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    if col == "tour_purpose":
        options = []
        if "all_tour_purposes" in vals:
            options.append("All")
        options.extend(
            sorted(
                v
                for v in vals
                if v not in {total_label, "Total", "all_tour_purposes"}
            )
        )
        if "All" not in options:
            options.insert(0, "All")
        return options
    return [total_label] + sorted(v for v in vals if v != total_label)


def stop_frequency_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    stop_col_map = {
        "Both": "total_stop_count",
        "Outbound": "outbound_stop_count",
        "Inbound": "inbound_stop_count",
    }
    stop_col = stop_col_map[direction]
    out = []

    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if purpose == "All":
            if "all_tour_purposes" in df["tour_purpose"].cast(pl.Utf8).unique().to_list():
                df = df.filter(pl.col("tour_purpose") == "all_tour_purposes")
            else:
                df = df.group_by(stop_col).agg(tour_count=pl.col("tour_count").sum())
                df = (
                    df.with_columns(pl.col(stop_col).cast(pl.Utf8).alias("stop_frequency"))
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
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Stop Frequency", state, config)

        stop_data = self.state.get_summary_table_set(
            "tour_stop_frequency_by_tour_purpose", "weighted"
        )

        self.purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=_options(stop_data or [], "tour_purpose"),
            value=_options(stop_data or [], "tour_purpose")[0],
        )
        self._watch_widget(self.purpose_sel)

        self.direction_sel = pn.widgets.Select(
            name="Direction",
            options=_options(stop_data or [], "direction", total_label="Both"),
            value=_options(stop_data or [], "direction", total_label="Both")[0],
        )
        self._watch_widget(self.direction_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Stop Frequency"),
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

        stop_list = summaries["tour_stop_frequency_by_tour_purpose"]
        atwork_list = _nonempty(summaries["atwork_subtour_frequency_distribution"])

        purpose_opts = _options(stop_list, "tour_purpose")
        self.purpose_sel.options = purpose_opts
        if self.purpose_sel.value not in purpose_opts:
            self.purpose_sel.value = purpose_opts[0]

        direction_opts = _options(stop_list, "direction", total_label="Both")
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = direction_opts[0]

        purpose = self.purpose_sel.value
        direction = self.direction_sel.value

        stop_data = self.get_filtered_view(
            "tour_stop_frequency",
            (purpose, direction),
            factory=lambda: stop_frequency_chart_data(
                stop_list,
                purpose,
                direction,
            ),
        )

        stop_chart = bar_chart(
            stop_data,
            x_col="stop_frequency",
            y_col="tour_count",
            title=f"Tour Stop Frequency - {purpose}, {direction}",
            xaxis_title="Stop Count",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        atwork_chart = bar_chart(
            atwork_list,
            x_col="atwork_subtour_frequency_category",
            y_col="atwork_subtour_count",
            title="At-Work Sub-Tour Frequency",
            xaxis_title="At-Work Sub-Tour Frequency",
            yaxis_title="Work Tours",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            pn.pane.Markdown("### Tour Stop Frequency"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.purpose_sel,
                pn.pane.Markdown("**Direction:**"),
                self.direction_sel,
            ),
            stop_chart,
            pn.pane.Markdown("### At-Work Sub-Tour Frequency"),
            atwork_chart,
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_stop_frequency",
    title="Tour Stop Frequency",
    group_id="tour_summaries",
    order=45,
    page_cls=TourStopFrequencyPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="purpose_sel",
            label="Tour Purpose",
        ),
        PageSelectorDefinition(
            selector_id="direction",
            widget_attr="direction_sel",
            label="Direction",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="tour_stop_frequency_body",
            view_attr="_body",
            selector_ids=("tour_purpose", "direction"),
        ),
    ),
    required_summary_ids=(
        "tour_stop_frequency_by_tour_purpose",
        "atwork_subtour_frequency_distribution",
    ),
)

TourStopFrequencyPage.definition = PAGE

