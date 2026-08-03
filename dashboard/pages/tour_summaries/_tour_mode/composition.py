"""Page composition for Tour Mode."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    add_percent_of_total,
    column_options,
    common_column_options,
    category_label_matches,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.rendering import selector_row

from .contracts import *
from .transforms import *


class TourModeCompositionMixin:
    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell and persistent selectors."""
        self._purpose_to_raw: dict[str, str | None] = {}
        self.purpose_sel = self.select(
            "tour_purpose",
            "Tour Purpose",
            options=self._purpose_options,
        )
        self.hide_drive_alone = self.selector(
            "hide_drive_alone",
            widget=pn.widgets.Checkbox(name="Hide Auto Modes", value=False),
            label="Hide Auto Modes",
        )
        self.occupancy_sel = self.select(
            "vehicle_occupancy",
            "Vehicle Occupancy",
            options=self._occupancy_options,
        )
        self._mode_section = self.section(
            "tour_mode_modes",
            selectors=("tour_purpose", "hide_drive_alone"),
            render=self.render_modes_section,
        )
        self._vehicle_section = self.section(
            "tour_mode_vehicles",
            selectors=("vehicle_occupancy",),
            render=self.render_vehicle_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Mode"),
            pn.pane.Markdown(auto_sufficiency_definitions_markdown(self.config)),
            selector_row(self.purpose_sel, self.hide_drive_alone),
            self._mode_section,
            self._vehicle_section,
        )
