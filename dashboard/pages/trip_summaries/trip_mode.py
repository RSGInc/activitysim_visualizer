"""Trip mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, selector_row
from dashboard.helpers.category_helpers import (
    add_percent_of_total,
    category_label_matches,
    column_options,
    complete_category_counts,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

AUTO_MODE_LABELS = ("Drive Alone", "Shared Ride 2", "Shared Ride 3+")


def filtered_trip_mode_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    *,
    tour_mode: str | None = None,
    hidden_mode_values: set[str] | None = None,
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
        if hidden_mode_values:
            filtered = filtered.filter(~pl.col("trip_mode").is_in(sorted(hidden_mode_values)))
        out.append((label, filtered))
    return out


def trip_mode_percent_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    all_trip_mode_values: list[str],
    hidden_trip_mode_values: set[str],
) -> list[tuple[str, pl.DataFrame]]:
    """Complete trip-mode rows, compute full-denominator percents, then hide rows."""
    completed = complete_category_counts(
        data_list,
        category_col="trip_mode",
        category_values=all_trip_mode_values,
        value_cols=("trip_count", "pct"),
    )
    with_percent = add_percent_of_total(
        completed,
        value_col="trip_count",
        percent_col="trip_count_percent",
    )
    if not hidden_trip_mode_values:
        return with_percent
    hidden_values = sorted(hidden_trip_mode_values)
    return [
        (
            label,
            df.filter(~pl.col("trip_mode").is_in(hidden_values)),
        )
        for label, df in with_percent
    ]


class TripModePage(DashboardPage):
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def _tour_purpose_title_label(self, display_purpose: str) -> str:
        """Return a title-ready tour-purpose label."""
        if display_purpose == self.TOTAL_PURPOSE_LABEL:
            return "All Tours"
        purpose_label = str(display_purpose)
        if not purpose_label.casefold().endswith(" tours"):
            purpose_label = f"{purpose_label} Tours"
        return purpose_label

    def _overall_chart_title(self, display_purpose: str) -> str:
        """Return the overall trip-mode chart title."""
        return f"Trip Mode Distribution for {self._tour_purpose_title_label(display_purpose)}"

    def _tour_mode_chart_title(self, tour_mode: str, display_purpose: str) -> str:
        """Return the tour-mode-specific trip-mode chart title."""
        mode_label = self.config.label_value("mode", tour_mode)
        if display_purpose == self.TOTAL_PURPOSE_LABEL:
            return f"Trip Mode Distribution for All {mode_label} Tours"
        return (
            "Trip Mode Distribution for "
            f"{mode_label} {self._tour_purpose_title_label(display_purpose)}"
        )

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
        self.hide_drive_alone = self.selector(
            "hide_drive_alone",
            widget=pn.widgets.Checkbox(name="Hide Auto Modes", value=False),
            label="Hide Auto Modes",
        )
        self._body = self.section(
            "trip_summary_mode_body",
            selectors=("tour_purpose", "hide_drive_alone"),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Trip Mode"),
            self.section_note("trip_mode.distributions", self._body),
            selector_row(self.tour_purpose_sel, self.hide_drive_alone),
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
    ) -> tuple[list[str], list[str], list[str], list[str], set[str]]:
        all_trip_mode_values = ordered_category_values(
            trip_mode_list,
            "trip_mode",
            category_id="mode",
            config=self.config,
        )
        trip_mode_values = all_trip_mode_values.copy()
        hidden_trip_mode_values: set[str] = set()
        if self.hide_drive_alone.value:
            hidden_trip_mode_values = {
                value
                for value in all_trip_mode_values
                if any(
                    category_label_matches(self.config, "mode", value, label)
                    for label in AUTO_MODE_LABELS
                )
            }
            trip_mode_values = [
                value
                for value in trip_mode_values
                if value not in hidden_trip_mode_values
            ]
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
        return (
            all_trip_mode_values,
            trip_mode_values,
            trip_mode_labels,
            tour_modes,
            hidden_trip_mode_values,
        )

    def render_mode_chart(
        self,
        trip_mode_list: list[tuple[str, pl.DataFrame]],
        *,
        raw_purpose: str,
        all_trip_mode_values: list[str],
        trip_mode_values: list[str],
        trip_mode_label_values: list[str],
        hidden_trip_mode_values: set[str],
        display_purpose: str,
        tour_mode: str | None = None,
    ) -> pn.viewable.Viewable:
        cache_key = (
            "trip_mode_overall" if tour_mode is None else "trip_mode_grid",
            raw_purpose,
            tour_mode,
            tuple(trip_mode_values),
        )
        mode_data = self.get_filtered_view(
            *cache_key,
            factory=lambda: label_category_data(
                trip_mode_percent_data(
                    filtered_trip_mode_data(
                        trip_mode_list,
                        raw_purpose,
                        tour_mode=tour_mode,
                    ),
                    all_trip_mode_values=all_trip_mode_values,
                    hidden_trip_mode_values=hidden_trip_mode_values,
                ),
                category_id="mode",
                config=self.config,
                source_col="trip_mode",
                target_col="trip_mode_label",
            ),
        )
        chart_title = (
            self._tour_mode_chart_title(tour_mode, display_purpose)
            if tour_mode is not None
            else self._overall_chart_title(display_purpose)
        )
        return bar_chart(
            mode_data,
            x_col="trip_mode_label",
            y_col="trip_count",
            title=chart_title,
            xaxis_title="Trip Mode",
            yaxis_title="Trips",
            pct_col="pct",
            percent_y_col="trip_count_percent",
            as_percent=self.as_percent,
            height=320 if tour_mode is not None else 400,
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
        (
            all_trip_mode_values,
            trip_mode_values,
            trip_mode_label_values,
            tour_modes,
            hidden_trip_mode_values,
        ) = self._mode_axes(trip_mode_list)
        overall_chart = self.render_mode_chart(
            trip_mode_list,
            raw_purpose=raw_purpose,
            all_trip_mode_values=all_trip_mode_values,
            trip_mode_values=trip_mode_values,
            trip_mode_label_values=trip_mode_label_values,
            hidden_trip_mode_values=hidden_trip_mode_values,
            display_purpose=display_purpose,
        )
        grid_cards = [
            self.render_mode_chart(
                trip_mode_list,
                raw_purpose=raw_purpose,
                all_trip_mode_values=all_trip_mode_values,
                trip_mode_values=trip_mode_values,
                trip_mode_label_values=trip_mode_label_values,
                hidden_trip_mode_values=hidden_trip_mode_values,
                display_purpose=display_purpose,
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
