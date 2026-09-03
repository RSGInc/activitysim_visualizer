"""Geography, export, and data ownership for Mandatory Location Choice."""

from __future__ import annotations


from dashboard.helpers.geography_helpers import *
from dashboard.pages.long_term_choices._mandatory_location_choice_support import *


class MandatoryLocationDomainMixin:
    def on_global_state_changed(self) -> None:
        """Invalidate page-local caches when the dashboard's global state changes."""
        self.clear_query_cache()
        self._current_data = self._collect_data()

    def _geography_level_options(self) -> list[str]:
        """Return available geography levels and refresh their raw mapping."""
        if not self._current_data:
            self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self._geo_level_raw_by_label = self._current_data["geo_raw_by_label"]
        return geo_opts

    def _geography_options(self) -> list[str]:
        """Return names valid for the selected geography level."""
        if not self._current_data:
            self._current_data = self._collect_data()
        geography_opts_by_level = self._current_data["geography_opts_by_level"]
        selected_geo_level = self.selected_geography_level_raw()
        if self.state.export_mode:
            geography_opts, self._geography_raw_by_label = (
                export_geography_name_options(
                    geography_opts_by_level,
                    config=self.config,
                )
            )
        else:
            geography_opts, self._geography_raw_by_label = geography_opts_by_level.get(
                selected_geo_level,
                (
                    [ALL_WITHIN_LEVEL_VALUE],
                    {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                ),
            )
        if getattr(self, "geography_sel", None) is not None:
            self.geography_sel.name = geography_name_selector_label(
                selected_geo_level,
                config=self.config,
            )
        return geography_opts

    def selected_geography_level_raw(self) -> str:
        """Return the raw geography type value selected in the display selector."""
        selected = str(self.geo_level_sel.value)
        raw_value = self._geo_level_raw_by_label.get(selected, selected)
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def selected_geography_raw(self) -> str:
        """Return the raw geography name/id value selected in the display selector."""
        selected = str(self.geography_sel.value)
        raw_value = self._geography_raw_by_label.get(selected, selected)
        return ALL_WITHIN_LEVEL_VALUE if raw_value is None else str(raw_value)

    def export_canonical_selector_value(
        self,
        section_id: str,
        selector_id: str,
        value: str,
        selected_values: dict[str, str],
    ) -> str:
        if selector_id != "geography":
            return value

        selected_geo_level = selected_values.get("geography_level")
        raw_geo_level = self._geo_level_raw_by_label.get(
            str(selected_geo_level),
            selected_geo_level,
        )
        raw_geo_level = (
            ALL_GEOGRAPHY_TYPES_VALUE if raw_geo_level is None else str(raw_geo_level)
        )
        geography_opts_by_level = self._current_data.get("geography_opts_by_level", {})
        _, raw_by_label = geography_opts_by_level.get(
            raw_geo_level,
            (
                [ALL_WITHIN_LEVEL_VALUE],
                {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
            ),
        )
        raw_geography = self._geography_raw_by_label.get(value, value)
        raw_geography = (
            ALL_WITHIN_LEVEL_VALUE if raw_geography is None else str(raw_geography)
        )
        valid_values = {str(raw) for raw in raw_by_label.values() if raw is not None}
        if raw_geography in valid_values:
            return value
        return ALL_WITHIN_LEVEL_VALUE

    def export_selector_dependencies(self) -> dict[str, dict[str, object]]:
        """Describe the Geography Name selector's export-time dependency."""
        geography_opts_by_level = self._current_data.get("geography_opts_by_level", {})
        options_by_geography_type: dict[str, list[str]] = {}
        disabled_geography_types: list[str] = []

        for display_level, raw_level_value in self._geo_level_raw_by_label.items():
            raw_level = (
                ALL_GEOGRAPHY_TYPES_VALUE
                if raw_level_value is None
                else str(raw_level_value)
            )
            level_options, raw_by_label = geography_opts_by_level.get(
                raw_level,
                (
                    [ALL_WITHIN_LEVEL_VALUE],
                    {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                ),
            )
            export_options = [ALL_WITHIN_LEVEL_VALUE]
            for option in level_options:
                raw_value = raw_by_label.get(str(option), str(option))
                if raw_value is None:
                    continue
                raw_value_str = str(raw_value)
                if raw_value_str == ALL_WITHIN_LEVEL_VALUE or is_all_geographies(
                    raw_value_str
                ):
                    continue
                if str(option) not in export_options:
                    export_options.append(str(option))
            options_by_geography_type[str(display_level)] = export_options
            if raw_level == ALL_GEOGRAPHY_TYPES_VALUE:
                disabled_geography_types.append(str(display_level))

        return {
            "geography": {
                "parent_selector_id": "geography_level",
                "options_by_parent_value": options_by_geography_type,
                "disabled_parent_values": disabled_geography_types,
            }
        }

    def _selected_geography(self) -> tuple[str, str]:
        """Return the effective geography selection, honoring export-mode flattening."""
        geo_level = self.selected_geography_level_raw()
        geography = self.selected_geography_raw()
        if not self.state.export_mode:
            return geo_level, geography

        geography_opts_by_level = self._current_data.get("geography_opts_by_level", {})
        _, raw_by_label = geography_opts_by_level.get(
            geo_level,
            (
                [ALL_WITHIN_LEVEL_VALUE],
                {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
            ),
        )
        valid_options = {
            str(value) for value in raw_by_label.values() if value is not None
        }
        if geography in valid_options:
            return geo_level, geography
        return geo_level, ALL_WITHIN_LEVEL_VALUE

    def _collect_data(self) -> dict[str, object]:
        """Collect and normalize every summary used by the page."""
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": [ALL_GEOGRAPHY_TYPES_LABEL],
                "geo_raw_by_label": {
                    ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
                },
                "geography_opts_by_level": {
                    ALL_GEOGRAPHY_TYPES_VALUE: (
                        [ALL_WITHIN_LEVEL_VALUE],
                        {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                    )
                },
            }

        summaries = self.data.summaries(
            "internal_external_worker_by_geography",
            "external_worker_workplace_locations",
            "work_from_home_rate_by_geography",
            "telecommute_frequency_distribution",
            "work_location_distance_distribution_by_geography",
            "school_location_distance_distribution_by_geography",
            "university_location_distance_distribution_by_geography",
            "average_mandatory_tour_distance_by_purpose_and_geography",
        )

        if not any(summaries.values()):
            return {
                "mode": "unavailable",
                "geo_opts": [ALL_GEOGRAPHY_TYPES_LABEL],
                "geo_raw_by_label": {
                    ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
                },
                "geography_opts_by_level": {
                    ALL_GEOGRAPHY_TYPES_VALUE: (
                        [ALL_WITHIN_LEVEL_VALUE],
                        {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                    )
                },
            }

        internal_external = normalize_geography_data(
            summaries["internal_external_worker_by_geography"]
        )
        external_workplace = adapt_external_workplace(
            summaries["external_worker_workplace_locations"]
        )
        work_from_home = normalize_geography_data(
            summaries["work_from_home_rate_by_geography"]
        )
        telecommute = normalize_geography_data(
            summaries["telecommute_frequency_distribution"]
        )
        work_distance = normalize_geography_data(
            summaries["work_location_distance_distribution_by_geography"]
        )
        school_distance = normalize_geography_data(
            summaries["school_location_distance_distribution_by_geography"]
        )
        university_distance = normalize_geography_data(
            summaries["university_location_distance_distribution_by_geography"]
        )
        average_distance = normalize_geography_data(
            summaries["average_mandatory_tour_distance_by_purpose_and_geography"]
        )

        geo_opts, geo_raw_by_label = geography_type_options(
            internal_external or None,
            work_from_home or None,
            telecommute or None,
            work_distance or None,
            school_distance or None,
            university_distance or None,
            average_distance or None,
            config=self.config,
            include_all_types=True,
        )
        geography_option_sources = (
            internal_external or None,
            telecommute or None,
            work_distance or None,
            school_distance or None,
            university_distance or None,
            average_distance or None,
        )
        geography_opts_by_level = {
            str(raw_geo_level): geography_name_options_for_type(
                str(raw_geo_level),
                *geography_option_sources,
                config=self.config,
            )
            for raw_geo_level in geo_raw_by_label.values()
            if raw_geo_level is not None
        }
        return {
            "mode": "ready",
            "geo_opts": geo_opts,
            "geo_raw_by_label": geo_raw_by_label,
            "geography_opts_by_level": geography_opts_by_level,
            "internal_external": internal_external or None,
            "external_workplace": external_workplace or None,
            "work_from_home": work_from_home or None,
            "telecommute": telecommute or None,
            "work_distance": work_distance or None,
            "school_distance": school_distance or None,
            "university_distance": university_distance or None,
            "average_distance": average_distance or None,
        }
