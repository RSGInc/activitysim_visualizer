"""Selector domains for Tour Mode."""

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


class TourModeSelectorDomainsMixin:
    def _purpose_options(self) -> list[str]:
        """Return purposes available for the current weighting mode."""
        summaries = self.data.summary(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            self.weighting_key,
        )
        options, self._purpose_to_raw = column_options(
            summaries or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        return options or [self.TOTAL_PURPOSE_LABEL]

    def _occupancy_options(self) -> list[str]:
        """Return vehicle occupancies available for the current weighting mode."""
        age_summary = self.data.summary(
            "allocated_vehicle_age_by_occupancy",
            self.weighting_key,
        )
        fuel_summary = self.data.summary(
            "allocated_vehicle_fuel_type_by_occupancy",
            self.weighting_key,
        )
        body_summary = self.data.summary(
            "allocated_vehicle_body_type_by_occupancy",
            self.weighting_key,
        )
        options, _ = common_column_options(
            age_summary,
            fuel_summary,
            body_summary,
            column="occupancy",
            total_raw="All",
            total_label="All",
        )
        return options or ["All"]

    def _summaries(self):
        """Load every summary used by either page section."""
        return self.data.summaries(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            "allocated_vehicle_age_by_occupancy",
            "allocated_vehicle_fuel_type_by_occupancy",
            "allocated_vehicle_body_type_by_occupancy",
        )
