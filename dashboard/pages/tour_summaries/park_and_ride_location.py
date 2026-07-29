"""Park-and-ride residual comparison page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import data_table, selector_row
from dashboard.helpers.comparison_helpers import format_percent_error_table
from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    GEOGRAPHY_TYPE_SELECTOR_LABEL,
    filter_geography_level,
    geography_type_options,
    is_all_geographies,
    normalize_geography_level_value,
    normalize_geography_data,
    with_display_geography_columns,
)
from dashboard import DashboardPage, dashboard_page
from dashboard.page_base import SectionContent


@dashboard_page(
    page_id="park_and_ride_location",
    title="Park-and-Ride Location",
    group_id="tour_summaries",
    order=47,
    required_summary_ids=(
        "park_and_ride_location_residuals",
        "park_and_ride_location_residual_histogram",
    ),
)
class ParkAndRideLocationPage(DashboardPage):
    """Show residual histograms and tables for park-and-ride locations."""

    def _maz_tables_disabled(self) -> bool:
        """Return whether MAZ-level tables should be hidden by configuration."""
        return (
            self.selected_geography_level_raw().lower() == "maz"
            and not self.config.enable_maz_geographies
        )

    def _all_geographies_distribution_card(self) -> pn.Card:
        """Explain why the aggregate residual cannot be shown as a distribution."""
        return self.data_not_available_card(
            title="Park-and-Ride Residual Distribution Unavailable",
            detail=(
                'The residual for "All Geographies" is a point mass that cannot be '
                "plotted as a distribution. Please refer to the table below for "
                'the park-and-ride values for "All Geographies".'
            ),
        )

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell and stable plot/table sections."""
        self._current_data: dict[str, object] = {}
        self._geo_level_raw_by_label: dict[str, str | None] = {
            ALL_GEOGRAPHY_TYPES_LABEL: "all_geographies"
        }
        self.geo_level_sel = self.select(
            "geography_level",
            GEOGRAPHY_TYPE_SELECTOR_LABEL,
            options=self._geography_options,
        )
        self._plot_section = self.section(
            "pnr_plot",
            selectors=("geography_level",),
            render=self.render_plot_section,
        )
        self._table_section = self.section(
            "pnr_table",
            selectors=("geography_level",),
            render=self.render_table_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Park-and-Ride Location"),
            pn.pane.Markdown("### Residual Distribution"),
            self.noted_section("park_and_ride.residual_plot", self._plot_section),
            pn.pane.Markdown("### Residual Details"),
            self.noted_section("park_and_ride.residual_table", self._table_section),
            sizing_mode="stretch_width",
        )

    def _geography_options(self) -> list[str]:
        """Refresh page data and return available geography levels."""
        self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self._geo_level_raw_by_label = self._current_data["geo_raw_by_label"]
        return geo_opts

    def selected_geography_level_raw(self) -> str:
        """Return the raw geography type selected in the display selector."""
        selected = str(self.geo_level_sel.value)
        raw_value = self._geo_level_raw_by_label.get(selected, selected)
        return (
            "all_geographies"
            if raw_value is None
            else normalize_geography_level_value(str(raw_value))
        )

    def _collect_data(self) -> dict[str, object]:
        """Collect and normalize park-and-ride summaries."""
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": [ALL_GEOGRAPHY_TYPES_LABEL],
                "geo_raw_by_label": {ALL_GEOGRAPHY_TYPES_LABEL: "all_geographies"},
            }

        residuals = normalize_geography_data(
            self.data.summary("park_and_ride_location_residuals", required=False)
        )
        histogram = normalize_geography_data(
            self.data.summary(
                "park_and_ride_location_residual_histogram", required=False
            )
        )
        geo_opts, geo_raw_by_label = geography_type_options(
            histogram or residuals,
            config=self.config,
            include_all_types=False,
            include_disabled_maz=True,
        )
        return {
            "mode": "ready",
            "geo_opts": geo_opts or [ALL_GEOGRAPHY_TYPES_LABEL],
            "geo_raw_by_label": geo_raw_by_label
            or {ALL_GEOGRAPHY_TYPES_LABEL: "all_geographies"},
            "residuals": residuals or None,
            "histogram": histogram or None,
        }

    def render_plot_section(self) -> SectionContent:
        """Render the residual histogram for the selected geography level."""
        if self._current_data["mode"] == "no_runs":
            return [self.no_runs_message()]

        histogram = self._current_data["histogram"]
        if histogram is None:
            return [
                self.data_not_available_card(
                    detail="The park-and-ride residual histogram summary is unavailable.",
                    missing_items=["park_and_ride_location_residual_histogram"],
                )
            ]

        geo_level = self.selected_geography_level_raw()
        if is_all_geographies(geo_level):
            return [
                selector_row(self.geo_level_sel),
                self._all_geographies_distribution_card(),
            ]

        filtered = self.query(lambda: filter_geography_level(histogram, geo_level))
        return [
            selector_row(self.geo_level_sel),
            self.plot.density(
                filtered,
                x="bin_start",
                y="geography_count",
                title="Park-and-Ride Residual Distribution",
                x_title="Residual (Modeled - Capacity)",
                y_title="Geographies",
            ),
        ]

    def render_table_section(self) -> SectionContent:
        """Render the residual table for the selected geography level."""
        if self._current_data["mode"] != "ready":
            return []

        residuals = self._current_data["residuals"]
        if residuals is None:
            return []
        if self._maz_tables_disabled():
            return [
                self.data_not_available_card(
                    title="Park-and-Ride Residuals by Geography",
                    detail="MAZ-level park-and-ride tables are hidden when visualizer.enable_maz_geographies is false.",
                )
            ]

        geo_level = self.selected_geography_level_raw()
        filtered = self.query(lambda: filter_geography_level(residuals, geo_level))
        return [
            data_table(
                [
                    (
                        label,
                        self.render_residual_table(df),
                    )
                    for label, df in filtered
                ],
                "Park-and-Ride Residuals by Geography",
            )
        ]

    def render_residual_table(self, df: pl.DataFrame) -> pl.DataFrame:
        """Select and format the table columns shared by every run."""
        display_df = with_display_geography_columns(df, config=self.config)
        columns = [
            column
            for column in (
                "Geography Type",
                "Geography Name",
                "pnr_tour_count",
                "pnr_lot_capacity",
                "residual_count",
                "absolute_residual_count",
                "percent_error",
            )
            if column in display_df.columns
        ]
        return format_percent_error_table(display_df.select(columns))
