"""Demo page that intentionally uses disaggregate prepared trip records."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from processor.models import RunData


def trip_mode_distribution(
    prepared_runs: list[tuple[str, RunData]],
) -> list[tuple[str, pl.DataFrame]]:
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

    return [(label, _one_run(run.trips)) for label, run in prepared_runs]


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

        prepared_result = self.resolve_prepared_visualization(
            "raw_trip_demo_trip_modes",
            table_requirements={"trips": ("trip_mode",)},
        )
        if not prepared_result.has_usable_runs:
            return [
                pn.pane.Markdown("## Prepared Trip Demo"),
                self.unavailable_visualization(
                    prepared_result,
                    detail=(
                        "This demo page intentionally requires disaggregate prepared trip "
                        "records and does not render from summary tables."
                    ),
                ),
                note,
            ]

        prepared_runs = prepared_result.usable_by_input["trips"]
        trip_mode_list = self.get_filtered_view(
            "raw_trip_demo_trip_modes",
            self.weighting_key,
            tuple(label for label, _ in prepared_runs),
            factory=lambda: trip_mode_distribution(prepared_runs),
        )
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
        return bar_chart(
            trip_mode_list,
            x_col="trip_mode",
            y_col="freq",
            title="Trip Mode Distribution From Raw Trips",
            xaxis_title="Trip Mode",
            yaxis_title="Trips",
            as_percent=self.as_percent,
        )


PAGE = DashboardPageDefinition(
    page_id="raw_trip_demo",
    title="Prepared Trip Demo",
    order=900,
    default_enabled=False,
    prepared_data_mode="required",
    required_prepared_tables=("trips",),
    page_cls=RawTripDemoPage,
)

RawTripDemoPage.definition = PAGE
