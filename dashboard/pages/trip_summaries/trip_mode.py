"""Trip mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import (
    column_options,
    complete_category_counts,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def filtered_trip_mode_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    *,
    tour_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter trip mode summaries to one selected tour purpose and optional tour mode."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
            pl.col("trip_mode").cast(pl.Utf8),
        ).filter(pl.col("tour_purpose") == tour_purpose)
        filtered = (
            filtered.filter(pl.col("tour_mode") == "all_tour_modes")
            if tour_mode is None
            else filtered.filter(pl.col("tour_mode") == tour_mode)
        )
        out.append((label, filtered))
    return out


class TripModePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        purpose_opts, self._tour_purpose_to_raw = column_options(
            self.state.get_summary_table_set(
                "trip_mode_by_tour_purpose_and_tour_mode", "weighted"
            )
            or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_mode",
                "trip_mode_by_tour_purpose_and_tour_mode",
                "tour_purpose",
                "weighted",
            ),
            total_raw="all_tour_purposes",
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
            "trip_summary_mode_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip Mode"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.tour_purpose_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        purpose_opts, self._tour_purpose_to_raw = column_options(
            summaries["trip_mode_by_tour_purpose_and_tour_mode"],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "trip_mode",
                "trip_mode_by_tour_purpose_and_tour_mode",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        self.tour_purpose_sel.options = purpose_opts or [self.TOTAL_PURPOSE_LABEL]
        if self.tour_purpose_sel.value not in self.tour_purpose_sel.options:
            self.tour_purpose_sel.value = self.tour_purpose_sel.options[0]

    def _selected_purpose(self) -> tuple[str, str]:
        display_purpose = self.tour_purpose_sel.value
        raw_purpose = self._tour_purpose_to_raw.get(display_purpose, "all_tour_purposes")
        return display_purpose, str(raw_purpose)

    def _mode_axes(
        self,
        trip_mode_list: list[tuple[str, pl.DataFrame]],
    ) -> tuple[list[str], list[str], list[str]]:
        trip_mode_values = ordered_category_values(
            trip_mode_list,
            "trip_mode",
            category_id="mode",
            config=self.config,
        )
        tour_modes = [
            value
            for value in ordered_category_values(
                trip_mode_list,
                "tour_mode",
                category_id="mode",
                config=self.config,
            )
            if value != "all_tour_modes"
        ]
        trip_mode_labels = self.config.ordered_labels("mode", trip_mode_values)
        return trip_mode_values, trip_mode_labels, tour_modes

    def render_mode_chart(
        self,
        trip_mode_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_purpose: str,
        trip_mode_values: list[str],
        trip_mode_label_values: list[str],
        tour_mode: str | None = None,
    ) -> pn.viewable.Viewable:
        cache_key = (
            "trip_mode_overall" if tour_mode is None else "trip_mode_grid",
            raw_purpose,
            tour_mode,
        )
        mode_data = self.get_filtered_view(
            *cache_key,
            factory=lambda: label_category_data(
                complete_category_counts(
                    filtered_trip_mode_data(
                        trip_mode_list,
                        raw_purpose,
                        tour_mode=tour_mode,
                    ),
                    category_col="trip_mode",
                    category_values=trip_mode_values,
                    value_cols=("trip_count", "pct"),
                ),
                category_id="mode",
                config=self.config,
                source_col="trip_mode",
                target_col="trip_mode_label",
            ),
        )
        chart_title = (
            f"Trip Mode Distribution - {self.config.label_value('mode', tour_mode)}"
            if tour_mode is not None
            else f"Trip Mode Distribution - {self.tour_purpose_sel.value}"
        )
        return bar_chart(
            mode_data,
            x_col="trip_mode_label",
            y_col="trip_count",
            title=chart_title,
            xaxis_title="Trip Mode",
            yaxis_title="Trips",
            pct_col="pct",
            as_percent=self.as_percent,
            height=320 if tour_mode is not None else None,
            xaxis_categoryarray=trip_mode_label_values,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [self.summary_only_unavailable_card()]
        trip_mode_list = summaries["trip_mode_by_tour_purpose_and_tour_mode"]
        display_purpose, raw_purpose = self._selected_purpose()
        trip_mode_values, trip_mode_label_values, tour_modes = self._mode_axes(trip_mode_list)
        overall_chart = self.render_mode_chart(
            trip_mode_list,
            raw_purpose=raw_purpose,
            trip_mode_values=trip_mode_values,
            trip_mode_label_values=trip_mode_label_values,
        )
        grid_cards = [
            self.render_mode_chart(
                trip_mode_list,
                raw_purpose=raw_purpose,
                trip_mode_values=trip_mode_values,
                trip_mode_label_values=trip_mode_label_values,
                tour_mode=tour_mode,
            )
            for tour_mode in tour_modes
        ]
        grid_rows = [
            pn.Row(*grid_cards[start : start + 2], sizing_mode="stretch_width")
            for start in range(0, len(grid_cards), 2)
        ]
        return [
            overall_chart,
            pn.pane.Markdown("### Trip Mode by Tour Mode"),
            *grid_rows,
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_mode",
    title="Trip Mode",
    group_id="trip_summaries",
    order=48,
    page_cls=TripModePage,
    required_summary_ids=("trip_mode_by_tour_purpose_and_tour_mode",),
)

TripModePage.definition = PAGE
