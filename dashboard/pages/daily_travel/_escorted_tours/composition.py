"""Page composition for Escorted Tours."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
    ordered_category_values,
)
from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard.rendering import selector_row
from dashboard.pages.daily_travel._escorted_tours_data import *

from .contracts import *


class EscortedToursCompositionMixin:
    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell with one direction selector and two stable sections."""
        school_escort = self.feature("school_escort")
        adult_escort = self.feature("adult_escort")
        direction = self.feature("direction")
        distance = self.feature("distance")
        self.direction_sel = direction.select(
            "value",
            "Direction",
            options=self._direction_options,
            default=lambda options: default_direction_option(list(options)),
        )
        self.escort_distance_range = DistanceRangeControls.create(
            self,
            "escort_distance",
            max_options=capped_distance_max_options(),
            reset_label="Reset distance range",
        )
        self._school_escort_body = school_escort.section(
            "body",
            render=self.render_school_escort_feature,
        )
        self._adult_escort_body = adult_escort.section(
            "body",
            render=self.render_adult_escort_feature,
        )
        self._direction_body = direction.section(
            "body",
            selectors=("value",),
            render=self.render_direction_feature,
        )
        self._distance_body = distance.section(
            "body",
            selectors=(
                "direction.value",
                *self.escort_distance_range.selector_ids,
            ),
            render=self.render_distance_feature,
        )
        return self.new_section(
            pn.pane.Markdown("## Escorted Tours"),
            self._school_escort_body,
            self._adult_escort_body,
            self._direction_body,
            self._distance_body,
            sizing_mode="stretch_width",
        )
