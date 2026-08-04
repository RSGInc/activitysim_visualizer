"""User-visible feature rendering for the VMT validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.helpers.category_helpers import label_category_data, nonempty
from dashboard.rendering import data_table

from .contracts import *
from .overview import vmt_overview_table_data
from .segmented import (
    _chart_category_order,
    _ordered_values,
    non_motorized_vmt_chart_data,
    personal_auto_vmt_chart_data,
)
from .wide_tod import (
    demo_commercial_vehicle_chart_data,
    external_travel_chart_data,
)


class VmtOverviewFeatureMixin:
    def render_vmt_overview_section(self) -> list[pn.viewable.Viewable]:
        overview_data = vmt_overview_table_data(
            personal_auto_vmt=self.data.summary(
                PERSONAL_AUTO_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
            non_motorized_vmt=self.data.summary(
                NON_MOTORIZED_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
            external_vmt=self.data.summary(
                EXTERNAL_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
            commercial_vmt=self.data.summary(
                COMMERCIAL_VMT_SUMMARY_ID,
                self.weighting_key,
            ),
        )
        if not overview_data:
            return [
                self.data_not_available_card(
                    detail="VMT overview summaries are unavailable.",
                    missing_items=[
                        PERSONAL_AUTO_VMT_SUMMARY_ID,
                        NON_MOTORIZED_VMT_SUMMARY_ID,
                        EXTERNAL_VMT_SUMMARY_ID,
                        COMMERCIAL_VMT_SUMMARY_ID,
                    ],
                )
            ]
        return [
            data_table(
                overview_data,
                height=180,
                numeric_precision_by_column={
                    "VMT": 2,
                    "% Share of Total": 4,
                },
                column_sorters={
                    "VMT": "number",
                    "% Share of Total": "number",
                },
            )
        ]

    def render_bicycle_chart(self) -> pn.viewable.Viewable:
        bicycle_vmt = self.data.summary(
            "bicycle_vmt_by_facility_type",
            self.weighting_key,
        )
        if not bicycle_vmt:
            return self.data_not_available_card(
                detail="Bicycle VMT summaries are unavailable.",
                missing_items=["bicycle_vmt_by_facility_type"],
            )
        return self.plot.bar(
            nonempty(bicycle_vmt),
            x="facility_type",
            y="bicycle_vmt",
            title="Bicycle VMT by Facility Type",
            x_title="Bicycle Facility Type",
            y_title="Bicycle VMT",
        )

    def render_bicycle_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        return [self.render_bicycle_chart()]


class SegmentedVmtFeatureMixin:
    def render_personal_auto_vmt_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return []
        personal_vmt = self.data.summary(
            PERSONAL_AUTO_VMT_SUMMARY_ID,
            columns=PERSONAL_AUTO_VMT_REQUIRED_COLUMNS,
        )
        if not personal_vmt:
            return [
                self.data_not_available_card(
                    detail="Personal auto VMT by home geography, income segment, household size, and time period is unavailable.",
                    missing_items=[PERSONAL_AUTO_VMT_SUMMARY_ID],
                )
            ]
        breakdown = str(self.personal_vmt_breakdown_sel.value)
        geography_type = self.selected_personal_vmt_geography_type_raw()
        geography_id = self.selected_personal_vmt_geography_raw()
        time_period = str(self.personal_vmt_time_period_sel.value)
        mode = self.selected_personal_vmt_mode_raw()
        income_segment = str(self.personal_vmt_income_segment_sel.value)
        household_size = str(self.personal_vmt_household_size_sel.value)
        mode_values = [
            value
            for _, df in personal_vmt
            if "mode" in df.columns
            for value in df["mode"].drop_nulls().cast(pl.Utf8).to_list()
        ]
        mode_order = self.config.ordered_values(
            PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
            list(dict.fromkeys(mode_values)),
        )
        chart_data = self.query(
            lambda: personal_auto_vmt_chart_data(
                personal_vmt,
                breakdown=breakdown,
                geography_type=geography_type,
                geography_id=geography_id,
                time_period=time_period,
                mode=mode,
                income_segment=income_segment,
                household_size=household_size,
                mode_order=mode_order,
            )
        )
        if breakdown == "Mode":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        elif breakdown == "Home Geography":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id="geography",
                config=self.config,
                target_col="category",
            )
        category_values = [
            value
            for _, df in chart_data
            for value in (
                df["category"].to_list()
                if "category" in df.columns and not df.is_empty()
                else []
            )
        ]
        if breakdown == "Time Period":
            xaxis_categoryarray = _ordered_values(
                list(dict.fromkeys(str(value) for value in category_values)),
                preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
            )
        elif breakdown == "Mode":
            xaxis_categoryarray = [
                self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                for value in mode_order
                if self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                in {str(category) for category in category_values}
            ]
        else:
            xaxis_categoryarray = list(
                dict.fromkeys(str(value) for value in category_values)
            )
        use_time_period_percent = self.as_percent and breakdown == "Time Period"
        chart = self.plot.bar(
            chart_data,
            x="category",
            y="auto_vmt_percent" if use_time_period_percent else "auto_vmt",
            title=f"Personal Auto VMT by {breakdown}",
            x_title=PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES[breakdown],
            y_title=(
                "Percent of Vehicle Miles Traveled (%)"
                if use_time_period_percent
                else "Vehicle Miles Traveled"
            ),
            value_mode="count" if use_time_period_percent else "dashboard",
            category_order=xaxis_categoryarray,
        )
        return [chart]

    def render_non_motorized_vmt_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return []
        non_motorized_vmt = self.data.summary(
            NON_MOTORIZED_VMT_SUMMARY_ID,
            columns=NON_MOTORIZED_VMT_REQUIRED_COLUMNS,
        )
        if not non_motorized_vmt:
            return [
                self.data_not_available_card(
                    detail="Non-motorized VMT by home geography, income segment, household size, and time period is unavailable.",
                    missing_items=[NON_MOTORIZED_VMT_SUMMARY_ID],
                )
            ]
        breakdown = str(self.non_motorized_vmt_breakdown_sel.value)
        geography_type = self.selected_non_motorized_vmt_geography_type_raw()
        geography_id = self.selected_non_motorized_vmt_geography_raw()
        time_period = str(self.non_motorized_vmt_time_period_sel.value)
        mode = self.selected_non_motorized_vmt_mode_raw()
        income_segment = str(self.non_motorized_vmt_income_segment_sel.value)
        household_size = str(self.non_motorized_vmt_household_size_sel.value)
        mode_values = [
            value
            for _, df in non_motorized_vmt
            if "mode" in df.columns
            for value in df["mode"].drop_nulls().cast(pl.Utf8).to_list()
        ]
        mode_order = self.config.ordered_values(
            PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
            list(dict.fromkeys(mode_values)),
        )
        chart_data = self.query(
            lambda: non_motorized_vmt_chart_data(
                non_motorized_vmt,
                breakdown=breakdown,
                geography_type=geography_type,
                geography_id=geography_id,
                time_period=time_period,
                mode=mode,
                income_segment=income_segment,
                household_size=household_size,
                mode_order=mode_order or NON_MOTORIZED_VMT_MODE_ORDER,
            )
        )
        if breakdown == "Mode":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=PERSONAL_AUTO_VMT_MODE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        elif breakdown == "Home Geography":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id="geography",
                config=self.config,
                target_col="category",
            )
        category_values = [
            value
            for _, df in chart_data
            for value in (
                df["category"].to_list()
                if "category" in df.columns and not df.is_empty()
                else []
            )
        ]
        if breakdown == "Time Period":
            xaxis_categoryarray = _ordered_values(
                list(dict.fromkeys(str(value) for value in category_values)),
                preferred=PERSONAL_AUTO_VMT_TIME_ORDER,
            )
        elif breakdown == "Mode":
            xaxis_categoryarray = [
                self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                for value in mode_order
                if self.config.label_value(PERSONAL_AUTO_VMT_MODE_CATEGORY_ID, value)
                in {str(category) for category in category_values}
            ]
        else:
            xaxis_categoryarray = list(
                dict.fromkeys(str(value) for value in category_values)
            )
        use_time_period_percent = self.as_percent and breakdown == "Time Period"
        chart = self.plot.bar(
            chart_data,
            x="category",
            y=(
                "non_motorized_vmt_percent"
                if use_time_period_percent
                else "non_motorized_vmt"
            ),
            title=f"Non-Motorized VMT by {breakdown}",
            x_title=PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES[breakdown],
            y_title=(
                "Percent of Non-Motorized Miles Traveled (%)"
                if use_time_period_percent
                else "Non-Motorized Miles Traveled"
            ),
            value_mode="count" if use_time_period_percent else "dashboard",
            category_order=xaxis_categoryarray,
        )
        return [chart]


class CommercialVmtFeatureMixin:
    def render_body(self):
        return self.render_commercial_vmt_section()

    def render_commercial_vmt_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        return [self.render_demo_commercial_chart()]

    def render_demo_commercial_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "commercial_vehicle_vmt_validation_summary"
            if self.demo_commercial_metric_sel.value == "VMT"
            else "commercial_vehicle_validation_summary"
        )
        data = self.data.summary(summary_id, self.weighting_key)
        if not data:
            return self.data_not_available_card(
                detail="Commercial vehicle summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.demo_commercial_metric_sel.value
        breakdown = str(self.demo_commercial_breakdown_sel.value)
        time_period = str(self.demo_commercial_time_period_sel.value)
        commercial_vehicle_type = self.selected_demo_commercial_vehicle_type_raw()
        chart_data = self.query(
            lambda: demo_commercial_vehicle_chart_data(
                data,
                breakdown=breakdown,
                time_period=time_period,
                commercial_vehicle_type=commercial_vehicle_type,
                tod_col="tod",
                value_columns=EXTERNAL_COMMERCIAL_COLUMNS,
            )
        )
        if breakdown == "Commercial Vehicle Type":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        xaxis_categoryarray = (
            _chart_category_order(chart_data, preferred=EXTERNAL_COMMERCIAL_TIME_ORDER)
            if breakdown == "Time Period"
            else _chart_category_order(
                chart_data,
                preferred=self.config.ordered_labels(
                    COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID,
                    EXTERNAL_COMMERCIAL_COLUMNS,
                ),
            )
        )
        return self.plot.bar(
            chart_data,
            x="category",
            y=(
                "value_percent"
                if self.as_percent and breakdown == "Time Period"
                else "value"
            ),
            title=f"Commercial Vehicle {metric} by {breakdown}",
            x_title=breakdown,
            y_title=(
                f"Percent of {metric} (%)"
                if self.as_percent and breakdown == "Time Period"
                else metric
            ),
            value_mode="count" if breakdown == "Time Period" else "dashboard",
            category_order=xaxis_categoryarray,
            show_legend=True,
        )


class ExternalVmtFeatureMixin:
    def render_external_travel_chart(self) -> pn.viewable.Viewable:
        summary_id = (
            "external_vmt_validation_summary"
            if self.external_travel_metric_sel.value == "VMT"
            else "external_trip_validation_summary"
        )
        data = self.data.summary(summary_id, self.weighting_key)
        if not data:
            return self.data_not_available_card(
                detail="External travel summaries are unavailable.",
                missing_items=[summary_id],
            )
        metric = self.external_travel_metric_sel.value
        breakdown = str(self.external_travel_breakdown_sel.value)
        time_period = str(self.external_travel_time_period_sel.value)
        trip_purpose = self.selected_external_travel_trip_purpose_raw()
        chart_data = self.query(
            lambda: external_travel_chart_data(
                data,
                breakdown=breakdown,
                time_period=time_period,
                trip_purpose=trip_purpose,
                tod_col="tod",
                value_columns=EXTERNAL_TRAVEL_COLUMNS,
            )
        )
        if breakdown == "Trip Purpose":
            chart_data = label_category_data(
                chart_data,
                source_col="category",
                category_id=EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
                config=self.config,
                target_col="category",
            )
        xaxis_categoryarray = (
            _chart_category_order(chart_data, preferred=EXTERNAL_COMMERCIAL_TIME_ORDER)
            if breakdown == "Time Period"
            else _chart_category_order(
                chart_data,
                preferred=self.config.ordered_labels(
                    EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID,
                    EXTERNAL_TRAVEL_COLUMNS,
                ),
            )
        )
        return self.plot.bar(
            chart_data,
            x="category",
            y=(
                "value_percent"
                if self.as_percent and breakdown == "Time Period"
                else "value"
            ),
            title=f"External {metric} by {breakdown}",
            x_title=breakdown,
            y_title=(
                f"Percent of {metric} (%)"
                if self.as_percent and breakdown == "Time Period"
                else metric
            ),
            value_mode="count" if breakdown == "Time Period" else "dashboard",
            category_order=xaxis_categoryarray,
            show_legend=True,
        )

    def render_external_vmt_section(self) -> list[pn.viewable.Viewable]:
        content: list[pn.viewable.Viewable] = [
            self.render_external_travel_chart(),
        ]
        return content


__all__ = [
    "CommercialVmtFeatureMixin",
    "ExternalVmtFeatureMixin",
    "SegmentedVmtFeatureMixin",
    "VmtOverviewFeatureMixin",
]
