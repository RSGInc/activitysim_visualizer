"""Selector and summary domains for Escorted Tours."""

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


class EscortedToursDomainMixin:
    def _direction_options(self) -> list[str]:
        """Discover available direction values from the core school escort summary."""
        data = self.data.summary(
            "school_escorted_tours_by_escort_type_and_direction",
            "weighted",
        )
        if data is None:
            return ["Both Directions"]
        return direction_options(data)

    def _load_page_summaries(self):
        """Load core summaries plus optional add-on summaries used by static sections."""
        summaries = self.data.summaries(*CORE_SUMMARY_IDS)
        if not all(summaries.values()):
            return None
        optional_summaries = self.data.summaries(*OPTIONAL_SUMMARY_IDS, required=False)
        return {**summaries, **optional_summaries}

    def _feature_summaries(self):
        if not self.state.run_labels:
            return None, [self.no_runs_message()]
        summaries = self._load_page_summaries()
        if summaries is None:
            return None, [
                self.summary_only_unavailable_card(summary_ids=CORE_SUMMARY_IDS)
            ]
        return summaries, None
