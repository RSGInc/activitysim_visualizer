"""Park-and-ride location page."""

from __future__ import annotations

import panel as pn

from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageExportRegionDefinition
from runtime.config import Config


class ParkAndRideLocationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Park-and-Ride Location", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Park-and-Ride Location"),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        self._body.objects = [
            self.data_not_available_card(
                detail=(
                    "The park-and-ride location scatterplot page is registered, but the "
                    "backing summary is not implemented yet."
                ),
                missing_items=["park_and_ride_location_comparison"],
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="park_and_ride_location",
    title="Park-and-Ride Location",
    group_id="tour_summaries",
    child_id="park_and_ride_location",
    order=47,
    controller_cls=ParkAndRideLocationPage,
    export_regions=(
        PageExportRegionDefinition(
            region_id="park_and_ride_location_body",
            view_attr="_body",
        ),
    ),
)

ParkAndRideLocationPage.definition = PAGE
