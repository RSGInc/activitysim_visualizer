"""Selector domains for Traffic Validation."""

from __future__ import annotations

from .transforms import demo_facility_options


class TrafficSelectorDomainsMixin:
    def _facility_options(self) -> list[str]:
        """Return facility labels and refresh their raw-value mapping."""
        demo_link_list = self.data.summary(
            "link_validation_summary", self.weighting_key
        )
        demo_count_list = self.data.summary(
            "count_location_counts_validation_summary", self.weighting_key
        )
        demo_volume_list = self.data.summary(
            "count_location_volumes_validation_summary", self.weighting_key
        )
        demo_scatter_list = self.data.summary(
            "count_location_scatter_validation_summary", self.weighting_key
        )
        demo_fit_list = self.data.summary(
            "count_location_fit_validation_summary", self.weighting_key
        )
        facility_opts, self.demo_facility_raw_by_label = demo_facility_options(
            demo_link_list,
            demo_count_list,
            demo_volume_list,
            demo_scatter_list,
            demo_fit_list,
            config=self.config,
        )
        return facility_opts

    def selected_facility_type_raw(self) -> str:
        selected = str(self.demo_facility_sel.value)
        raw_value = self.demo_facility_raw_by_label.get(selected, selected)
        return "All" if raw_value is None else str(raw_value)
