"""Dynamic selector domains for VMT page features."""

from __future__ import annotations

from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    ALL_GEOGRAPHY_TYPES_VALUE,
    geography_name_options_for_type,
    geography_name_selector_label,
    geography_type_options,
)

from .contracts import (
    EXTERNAL_COMMERCIAL_DAILY_PERIOD,
    NON_MOTORIZED_VMT_SUMMARY_ID,
    PERSONAL_AUTO_VMT_SUMMARY_ID,
    PERSONAL_AUTO_VMT_TIME_ORDER,
)
from .segmented import (
    _selector_values,
    non_motorized_mode_options,
    personal_auto_mode_options,
)
from .wide_tod import (
    demo_commercial_filter_options,
    external_travel_filter_options,
)


class VmtSelectorDomainsMixin:
    """Supply dynamic option providers and the small remaining UI state sync."""

    def _personal_vmt_data(self):
        return self.data.summary(PERSONAL_AUTO_VMT_SUMMARY_ID, self.weighting_key)

    def _non_motorized_vmt_data(self):
        return self.data.summary(NON_MOTORIZED_VMT_SUMMARY_ID, self.weighting_key)

    def _personal_geography_type_options(self) -> list[str]:
        options, mapping = geography_type_options(
            self._personal_vmt_data(),
            config=self.config,
            include_all_types=True,
        )
        if not options:
            options = [ALL_GEOGRAPHY_TYPES_LABEL]
            mapping = {ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE}
        self.personal_vmt_geo_type_raw_by_label = mapping
        return options

    def _personal_geography_options(self) -> list[str]:
        geography_type = self.selected_personal_vmt_geography_type_raw()
        options, mapping = geography_name_options_for_type(
            geography_type,
            self._personal_vmt_data(),
            config=self.config,
        )
        if not options:
            options = ["All Geographies"]
            mapping = {"All Geographies": "All"}
        self.personal_vmt_geo_raw_by_label = mapping
        if hasattr(self, "personal_vmt_geography_sel"):
            self.personal_vmt_geography_sel.name = geography_name_selector_label(
                geography_type,
                config=self.config,
            )
        return options

    def _personal_time_period_options(self) -> list[str]:
        return _selector_values(
            self._personal_vmt_data(),
            "time_period",
            include_all=True,
            preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
        ) or ["All"]

    def _personal_mode_options(self) -> list[str]:
        options, mapping = personal_auto_mode_options(
            self._personal_vmt_data(),
            config=self.config,
        )
        if not options:
            options = ["All"]
            mapping = {"All": "All"}
        self.personal_vmt_mode_raw_by_label = mapping
        return options

    def _personal_income_options(self) -> list[str]:
        return _selector_values(
            self._personal_vmt_data(),
            "income_segment",
            include_all=True,
        ) or ["All"]

    def _personal_household_size_options(self) -> list[str]:
        return _selector_values(
            self._personal_vmt_data(),
            "household_size",
            include_all=True,
        ) or ["All"]

    def _non_motorized_geography_type_options(self) -> list[str]:
        options, mapping = geography_type_options(
            self._non_motorized_vmt_data(),
            config=self.config,
            include_all_types=True,
        )
        if not options:
            options = [ALL_GEOGRAPHY_TYPES_LABEL]
            mapping = {ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE}
        self.non_motorized_vmt_geo_type_raw_by_label = mapping
        return options

    def _non_motorized_geography_options(self) -> list[str]:
        geography_type = self.selected_non_motorized_vmt_geography_type_raw()
        options, mapping = geography_name_options_for_type(
            geography_type,
            self._non_motorized_vmt_data(),
            config=self.config,
        )
        if not options:
            options = ["All Geographies"]
            mapping = {"All Geographies": "All"}
        self.non_motorized_vmt_geo_raw_by_label = mapping
        if hasattr(self, "non_motorized_vmt_geography_sel"):
            self.non_motorized_vmt_geography_sel.name = geography_name_selector_label(
                geography_type,
                config=self.config,
            )
        return options

    def _non_motorized_time_period_options(self) -> list[str]:
        return _selector_values(
            self._non_motorized_vmt_data(),
            "time_period",
            include_all=True,
            preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
        ) or ["All"]

    def _non_motorized_mode_options(self) -> list[str]:
        options, mapping = non_motorized_mode_options(
            self._non_motorized_vmt_data(),
            config=self.config,
        )
        if not options:
            options = ["All"]
            mapping = {"All": "All"}
        self.non_motorized_vmt_mode_raw_by_label = mapping
        return options

    def _non_motorized_income_options(self) -> list[str]:
        return _selector_values(
            self._non_motorized_vmt_data(),
            "income_segment",
            include_all=True,
        ) or ["All"]

    def _non_motorized_household_size_options(self) -> list[str]:
        return _selector_values(
            self._non_motorized_vmt_data(),
            "household_size",
            include_all=True,
        ) or ["All"]

    def _commercial_data(self):
        summary_id = (
            "commercial_vehicle_vmt_validation_summary"
            if self.demo_commercial_metric_sel.value == "VMT"
            else "commercial_vehicle_validation_summary"
        )
        return self.data.summary(summary_id, self.weighting_key)

    def _commercial_domains(self):
        time_options, (vehicle_options, mapping) = demo_commercial_filter_options(
            self._commercial_data(),
            config=self.config,
        )
        self.demo_commercial_vehicle_type_raw_by_label = mapping
        return time_options or [EXTERNAL_COMMERCIAL_DAILY_PERIOD], vehicle_options or [
            "All"
        ]

    def _commercial_time_period_options(self) -> list[str]:
        return self._commercial_domains()[0]

    def _commercial_vehicle_type_options(self) -> list[str]:
        return self._commercial_domains()[1]

    def _external_data(self):
        summary_id = (
            "external_vmt_validation_summary"
            if self.external_travel_metric_sel.value == "VMT"
            else "external_trip_validation_summary"
        )
        return self.data.summary(summary_id, self.weighting_key)

    def _external_domains(self):
        time_options, (purpose_options, mapping) = external_travel_filter_options(
            self._external_data(),
            config=self.config,
        )
        self.external_travel_trip_purpose_raw_by_label = mapping
        return time_options or [EXTERNAL_COMMERCIAL_DAILY_PERIOD], purpose_options or [
            "All"
        ]

    def _external_time_period_options(self) -> list[str]:
        return self._external_domains()[0]

    def _external_trip_purpose_options(self) -> list[str]:
        return self._external_domains()[1]

    @staticmethod
    def _disable_breakdown_filter(breakdown: str, widgets: dict[str, object]) -> None:
        for widget in widgets.values():
            widget.disabled = False
        widget = widgets.get(breakdown)
        if widget is None:
            return
        if "All" in widget.options:
            widget.value = "All"
        elif widget.options:
            widget.value = widget.options[0]
        widget.disabled = True

    def sync_controls(self) -> None:
        """Apply only behavior that is not an option-domain concern."""
        self.personal_vmt_geography_type_sel.disabled = False
        self.personal_vmt_geography_sel.disabled = False
        self._disable_breakdown_filter(
            str(self.personal_vmt_breakdown_sel.value),
            {
                "Time Period": self.personal_vmt_time_period_sel,
                "Mode": self.personal_vmt_mode_sel,
                "Income Segment": self.personal_vmt_income_segment_sel,
                "Household Size": self.personal_vmt_household_size_sel,
            },
        )
        self.non_motorized_vmt_geography_type_sel.disabled = False
        self.non_motorized_vmt_geography_sel.disabled = False
        self._disable_breakdown_filter(
            str(self.non_motorized_vmt_breakdown_sel.value),
            {
                "Time Period": self.non_motorized_vmt_time_period_sel,
                "Mode": self.non_motorized_vmt_mode_sel,
                "Income Segment": self.non_motorized_vmt_income_segment_sel,
                "Household Size": self.non_motorized_vmt_household_size_sel,
            },
        )
        self._disable_breakdown_filter(
            str(self.demo_commercial_breakdown_sel.value),
            {
                "Time Period": self.demo_commercial_time_period_sel,
                "Commercial Vehicle Type": self.demo_commercial_vehicle_type_sel,
            },
        )
        self._disable_breakdown_filter(
            str(self.external_travel_breakdown_sel.value),
            {
                "Time Period": self.external_travel_time_period_sel,
                "Trip Purpose": self.external_travel_trip_purpose_sel,
            },
        )


__all__ = ["VmtSelectorDomainsMixin"]
