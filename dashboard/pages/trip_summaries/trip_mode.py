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


def _filtered_trip_mode_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    *,
    tour_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
            pl.col("trip_mode").cast(pl.Utf8),
        ).filter(pl.col("tour_purpose") == tour_purpose)
        if tour_mode is None:
            filtered = filtered.filter(pl.col("tour_mode") == "all_tour_modes")
        else:
            filtered = filtered.filter(pl.col("tour_mode") == tour_mode)
        out.append((label, filtered))
    return out


class TripModePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        trip_mode_data = self.state.get_summary_table_set(
            "trip_mode_by_tour_purpose_and_tour_mode",
            "weighted",
        )
        purpose_opts, self._tour_purpose_to_raw = column_options(
            trip_mode_data or [],
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
            total_label="All",
        )
        if not purpose_opts:
            purpose_opts = ["All"]
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
            "trip_summary_mode_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip Mode"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.tour_purpose_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        trip_mode_list = summaries["trip_mode_by_tour_purpose_and_tour_mode"]
        purpose_opts, self._tour_purpose_to_raw = column_options(
            trip_mode_list,
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
            total_label="All",
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

        trip_mode_list = summaries["trip_mode_by_tour_purpose_and_tour_mode"]
        tour_purpose = self.tour_purpose_sel.value
        raw_tour_purpose = self._tour_purpose_to_raw.get(
            tour_purpose, "all_tour_purposes"
        )
        trip_mode_x_values = ordered_category_values(
            trip_mode_list,
            "trip_mode",
            category_id="mode",
            config=self.config,
        )
        trip_mode_label_values = self.config.ordered_labels("mode", trip_mode_x_values)
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

        overall_data = self.get_filtered_view(
            "trip_mode_overall",
            raw_tour_purpose,
            factory=lambda: label_category_data(
                complete_category_counts(
                    _filtered_trip_mode_data(
                        trip_mode_list,
                        raw_tour_purpose,
                    ),
                    category_col="trip_mode",
                    category_values=trip_mode_x_values,
                    value_cols=("trip_count", "pct"),
                ),
                category_id="mode",
                config=self.config,
                source_col="trip_mode",
                target_col="trip_mode_label",
            ),
        )

        grid_cards: list[pn.viewable.Viewable] = []
        for tour_mode in tour_modes:
            mode_data = self.get_filtered_view(
                "trip_mode_grid",
                (raw_tour_purpose, tour_mode),
                factory=lambda tm=tour_mode: label_category_data(
                    complete_category_counts(
                        _filtered_trip_mode_data(
                            trip_mode_list,
                            raw_tour_purpose,
                            tour_mode=tm,
                        ),
                        category_col="trip_mode",
                        category_values=trip_mode_x_values,
                        value_cols=("trip_count", "pct"),
                    ),
                    category_id="mode",
                    config=self.config,
                    source_col="trip_mode",
                    target_col="trip_mode_label",
                ),
            )
            grid_cards.append(
                bar_chart(
                    mode_data,
                    x_col="trip_mode_label",
                    y_col="trip_count",
                    title=f"Trip Mode Distribution - {self.config.label_value('mode', tour_mode)}",
                    xaxis_title="Trip Mode",
                    yaxis_title="Trips",
                    pct_col="pct",
                    as_percent=self.as_percent,
                    height=320,
                    xaxis_categoryarray=trip_mode_label_values,
                )
            )

        grid_rows: list[pn.Row] = []
        for start in range(0, len(grid_cards), 2):
            grid_rows.append(
                pn.Row(*grid_cards[start : start + 2], sizing_mode="stretch_width")
            )

        return [
            bar_chart(
                overall_data,
                x_col="trip_mode_label",
                y_col="trip_count",
                title=f"Trip Mode Distribution - {tour_purpose}",
                xaxis_title="Trip Mode",
                yaxis_title="Trips",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=trip_mode_label_values,
            ),
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
