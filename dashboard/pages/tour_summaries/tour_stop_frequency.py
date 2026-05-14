"""Tour stop frequency page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_value_union, nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping


def _options(
    data_list: list[tuple[str, pl.DataFrame]], col: str, total_label: str = "All"
) -> list[str]:
    if col == "direction":
        return ["Both", "Outbound", "Inbound"]
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
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if purpose == "all_tour_purposes":
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
            "tour_stop_frequency_by_tour_purpose", "weighted"
        )
        purpose_opts, self._purpose_to_raw = self._purpose_options_and_mapping(
            stop_data or []
        )
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_opts,
                value=purpose_opts[0],
            ),
            label="Tour Purpose",
        )
        self.direction_sel = self.selector(
            "direction",
            widget=pn.widgets.Select(
                name="Direction",
                options=_options(stop_data or [], "direction", total_label="Both"),
                value=_options(stop_data or [], "direction", total_label="Both")[0],
            ),
            label="Direction",
        )
        self._body = self.section(
            "tour_stop_frequency_body",
            selectors=("tour_purpose", "direction"),
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
        purpose_opts, self._purpose_to_raw = self._purpose_options_and_mapping(
            stop_list
        )
        self.purpose_sel.options = purpose_opts
        if self.purpose_sel.value not in purpose_opts:
            self.purpose_sel.value = purpose_opts[0]
        direction_opts = _options(stop_list, "direction", total_label="Both")
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = direction_opts[0]

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
        atwork_list = nonempty_runs(summaries["atwork_subtour_frequency_distribution"])
        purpose = self.purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(str(purpose), str(purpose))
        direction = self.direction_sel.value
        stop_data = self.get_filtered_view(
            "tour_stop_frequency",
            (raw_purpose, direction),
            factory=lambda: stop_frequency_chart_data(stop_list, raw_purpose, direction),
        )
        return [
            pn.pane.Markdown("### Tour Stop Frequency"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.purpose_sel,
                pn.pane.Markdown("**Direction:**"),
                self.direction_sel,
            ),
            bar_chart(
                stop_data,
                "stop_frequency",
                "tour_count",
                f"Tour Stop Frequency - {purpose}, {direction}",
                "Stop Count",
                pct_col="pct",
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
            pn.pane.Markdown("### At-Work Sub-Tour Frequency"),
            bar_chart(
                atwork_list,
                "atwork_subtour_frequency_category",
                "atwork_subtour_count",
                "At-Work Sub-Tour Frequency",
                "At-Work Sub-Tour Frequency",
                pct_col="pct",
                yaxis_title="At-Work Sub-Tours",
                as_percent=self.as_percent,
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
