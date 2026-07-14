"""Parking location page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard import DashboardPage, dashboard_page
from dashboard.rendering import data_table
from dashboard.data_access import RunTables

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
    land_use_tables: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    capacity_tables: list[tuple[str, pl.DataFrame]] = []
    for label, land_use in land_use_tables:
        capacity_col = _parking_capacity_col(land_use)
        if capacity_col is None:
            continue
        capacity_tables.append(
            (
                label,
                land_use.select(
                    pl.col("MAZ").cast(pl.Utf8).alias("geography_id"),
                    pl.col(capacity_col).cast(pl.Float64).alias("parking_capacity"),
                )
                .group_by("geography_id")
                .agg(parking_capacity=pl.col("parking_capacity").sum()),
            )
        )

    parking_counts = (
        RunTables.from_runs(parking_summary)
        .map(
            lambda frame: frame.filter(
                pl.col("geography_type").cast(pl.Utf8) == "maz"
            ).select(
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("trip_count").cast(pl.Float64),
            )
        )
    )
    return (
        RunTables.from_runs(capacity_tables)
        .join(parking_counts, on="geography_id", how="full", coalesce=True)
        .with_columns(
            pl.col("parking_capacity").fill_null(0.0),
            pl.col("trip_count").fill_null(0.0),
        )
        .sort("geography_id")
    )


@dashboard_page(
    page_id="parking_location",
    title="Parking Location",
    group_id="trip_summaries",
    order=51,
    default_enabled=False,
    prepared_data_mode="required",
    required_summary_ids=("parking_locations",),
    required_prepared_tables=("land_use",),
)
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
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        """Render the parking scatterplot plus the joined comparison table."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        parking_tables = self.data.summary(
            "parking_locations",
            columns=("geography_type", "geography_id", "trip_count"),
        )
        land_use_tables = self.data.prepared(
            "land_use",
            columns=("MAZ",),
            weighted=self.weighting_key == "weighted",
        )
        if not parking_tables or not land_use_tables:
            detail = (
                "Parking location scatterplots require parking trip summaries and prepared "
                "land use tables with parking capacity columns."
            )
            missing = []
            if not parking_tables:
                missing.append("parking_locations")
            if not land_use_tables:
                missing.append("land_use")
            return [self.data_not_available_card(detail=detail, missing_items=missing)]

        scatter_data = self.get_filtered_view(
            "parking_location_scatter",
            tuple(
                label
                for label, _ in parking_tables
            ),
            factory=lambda: parking_scatter_data(
                parking_tables,
                land_use_tables,
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
        return self.plot.scatter(
            scatter_data,
            x="parking_capacity",
            y="trip_count",
            title="Parking Capacity vs Trips Parked by Zone",
            x_title="Parking Capacity",
            y_title="Trips Parked",
            drop_zero_y=False,
        )

    def render_comparison_table(
        self,
        scatter_data: list[tuple[str, pl.DataFrame]],
    ) -> pn.viewable.Viewable:
        """Render the joined capacity/trips table below the chart."""
        return data_table(scatter_data, "Parking Capacity vs Trips Parked")
