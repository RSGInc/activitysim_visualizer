"""Park-and-ride residual comparison page."""

from __future__ import annotations

import math

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart
from dashboard.helpers.geography_helpers import detail_geography_levels
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    if data_list is None:
        return []
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    col: str,
    *,
    config: Config | None = None,
    total_label: str = "All",
    include_all_geographies: bool = False,
) -> list[str]:
    first_df = next((df for _, df in _nonempty(data_list) if col in df.columns), None)
    if first_df is None:
        return [total_label]
    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    if config is not None and col == "geography_type":
        if include_all_geographies:
            detail_vals = sorted(v for v in vals if v != "all_geographies")
            return (
                ["all_geographies"] + detail_vals
                if "all_geographies" in vals
                else detail_vals or [total_label]
            )
        vals = detail_geography_levels(vals, config=config)
        return vals or [total_label]
    vals = sorted(v for v in vals if v != total_label)
    return [total_label] + vals


def _filter_col(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    col: str,
    value: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if col in df.columns and value != "All":
            df = df.with_columns(pl.col(col).cast(pl.Utf8)).filter(pl.col(col) == value)
        out.append((label, df))
    return out


def _format_percent_error_table(df: pl.DataFrame) -> pl.DataFrame:
    if "percent_error" not in df.columns:
        return df
    return df.with_columns(
        pl.col("percent_error")
        .map_elements(
            lambda value: (
                ""
                if value is None
                or (isinstance(value, float) and not math.isfinite(value))
                else f"{float(value):.2f}%"
            ),
            return_dtype=pl.Utf8,
        )
        .alias("percent_error")
    )


class ParkAndRideLocationPage(DashboardPage):
    def _maz_tables_disabled(self) -> bool:
        return str(self.geo_level_sel.value).lower() == "maz" and not self.config.enable_maz_geographies

    def _all_geographies_distribution_card(self) -> pn.Card:
        return self.data_not_available_card(
            title="Park-and-Ride Residual Distribution Unavailable",
            detail=(
                'The residual for "All Geographies" is a point mass that cannot be plotted '
                'as a distribution. Please refer to the table below for the park-and-ride '
                'values for "All Geographies".'
            ),
        )

    def build_page(self) -> pn.viewable.Viewable:
        self._current_data: dict[str, object] = {}
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=["all_geographies"],
                value="all_geographies",
            ),
            label="Geography Level",
        )
        self._plot_section = self.section(
            "pnr_plot",
            selectors=("geography_level",),
            render=self.render_plot,
        )
        self._table_section = self.section(
            "pnr_table",
            selectors=("geography_level",),
            render=self.render_table,
        )
        return self.new_section(
            pn.pane.Markdown("## Park-and-Ride Location"),
            self._plot_section,
            self._table_section,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

    def _collect_data(self) -> dict[str, object]:
        if not self.state.run_labels:
            return {"mode": "no_runs", "geo_opts": ["all_geographies"]}
        residuals = self.optional_summary("park_and_ride_location_residuals")
        histogram = self.optional_summary("park_and_ride_location_residual_histogram")
        return {
            "mode": "ready",
            "geo_opts": _options(
                histogram or residuals or [],
                "geography_type",
                config=self.config,
                total_label="all_geographies",
                include_all_geographies=True,
            ),
            "residuals": residuals,
            "histogram": histogram,
        }

    def render_plot(self) -> SectionContent:
        if self._current_data["mode"] == "no_runs":
            return [pn.pane.Markdown("No runs loaded.")]
        histogram = self._current_data["histogram"]
        if histogram is None:
            return [
                self.data_not_available_card(
                    detail="The park-and-ride residual histogram summary is unavailable.",
                    missing_items=["park_and_ride_location_residual_histogram"],
                )
            ]
        geo_level = str(self.geo_level_sel.value)
        if geo_level == "all_geographies":
            return [
                pn.Row(
                    pn.pane.Markdown("**Geography Level:**"),
                    self.geo_level_sel,
                ),
                self._all_geographies_distribution_card(),
            ]
        filtered = self.get_filtered_view(
            "pnr_residual_histogram",
            geo_level,
            factory=lambda: _filter_col(histogram, "geography_type", geo_level),
        )
        return [
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            density_chart(
                filtered,
                x_col="bin_start",
                y_col="geography_count",
                title="Park-and-Ride Residual Distribution",
                xaxis_title="Residual (Modeled - Capacity)",
                yaxis_title="Geographies",
                normalize=False,
                as_percent=self.as_percent,
            ),
        ]

    def render_table(self) -> SectionContent:
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
        geo_level = str(self.geo_level_sel.value)
        filtered = self.get_filtered_view(
            "pnr_residuals",
            geo_level,
            factory=lambda: _filter_col(residuals, "geography_type", geo_level),
        )
        return [
            data_table(
                [
                    (
                        label,
                        _format_percent_error_table(
                            df.select(
                                [
                                    "geography_id",
                                    "pnr_tour_count",
                                    "pnr_lot_capacity",
                                    "residual_count",
                                    "absolute_residual_count",
                                    "percent_error",
                                ]
                            )
                        ),
                    )
                    for label, df in filtered
                ],
                "Park-and-Ride Residuals by Geography",
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="park_and_ride_location",
    title="Park-and-Ride Location",
    group_id="tour_summaries",
    order=47,
    page_cls=ParkAndRideLocationPage,
    required_summary_ids=(
        "park_and_ride_location_residuals",
        "park_and_ride_location_residual_histogram",
    ),
)

ParkAndRideLocationPage.definition = PAGE
