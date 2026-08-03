"""VMT validation page with personal auto, commercial, and bicycle VMT charts."""

from __future__ import annotations

from dashboard import DashboardPage, dashboard_page
from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    ALL_GEOGRAPHY_TYPES_VALUE,
)

from ._vmt import *  # Re-export the established VMT page helper surface.
from ._vmt.composition import VmtPageCompositionMixin
from ._vmt.features import (
    CommercialVmtFeatureMixin,
    ExternalVmtFeatureMixin,
    SegmentedVmtFeatureMixin,
    VmtOverviewFeatureMixin,
)
from ._vmt.selector_domains import VmtSelectorDomainsMixin


@dashboard_page(
    page_id="vmt",
    title="VMT Validation",
    group_id="validation",
    order=54,
    required_summary_ids=(
        PERSONAL_AUTO_VMT_SUMMARY_ID,
        NON_MOTORIZED_VMT_SUMMARY_ID,
        "bicycle_vmt_by_facility_type",
    ),
    optional_summary_ids=(
        "commercial_vehicle_validation_summary",
        "commercial_vehicle_vmt_validation_summary",
        "external_trip_validation_summary",
        "external_vmt_validation_summary",
    ),
)
class VMTValidationPage(
    VmtPageCompositionMixin,
    VmtOverviewFeatureMixin,
    SegmentedVmtFeatureMixin,
    CommercialVmtFeatureMixin,
    ExternalVmtFeatureMixin,
    VmtSelectorDomainsMixin,
    DashboardPage,
):
    def selected_personal_vmt_geography_type_raw(self) -> str:
        selected = str(self.personal_vmt_geography_type_sel.value)
        raw_value = self.personal_vmt_geo_type_raw_by_label.get(selected, selected)
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def selected_non_motorized_vmt_geography_type_raw(self) -> str:
        selected = str(self.non_motorized_vmt_geography_type_sel.value)
        raw_value = self.non_motorized_vmt_geo_type_raw_by_label.get(
            selected,
            selected,
        )
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def export_ignored_selectors(
        self,
        section_id: str,
        selected_values: dict[str, str],
    ) -> set[str]:
        section_prefix = {
            "personal_auto_vmt_body": "personal_auto_vmt",
            "non_motorized_vmt_body": "non_motorized_vmt",
        }.get(section_id)
        if section_prefix is None:
            return set()

        breakdown = selected_values.get(f"{section_prefix}_breakdown")
        if breakdown == "Home Geography":
            return {f"{section_prefix}_geography"}
        if breakdown:
            return {
                f"{section_prefix}_geography_type",
                f"{section_prefix}_geography",
            }
        return set()

    def export_canonical_selector_value(
        self,
        section_id: str,
        selector_id: str,
        value: str,
        selected_values: dict[str, str],
    ) -> str:
        section_prefix = {
            "personal_auto_vmt_body": "personal_auto_vmt",
            "non_motorized_vmt_body": "non_motorized_vmt",
        }.get(section_id)
        if (
            section_prefix is not None
            and selector_id == f"{section_prefix}_geography_type"
            and selected_values.get(f"{section_prefix}_breakdown") != "Home Geography"
        ):
            return ALL_GEOGRAPHY_TYPES_LABEL
        return value

    def selected_personal_vmt_geography_raw(self) -> str:
        selected = str(self.personal_vmt_geography_sel.value)
        raw_value = self.personal_vmt_geo_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_non_motorized_vmt_geography_raw(self) -> str:
        selected = str(self.non_motorized_vmt_geography_sel.value)
        raw_value = self.non_motorized_vmt_geo_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_personal_vmt_mode_raw(self) -> str:
        selected = str(self.personal_vmt_mode_sel.value)
        raw_value = self.personal_vmt_mode_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_non_motorized_vmt_mode_raw(self) -> str:
        selected = str(self.non_motorized_vmt_mode_sel.value)
        raw_value = self.non_motorized_vmt_mode_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)

    def selected_demo_commercial_vehicle_type_raw(self) -> str:
        selected = str(self.demo_commercial_vehicle_type_sel.value)
        raw_value = self.demo_commercial_vehicle_type_raw_by_label.get(
            selected,
            selected,
        )
        return "All" if raw_value is None else str(raw_value)

    def selected_external_travel_trip_purpose_raw(self) -> str:
        selected = str(self.external_travel_trip_purpose_sel.value)
        raw_value = self.external_travel_trip_purpose_raw_by_label.get(
            selected,
            selected,
        )
        return "All" if raw_value is None else str(raw_value)
