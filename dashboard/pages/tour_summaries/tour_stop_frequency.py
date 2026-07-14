"""Tour stop frequency page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import selector_row
from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    capped_numeric_category_expr,
    column_options,
    label_category_data,
    nonempty,
    numeric_like_sort_expr,
)
from dashboard import DashboardPage, dashboard_page

STOP_FREQUENCY_VALUES = {
    "Both": ["0", "1", "2", "3", "4", "5", "6+"],
    "Outbound": ["0", "1", "2", "3+"],
    "Inbound": ["0", "1", "2", "3+"],
}


def stop_frequency_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str | None,
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one stop-frequency distribution for the selected purpose and direction."""
    stop_col = {
        "Both": "total_stop_count",
        "Outbound": "outbound_stop_count",
        "Inbound": "inbound_stop_count",
    }[direction]
    cap_value = 6 if direction == "Both" else 3
    def build_frame(df: pl.DataFrame) -> pl.DataFrame:
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if purpose is None:
            if "all_tour_purposes" in filtered["tour_purpose"].cast(pl.Utf8).unique().to_list():
                filtered = filtered.filter(pl.col("tour_purpose") == "all_tour_purposes")
            else:
                filtered = filtered.with_columns(
                    capped_numeric_category_expr(stop_col, cap_value)
                ).group_by(stop_col).agg(
                    tour_count=pl.col("tour_count").sum()
                )
                filtered = (
                    filtered.with_columns(pl.col(stop_col).cast(pl.Utf8).alias("stop_frequency"))
                    .select("stop_frequency", "tour_count")
                    .sort(numeric_like_sort_expr("stop_frequency"))
                )
                return filtered
        else:
            filtered = filtered.filter(pl.col("tour_purpose") == purpose)
        filtered = filtered.with_columns(
            capped_numeric_category_expr(stop_col, cap_value)
        ).group_by(stop_col).agg(tour_count=pl.col("tour_count").sum())
        filtered = (
            filtered.with_columns(pl.col(stop_col).cast(pl.Utf8).alias("stop_frequency"))
            .select("stop_frequency", "tour_count")
            .sort(numeric_like_sort_expr("stop_frequency"))
        )
        return filtered

    return RunTables.from_runs(data_list).map(build_frame)


@dashboard_page(
    page_id="tour_stop_frequency",
    title="Tour Stop Frequency",
    group_id="tour_summaries",
    order=45,
    required_summary_ids=(
        "tour_stop_frequency_by_tour_purpose",
        "atwork_subtour_frequency_distribution",
    ),
)
class TourStopFrequencyPage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        purpose_opts, self._purpose_to_raw = column_options(
            self.data.summary(
                "tour_stop_frequency_by_tour_purpose", "weighted"
            )
            or [],
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
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_opts or [self.TOTAL_PURPOSE_LABEL],
                value=(purpose_opts or [self.TOTAL_PURPOSE_LABEL])[0],
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
        summaries = self.data.summaries(*self.required_summary_ids)
        if not all(summaries.values()):
            return
        purpose_opts, self._purpose_to_raw = column_options(
            summaries["tour_stop_frequency_by_tour_purpose"],
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
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        self.purpose_sel.options = purpose_opts or [self.TOTAL_PURPOSE_LABEL]
        if self.purpose_sel.value not in self.purpose_sel.options:
            self.purpose_sel.value = self.purpose_sel.options[0]

    def _selected_purpose(self) -> tuple[str, str | None]:
        display_purpose = self.purpose_sel.value
        return display_purpose, self._purpose_to_raw.get(display_purpose)

    def render_direction_chart(
        self,
        stop_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_purpose: str | None,
        display_purpose: str,
        direction: str,
    ) -> pn.viewable.Viewable:
        stop_data = self.get_filtered_view(
            "tour_stop_frequency",
            (raw_purpose, direction),
            factory=lambda: stop_frequency_chart_data(stop_list, raw_purpose, direction),
        )
        raw_values = STOP_FREQUENCY_VALUES[direction]
        label_values = self.config.ordered_labels("stop_frequency", raw_values)
        return self.plot.bar(
            label_category_data(
                stop_data,
                source_col="stop_frequency",
                category_id="stop_frequency",
                config=self.config,
                target_col="stop_frequency_label",
            ),
            x="stop_frequency_label",
            y="tour_count",
            title=f"Tour Stop Frequency - Purpose: {display_purpose}, Direction: {direction}",
            x_title="Stop Count",
            y_title="Tours",
            category_order=label_values,
        )

    def render_atwork_chart(
        self,
        atwork_list: list[tuple[str, pl.DataFrame]],
    ) -> pn.viewable.Viewable:
        label_values = self.config.ordered_labels(
            "atwork_subtour_frequency_category",
            [
                str(value)
                for _, df in atwork_list
                for value in (
                    df["atwork_subtour_frequency_category"].cast(pl.Utf8).to_list()
                    if "atwork_subtour_frequency_category" in df.columns
                    else []
                )
            ],
        )
        return self.plot.bar(
            label_category_data(
                atwork_list,
                source_col="atwork_subtour_frequency_category",
                category_id="atwork_subtour_frequency_category",
                config=self.config,
                target_col="atwork_subtour_frequency_label",
            ),
            x="atwork_subtour_frequency_label",
            y="atwork_subtour_count",
            title="At-Work Sub-Tour Frequency",
            x_title="At-Work Sub-Tour Frequency",
            y_title="At-Work Sub-Tours",
            category_order=label_values,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.data.summaries(*self.required_summary_ids)
        if not all(summaries.values()):
            return [self.summary_only_unavailable_card()]
        stop_list = summaries["tour_stop_frequency_by_tour_purpose"]
        atwork_list = nonempty(summaries["atwork_subtour_frequency_distribution"])
        display_purpose, raw_purpose = self._selected_purpose()
        both_chart = self.render_direction_chart(
            stop_list,
            raw_purpose=raw_purpose,
            display_purpose=display_purpose,
            direction="Both",
        )
        outbound_chart = self.render_direction_chart(
            stop_list,
            raw_purpose=raw_purpose,
            display_purpose=display_purpose,
            direction="Outbound",
        )
        inbound_chart = self.render_direction_chart(
            stop_list,
            raw_purpose=raw_purpose,
            display_purpose=display_purpose,
            direction="Inbound",
        )
        directional_row = pn.Row(
            outbound_chart,
            inbound_chart,
            sizing_mode="stretch_width",
        )
        charts = [
            both_chart,
            directional_row,
        ]
        return [
            pn.pane.Markdown("### Tour Stop Frequency"),
            selector_row(self.purpose_sel),
            *charts,
            pn.pane.Markdown("### At-Work Sub-Tour Frequency"),
            self.render_atwork_chart(atwork_list),
        ]
