"""Demo page that intentionally uses disaggregate prepared trip records."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard import DashboardPage, dashboard_page
from dashboard.data_access import RunTables


def trip_mode_distribution(
    trip_tables: RunTables,
) -> RunTables:
    """Aggregate prepared trip records into one trip-mode distribution per run."""

    def _one_run(trips: pl.DataFrame) -> pl.DataFrame:
        if "trip_mode" not in trips.columns:
            return pl.DataFrame(
                {
                    "trip_mode": pl.Series(name="trip_mode", values=[], dtype=pl.Utf8),
                    "freq": pl.Series(name="freq", values=[], dtype=pl.Float64),
                }
            )

        agg_expr = (
            pl.col("finalweight").cast(pl.Float64).sum().alias("freq")
            if "finalweight" in trips.columns
            else pl.len().cast(pl.Float64).alias("freq")
        )
        return (
            trips.drop_nulls("trip_mode")
            .with_columns(pl.col("trip_mode").cast(pl.Utf8))
            .group_by("trip_mode")
            .agg(agg_expr)
            .sort("trip_mode")
        )

    return trip_tables.map(_one_run)


@dashboard_page(
    page_id="raw_trip_demo",
    title="Prepared Trip Demo",
    order=900,
    default_enabled=False,
    prepared_data_mode="required",
    required_prepared_tables=("trips",),
)
class RawTripDemoPage(DashboardPage):
    """Example page for future prepared-data pages to follow."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell around one prepared-data-backed section."""
        self._body = self.section(
            "raw_trip_demo_body",
            export_data_mode="required",
            render=self.render_body,
        )
        return self._body

    def render_body(self):
        """Render the prepared-run trip mode demo or an unavailable placeholder."""
        if not self.state.run_labels:
            return [self.no_runs_message()]
        note = self.section_note("raw_trip_demo.trip_modes", self._body)

        trip_tables = self.data.prepared(
            "trips",
            columns=("trip_mode",),
        )
        if not trip_tables:
            return [
                pn.pane.Markdown("## Prepared Trip Demo"),
                self.data_not_available_card(
                    detail=(
                        "This demo page intentionally requires disaggregate prepared trip "
                        "records and does not render from summary tables."
                    ),
                    missing_items=["trips"],
                ),
                note,
            ]

        trip_mode_list = self.query(lambda: trip_mode_distribution(trip_tables))
        return [
            pn.pane.Markdown("## Prepared Trip Demo"),
            pn.pane.Markdown(
                "This page demonstrates the opt-in prepared-data path by aggregating "
                "trip records directly from the loaded prepared runs."
            ),
            self.render_trip_mode_chart(trip_mode_list),
            note,
        ]

    def render_trip_mode_chart(
        self,
        trip_mode_list: list[tuple[str, pl.DataFrame]],
    ) -> pn.viewable.Viewable:
        """Render the prepared-run trip mode distribution."""
        return self.plot.bar(
            trip_mode_list,
            x="trip_mode",
            y="freq",
            title="Trip Mode Distribution From Raw Trips",
            x_title="Trip Mode",
            y_title="Trips",
        )
