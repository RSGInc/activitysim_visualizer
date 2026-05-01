"""Park-and-ride location page."""

from __future__ import annotations

import panel as pn

from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


class ParkAndRideLocationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self._body = self.section(
            "park_and_ride_location_body",
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Park-and-Ride Location"),
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        return [
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
    order=47,
    page_cls=ParkAndRideLocationPage,
)

ParkAndRideLocationPage.definition = PAGE
