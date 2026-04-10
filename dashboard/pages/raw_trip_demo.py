"""Demo page that intentionally uses disaggregate raw trip records."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config
from runtime.models import RunData


def trip_mode_distribution(
    raw_runs: list[tuple[str, RunData]],
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate raw trip records into one trip-mode distribution per run."""

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

    return [(label, _one_run(run.trips)) for label, run in raw_runs]


class RawTripDemoPage(DashboardPage):
    """Example page for future raw-data pages to follow."""

    def __init__(self, state, config: Config) -> None:
        super().__init__("Raw Trip Demo", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = self._body

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        raw_runs = self.require_raw_runs()
        if raw_runs is None:
            self._body.objects = [
                pn.pane.Markdown("## Raw Trip Demo"),
                self.data_not_available_card(
                    detail=(
                        "This demo page intentionally requires disaggregate raw trip "
                        "records and does not render from summary tables."
                    ),
                    missing_items=["raw_run_data"],
                ),
            ]
            return

        trip_mode_list = self.get_filtered_view(
            "raw_trip_demo_trip_modes",
            self.weighting_key,
            factory=lambda: trip_mode_distribution(raw_runs),
        )
        self._body.objects = [
            pn.pane.Markdown("## Raw Trip Demo"),
            pn.pane.Markdown(
                "This page demonstrates the opt-in raw-data path by aggregating "
                "trip records directly from the loaded runs."
            ),
            bar_chart(
                trip_mode_list,
                x_col="trip_mode",
                y_col="freq",
                title="Trip Mode Distribution From Raw Trips",
                xaxis_title="Trip Mode",
                yaxis_title="Trips",
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="raw_trip_demo",
    title="Raw Trip Demo",
    order=900,
    default_enabled=False,
    raw_data_mode="required",
    controller_cls=RawTripDemoPage,
)

RawTripDemoPage.definition = PAGE
