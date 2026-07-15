"""Page composition for Mandatory Location Choice."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard.helpers.geography_helpers import *
from dashboard.page_base import SectionContent
from dashboard.rendering import data_table, selector_row
from dashboard.pages.long_term_choices._mandatory_location_choice_support import *


class MandatoryLocationCompositionMixin:
    def build_page(self) -> pn.viewable.Viewable:
        """Build the persistent selectors and stable section containers."""
        self._current_data: dict[str, object] = {}
        self._geo_level_raw_by_label: dict[str, str | None] = {
            ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
        }
        self._geography_raw_by_label: dict[str, str | None] = {
            ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE
        }
        self.geo_level_sel = self.select(
            "geography_level",
            GEOGRAPHY_TYPE_SELECTOR_LABEL,
            options=self._geography_level_options,
        )
        self.geography_sel = self.select(
            "geography",
            GEOGRAPHY_NAME_SELECTOR_LABEL,
            options=self._geography_options,
        )
        self.mandatory_distance_range = DistanceRangeControls.create(
            self,
            "mandatory_distance",
            max_options=capped_distance_max_options(),
            reset_label="Reset distance range",
        )
        geography = self.feature("geography_comparison")
        flows = self.feature("flows")
        distance = self.feature("distance")
        remote_work = self.feature("remote_work")
        self._remote_work_section = remote_work.section(
            "body",
            selectors=("geography_level", "geography"),
            render=self.render_remote_work_section,
        )
        self._distance_section = distance.section(
            "distribution",
            selectors=(
                "geography_level",
                "geography",
                *self.mandatory_distance_range.selector_ids,
            ),
            render=self.render_distance_distribution_section,
        )
        self._worker_section = flows.section(
            "body",
            selectors=("geography_level", "geography"),
            render=self.render_worker_geography_section,
        )
        self._mandatory_distance_table_section = geography.section(
            "body",
            selectors=("geography_level", "geography"),
            render=self.render_mandatory_distance_table_section,
        )

        return self.new_section(
            pn.pane.Markdown("## Mandatory Location Choice"),
            selector_row(self.geo_level_sel, self.geography_sel),
            self._remote_work_section,
            self._distance_section,
            self._worker_section,
            self._mandatory_distance_table_section,
        )
