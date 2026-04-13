"""Stop location page built from canonical summary-table columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


def purpose_options(loc_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect purpose options from canonical stop-location summaries."""
    purposes_set = set()
    for _, df in loc_list:
        if len(df) > 0 and "purpose" in df.columns:
            purposes_set.update(df["purpose"].drop_nulls().cast(pl.Utf8).unique().to_list())
    return sorted(purposes_set) if purposes_set else []


def all_purpose_chart_data(
    loc_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Build the all-purpose stop-location comparison data."""
    return [
        (label, df.group_by("distbin").agg(pl.col("freq").sum()).sort("distbin"))
        for label, df in loc_list
    ]


def purpose_chart_data(
    loc_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-location comparison data for one purpose."""
    return [
        (
            label,
            df.filter(pl.col("purpose") == purpose).select(["distbin", "freq"]),
        )
        for label, df in loc_list
    ]


class StopLocationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Location", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = self._body

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        loc_list = self.require_summary("stop_location")
        if loc_list is None:
            self._body.objects = [
                pn.pane.Markdown("## Stop Location"),
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                ),
            ]
            return
        purp_opts = purpose_options(loc_list)

        charts = [
            density_chart(
                self.get_filtered_view(
                    "stop_location_all",
                    factory=lambda: all_purpose_chart_data(loc_list),
                ),
                "distbin",
                "freq",
                "Stop Out-of-Direction Distance - All Purposes",
                "Miles",
                normalize=False,
                as_percent=self.as_percent,
            )
        ]
        for purp in purp_opts:
            charts.append(
                density_chart(
                    self.get_filtered_view(
                        "stop_location",
                        purp,
                        factory=lambda purp=purp: purpose_chart_data(loc_list, purp),
                    ),
                    "distbin",
                    "freq",
                    f"Stop Out-of-Direction Distance - {purp}",
                    "Miles",
                    normalize=False,
                    as_percent=self.as_percent,
                )
            )

        self._body.objects = [pn.pane.Markdown("## Stop Location"), *charts]


PAGE = DashboardPageDefinition(
    page_id="stop_location",
    title="Stop Location",
    order=90,
    controller_cls=StopLocationPage,
    required_summary_ids=("stop_location",),
)

StopLocationPage.definition = PAGE
