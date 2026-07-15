"""Feature rendering for Tour Mode."""

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


class TourModeFeatureMixin:
    def render_modes_section(self):
        """Render the tour mode charts by auto sufficiency."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._summaries()
        mode_summary = summaries["tour_mode_by_tour_purpose_and_auto_sufficiency"]
        selected_purpose = str(self.purpose_sel.value)
        raw_purpose = self._purpose_to_raw.get(selected_purpose, "all_tour_purposes")
        if not mode_summary:
            return [
                pn.pane.Markdown("### Tour Mode"),
                self.data_not_available_card(
                    detail="The tour mode summary is unavailable.",
                    missing_items=["tour_mode_by_tour_purpose_and_auto_sufficiency"],
                ),
            ]

        mode_values = [
            value
            for value in ordered_category_values(
                mode_summary,
                "tour_mode",
                category_id="mode",
                config=self.config,
            )
            if value != "all_tour_modes"
        ]
        hidden_mode_values: set[str] = set()
        if self.hide_drive_alone.value:
            hidden_mode_values = {
                value
                for value in mode_values
                if any(
                    category_label_matches(self.config, "mode", value, label)
                    for label in AUTO_MODE_LABELS
                )
            }
            mode_values = [
                value for value in mode_values if value not in hidden_mode_values
            ]
        return [
            pn.pane.Markdown("### Tour Mode"),
            *[
                self.render_tour_mode_chart(
                    mode_summary,
                    str(raw_purpose),
                    selected_purpose,
                    auto_sufficiency,
                    mode_values,
                    hidden_mode_values,
                )
                for auto_sufficiency in AUTO_SUFFICIENCY_LEVELS
            ],
        ]

    def render_tour_mode_chart(
        self,
        summary_data,
        raw_purpose: str,
        display_purpose: str,
        auto_sufficiency: str,
        mode_values: list[str],
        hidden_mode_values: set[str],
    ) -> pn.viewable.Viewable:
        """Render one auto-sufficiency slice of the selected tour purpose."""
        mode_data = self.query(
            lambda: tour_mode_chart_data(
                summary_data,
                raw_purpose,
                auto_sufficiency,
                hidden_mode_values,
            )
        )
        labeled = label_category_data(
            mode_data,
            source_col="tour_mode",
            category_id="mode",
            config=self.config,
            target_col="tour_mode_label",
        )
        return self.plot.bar(
            labeled,
            x="tour_mode_label",
            y="tour_count",
            title=(
                "Tour Mode - "
                f"{auto_sufficiency_display_label(auto_sufficiency, self.config)}"
            ),
            x_title="Tour Mode",
            y_title="Tours",
            share_y="tour_count_percent",
            category_order=self.config.ordered_labels("mode", mode_values),
        )

    def render_vehicle_section(self):
        """Render the three allocated vehicle characteristic charts."""
        summaries = self._summaries()
        occupancy = str(self.occupancy_sel.value)
        return [
            pn.pane.Markdown("### Allocated Vehicle Characteristics"),
            selector_row(self.occupancy_sel),
            pn.Row(
                self.render_vehicle_age_chart(
                    summaries["allocated_vehicle_age_by_occupancy"],
                    occupancy,
                ),
                self.render_vehicle_fuel_chart(
                    summaries["allocated_vehicle_fuel_type_by_occupancy"],
                    occupancy,
                ),
                self.render_vehicle_body_chart(
                    summaries["allocated_vehicle_body_type_by_occupancy"],
                    occupancy,
                ),
            ),
        ]

    def render_vehicle_age_chart(
        self, summary_data, occupancy: str
    ) -> pn.viewable.Viewable:
        """Render allocated vehicle age by occupancy level."""
        if not summary_data:
            return self.data_not_available_card(
                detail="The allocated vehicle age summary is unavailable.",
                missing_items=["allocated_vehicle_age_by_occupancy"],
            )
        age_values = self.ordered_vehicle_values(summary_data, "age")
        chart_data = self.query(
            lambda: vehicle_attribute_data(
                summary_data,
                occupancy,
                category="age",
            )
        )
        return self.plot.bar(
            chart_data,
            x="age",
            y="vehicle_count",
            title="Allocated Vehicle Age by Occupancy Level",
            x_title="Vehicle Age",
            y_title="Allocated Vehicles",
            category_order=age_values,
        )

    def render_vehicle_fuel_chart(
        self, summary_data, occupancy: str
    ) -> pn.viewable.Viewable:
        """Render allocated vehicle fuel type by occupancy level."""
        if not summary_data:
            return self.data_not_available_card(
                detail="The allocated vehicle fuel summary is unavailable.",
                missing_items=["allocated_vehicle_fuel_type_by_occupancy"],
            )
        fuel_values = self.ordered_vehicle_values(summary_data, "fuel_type")
        chart_data = self.query(
            lambda: vehicle_attribute_data(
                summary_data,
                occupancy,
                category="fuel_type",
            )
        )
        return self.plot.bar(
            chart_data,
            x="fuel_type",
            y="vehicle_count",
            title="Allocated Vehicle Fuel Type by Occupancy Level",
            x_title="Vehicle Fuel Type",
            y_title="Allocated Vehicles",
            category_order=fuel_values,
        )

    def render_vehicle_body_chart(
        self, summary_data, occupancy: str
    ) -> pn.viewable.Viewable:
        """Render allocated vehicle body type by occupancy level."""
        if not summary_data:
            return self.data_not_available_card(
                detail="The allocated vehicle body summary is unavailable.",
                missing_items=["allocated_vehicle_body_type_by_occupancy"],
            )
        body_values = self.ordered_vehicle_values(summary_data, "body_type")
        chart_data = self.query(
            lambda: vehicle_attribute_data(
                summary_data,
                occupancy,
                category="body_type",
            )
        )
        return self.plot.bar(
            chart_data,
            x="body_type",
            y="vehicle_count",
            title="Allocated Vehicle Body Type by Occupancy Level",
            x_title="Vehicle Body Type",
            y_title="Allocated Vehicles",
            category_order=body_values,
        )

    def ordered_vehicle_values(
        self,
        summary_data: list[tuple[str, pl.DataFrame]],
        column: str,
    ) -> list[str]:
        """Return a stable x-axis order for vehicle attributes."""
        values = {
            str(value)
            for _, df in nonempty(summary_data)
            for value in (
                df[column].cast(pl.Utf8).to_list() if column in df.columns else []
            )
        }
        if column == "age":
            return sorted(
                values,
                key=lambda value: (
                    999 if value == "20+" else int(value) if value.isdigit() else 1000
                ),
            )
        return sorted(values)
