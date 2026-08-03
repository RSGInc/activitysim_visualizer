"""Page composition for the VMT validation dashboard."""

from __future__ import annotations

import panel as pn

from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    ALL_GEOGRAPHY_TYPES_VALUE,
    GEOGRAPHY_NAME_SELECTOR_LABEL,
    GEOGRAPHY_TYPE_SELECTOR_LABEL,
)
from dashboard.rendering import selector_row

from . import *


class VmtPageCompositionMixin:
    def build_page(self) -> pn.viewable.Viewable:
        self.personal_vmt_geo_type_raw_by_label = {
            ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
        }
        self.personal_vmt_geo_raw_by_label = {"All Geographies": "All"}
        self.personal_vmt_mode_raw_by_label = {"All": "All"}
        self.non_motorized_vmt_geo_type_raw_by_label = {
            ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
        }
        self.non_motorized_vmt_geo_raw_by_label = {"All Geographies": "All"}
        self.non_motorized_vmt_mode_raw_by_label = {"All": "All"}
        self.demo_commercial_vehicle_type_raw_by_label = {"All": "All"}
        self.external_travel_trip_purpose_raw_by_label = {"All": "All"}
        self.personal_vmt_breakdown_sel = self.selector(
            "personal_auto_vmt_breakdown",
            widget=pn.widgets.Select(
                name="Breakdown",
                options=list(PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS),
                value="Time Period",
            ),
            label="Breakdown",
        )
        self.personal_vmt_geography_type_sel = self.selector(
            "personal_auto_vmt_geography_type",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_TYPE_SELECTOR_LABEL,
                options=[ALL_GEOGRAPHY_TYPES_LABEL],
                value=ALL_GEOGRAPHY_TYPES_LABEL,
            ),
            label=GEOGRAPHY_TYPE_SELECTOR_LABEL,
            options=self._personal_geography_type_options,
        )
        self.personal_vmt_geography_sel = self.selector(
            "personal_auto_vmt_geography",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_NAME_SELECTOR_LABEL,
                options=["All Geographies"],
                value="All Geographies",
            ),
            label=GEOGRAPHY_NAME_SELECTOR_LABEL,
            options=self._personal_geography_options,
        )
        self.personal_vmt_time_period_sel = self.selector(
            "personal_auto_vmt_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=["All"],
                value="All",
            ),
            label="Time Period",
            options=self._personal_time_period_options,
        )
        self.personal_vmt_mode_sel = self.selector(
            "personal_auto_vmt_mode",
            widget=pn.widgets.Select(
                name="Mode",
                options=["All"],
                value="All",
            ),
            label="Mode",
            options=self._personal_mode_options,
        )
        self.personal_vmt_income_segment_sel = self.selector(
            "personal_auto_vmt_income_segment",
            widget=pn.widgets.Select(
                name="Income Segment",
                options=["All"],
                value="All",
            ),
            label="Income Segment",
            options=self._personal_income_options,
        )
        self.personal_vmt_household_size_sel = self.selector(
            "personal_auto_vmt_household_size",
            widget=pn.widgets.Select(
                name="Household Size",
                options=["All"],
                value="All",
            ),
            label="Household Size",
            options=self._personal_household_size_options,
        )
        self.non_motorized_vmt_breakdown_sel = self.selector(
            "non_motorized_vmt_breakdown",
            widget=pn.widgets.Select(
                name="Breakdown",
                options=list(PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS),
                value="Time Period",
            ),
            label="Breakdown",
        )
        self.non_motorized_vmt_geography_type_sel = self.selector(
            "non_motorized_vmt_geography_type",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_TYPE_SELECTOR_LABEL,
                options=[ALL_GEOGRAPHY_TYPES_LABEL],
                value=ALL_GEOGRAPHY_TYPES_LABEL,
            ),
            label=GEOGRAPHY_TYPE_SELECTOR_LABEL,
            options=self._non_motorized_geography_type_options,
        )
        self.non_motorized_vmt_geography_sel = self.selector(
            "non_motorized_vmt_geography",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_NAME_SELECTOR_LABEL,
                options=["All Geographies"],
                value="All Geographies",
            ),
            label=GEOGRAPHY_NAME_SELECTOR_LABEL,
            options=self._non_motorized_geography_options,
        )
        self.non_motorized_vmt_time_period_sel = self.selector(
            "non_motorized_vmt_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=["All"],
                value="All",
            ),
            label="Time Period",
            options=self._non_motorized_time_period_options,
        )
        self.non_motorized_vmt_mode_sel = self.selector(
            "non_motorized_vmt_mode",
            widget=pn.widgets.Select(
                name="Mode",
                options=["All"],
                value="All",
            ),
            label="Mode",
            options=self._non_motorized_mode_options,
        )
        self.non_motorized_vmt_income_segment_sel = self.selector(
            "non_motorized_vmt_income_segment",
            widget=pn.widgets.Select(
                name="Income Segment",
                options=["All"],
                value="All",
            ),
            label="Income Segment",
            options=self._non_motorized_income_options,
        )
        self.non_motorized_vmt_household_size_sel = self.selector(
            "non_motorized_vmt_household_size",
            widget=pn.widgets.Select(
                name="Household Size",
                options=["All"],
                value="All",
            ),
            label="Household Size",
            options=self._non_motorized_household_size_options,
        )
        self.demo_commercial_metric_sel = self.selector(
            "demo_commercial_metric",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Metric",
                options=["Trips", "VMT"],
                value="Trips",
            ),
            label="Commercial Vehicle Metric",
        )
        self.demo_commercial_breakdown_sel = self.selector(
            "demo_commercial_breakdown",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Breakdown",
                options=EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS,
                value=EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS[0],
            ),
            label="Commercial Vehicle Breakdown",
        )
        self.demo_commercial_vehicle_type_sel = self.selector(
            "demo_commercial_vehicle_type",
            widget=pn.widgets.Select(
                name="Commercial Vehicle Type",
                options=["All"],
                value="All",
            ),
            label="Commercial Vehicle Type",
            options=self._commercial_vehicle_type_options,
        )
        self.demo_commercial_time_period_sel = self.selector(
            "demo_commercial_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=[EXTERNAL_COMMERCIAL_DAILY_PERIOD],
                value=EXTERNAL_COMMERCIAL_DAILY_PERIOD,
            ),
            label="Time Period",
            options=self._commercial_time_period_options,
        )
        self.external_travel_metric_sel = self.selector(
            "external_travel_metric",
            widget=pn.widgets.Select(
                name="External Travel Metric",
                options=["Trips", "VMT"],
                value="Trips",
            ),
            label="External Travel Metric",
        )
        self.external_travel_breakdown_sel = self.selector(
            "external_travel_breakdown",
            widget=pn.widgets.Select(
                name="External Travel Breakdown",
                options=EXTERNAL_TRAVEL_BREAKDOWN_OPTIONS,
                value=EXTERNAL_TRAVEL_BREAKDOWN_OPTIONS[0],
            ),
            label="External Travel Breakdown",
        )
        self.external_travel_trip_purpose_sel = self.selector(
            "external_travel_trip_purpose",
            widget=pn.widgets.Select(
                name="Trip Purpose",
                options=["All"],
                value="All",
            ),
            label="Trip Purpose",
            options=self._external_trip_purpose_options,
        )
        self.external_travel_time_period_sel = self.selector(
            "external_travel_time_period",
            widget=pn.widgets.Select(
                name="Time Period",
                options=[EXTERNAL_COMMERCIAL_DAILY_PERIOD],
                value=EXTERNAL_COMMERCIAL_DAILY_PERIOD,
            ),
            label="Time Period",
            options=self._external_time_period_options,
        )
        comparison = self.feature("comparison")
        personal_auto = self.feature("personal_auto")
        non_motorized = self.feature("non_motorized")
        commercial = self.feature("commercial")
        external = self.feature("external")
        bicycle = self.feature("bicycle")
        self._personal_vmt_body = personal_auto.section(
            "body",
            selectors=(
                "personal_auto_vmt_breakdown",
                "personal_auto_vmt_geography_type",
                "personal_auto_vmt_geography",
                "personal_auto_vmt_time_period",
                "personal_auto_vmt_mode",
                "personal_auto_vmt_income_segment",
                "personal_auto_vmt_household_size",
            ),
            render=self.render_personal_auto_vmt_section,
        )
        self._non_motorized_vmt_body = non_motorized.section(
            "body",
            selectors=(
                "non_motorized_vmt_breakdown",
                "non_motorized_vmt_geography_type",
                "non_motorized_vmt_geography",
                "non_motorized_vmt_time_period",
                "non_motorized_vmt_mode",
                "non_motorized_vmt_income_segment",
                "non_motorized_vmt_household_size",
            ),
            render=self.render_non_motorized_vmt_section,
        )
        self._body = commercial.section(
            "body",
            selectors=(
                "demo_commercial_metric",
                "demo_commercial_breakdown",
                "demo_commercial_vehicle_type",
                "demo_commercial_time_period",
            ),
            render=self.render_commercial_vmt_section,
        )
        self._external_vmt_body = external.section(
            "body",
            selectors=(
                "external_travel_metric",
                "external_travel_breakdown",
                "external_travel_trip_purpose",
                "external_travel_time_period",
            ),
            render=self.render_external_vmt_section,
        )
        self._bicycle_body = bicycle.section(
            "body",
            render=self.render_bicycle_section,
        )
        self._vmt_overview_body = comparison.section(
            "body",
            render=self.render_vmt_overview_section,
        )
        return self.new_section(
            pn.pane.Markdown("## VMT Validation"),
            pn.pane.Markdown("### VMT Overview"),
            self.noted_section("vmt.overview", self._vmt_overview_body),
            pn.pane.Markdown("### Personal Auto VMT"),
            selector_row(
                self.personal_vmt_breakdown_sel,
                self.personal_vmt_geography_type_sel,
                self.personal_vmt_geography_sel,
            ),
            selector_row(
                self.personal_vmt_time_period_sel,
                self.personal_vmt_mode_sel,
                self.personal_vmt_income_segment_sel,
                self.personal_vmt_household_size_sel,
            ),
            self._personal_vmt_body,
            self.section_note("vmt.personal_auto", self._personal_vmt_body),
            pn.pane.Markdown("### Non-Motorized VMT"),
            selector_row(
                self.non_motorized_vmt_breakdown_sel,
                self.non_motorized_vmt_geography_type_sel,
                self.non_motorized_vmt_geography_sel,
            ),
            selector_row(
                self.non_motorized_vmt_time_period_sel,
                self.non_motorized_vmt_mode_sel,
                self.non_motorized_vmt_income_segment_sel,
                self.non_motorized_vmt_household_size_sel,
            ),
            self._non_motorized_vmt_body,
            self.section_note("vmt.non_motorized", self._non_motorized_vmt_body),
            pn.pane.Markdown("### External VMT and Travel"),
            selector_row(
                self.external_travel_metric_sel,
                self.external_travel_breakdown_sel,
                self.external_travel_trip_purpose_sel,
                self.external_travel_time_period_sel,
            ),
            self._external_vmt_body,
            self.section_note("vmt.external_travel", self._external_vmt_body),
            pn.pane.Markdown("### Commercial VMT and Travel"),
            selector_row(
                self.demo_commercial_metric_sel,
                self.demo_commercial_breakdown_sel,
                self.demo_commercial_vehicle_type_sel,
                self.demo_commercial_time_period_sel,
            ),
            self._body,
            self.section_note("vmt.commercial_travel", self._body),
            pn.pane.Markdown("### Bicycle VMT"),
            self.noted_section("vmt.bicycle", self._bicycle_body),
            sizing_mode="stretch_width",
        )
