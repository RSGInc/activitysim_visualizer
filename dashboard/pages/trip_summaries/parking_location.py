"""Parking location page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, scatter_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from processor.models import RunData

PARKING_CAPACITY_COLUMNS = (
    "PRKSPACES",
    "parking_spaces",
    "parking_capacity",
    "PARKING_SPACES",
)


def _parking_capacity_col(land_use: pl.DataFrame) -> str | None:
    for column in PARKING_CAPACITY_COLUMNS:
        if column in land_use.columns:
            return column
    return None


def parking_scatter_data(
    parking_summary: list[tuple[str, pl.DataFrame]],
    prepared_runs: list[tuple[str, RunData]],
) -> list[tuple[str, pl.DataFrame]]:
    prepared_by_label = {label: run for label, run in prepared_runs}
    out: list[tuple[str, pl.DataFrame]] = []
    for label, summary_df in parking_summary:
        run = prepared_by_label.get(label)
        if run is None:
            continue
        capacity_col = _parking_capacity_col(run.land_use)
        if capacity_col is None:
            continue
        land_use = (
            run.land_use.select(
                pl.col("MAZ").cast(pl.Utf8).alias("geography_id"),
                pl.col(capacity_col).cast(pl.Float64).alias("parking_capacity"),
            )
            .group_by("geography_id")
            .agg(parking_capacity=pl.col("parking_capacity").sum())
        )
        parking_counts = summary_df.filter(
            pl.col("geography_type").cast(pl.Utf8) == "maz"
        ).select(
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
        joined = (
            land_use.join(parking_counts, on="geography_id", how="full", coalesce=True)
            .with_columns(
                pl.col("parking_capacity").fill_null(0.0),
                pl.col("trip_count").fill_null(0.0),
            )
            .sort("geography_id")
        )
        out.append((label, joined))
    return out


class ParkingLocationPage(DashboardPage):
    """Join parking summaries with prepared land-use capacity data."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page around one exportable body section."""
        self._body = self.section(
            "parking_location_body",
            export_data_mode="required",
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Parking Location"),
            self.noted_section("parking_location.comparison", self._body),
            sizing_mode="stretch_width",
        )

    def render_body(self):
        """Render the parking scatterplot plus the joined comparison table."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        parking_result = self.resolve_summary_visualization(
            "parking_location_scatter",
            summary_requirements={
                "parking_locations": ("geography_type", "geography_id", "trip_count")
            },
        )
        prepared_result = self.resolve_prepared_visualization(
            "parking_location_land_use",
            table_requirements={"land_use": ("MAZ",)},
            weighted=self.weighting_key == "weighted",
        )
        if not parking_result.has_usable_runs or not prepared_result.has_usable_runs:
            detail = (
                "Parking location scatterplots require parking trip summaries and prepared "
                "land use tables with parking capacity columns."
            )
            result = (
                parking_result
                if not parking_result.has_usable_runs
                else prepared_result
            )
            return [self.unavailable_visualization(result, detail=detail)]

        scatter_data = self.get_filtered_view(
            "parking_location_scatter",
            tuple(
                label
                for label, _ in parking_result.usable_by_input["parking_locations"]
            ),
            factory=lambda: parking_scatter_data(
                parking_result.usable_by_input["parking_locations"],
                prepared_result.usable_by_input["land_use"],
            ),
        )
        if not scatter_data:
            return [
                self.data_not_available_card(
                    detail=(
                        "Prepared land use tables do not expose a recognized parking "
                        "capacity column for this run set."
                    ),
                    missing_items=list(PARKING_CAPACITY_COLUMNS),
                )
            ]

        return [
            self.render_scatter_chart(scatter_data),
            self.render_comparison_table(scatter_data),
        ]

    def render_scatter_chart(
        self,
        scatter_data: list[tuple[str, pl.DataFrame]],
    ) -> pn.viewable.Viewable:
        """Render the parking capacity versus trips scatterplot."""
        return scatter_chart(
            scatter_data,
            x_col="parking_capacity",
            y_col="trip_count",
            title="Parking Capacity vs Trips Parked by Zone",
            xaxis_title="Parking Capacity",
            yaxis_title="Trips Parked",
            drop_zero_y=False,
        )

    def render_comparison_table(
        self,
        scatter_data: list[tuple[str, pl.DataFrame]],
    ) -> pn.viewable.Viewable:
        """Render the joined capacity/trips table below the chart."""
        return data_table(scatter_data, "Parking Capacity vs Trips Parked")


PAGE = DashboardPageDefinition(
    page_id="parking_location",
    title="Parking Location",
    group_id="trip_summaries",
    order=51,
    default_enabled=False,
    page_cls=ParkingLocationPage,
    prepared_data_mode="required",
    required_summary_ids=("parking_locations",),
    required_prepared_tables=("land_use",),
)

ParkingLocationPage.definition = PAGE
