"""Feature rendering for Traffic Validation."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.helpers.category_helpers import label_category_data
from dashboard.rendering import data_table

from .contracts import *
from .transforms import *


class TrafficFeatureMixin:
    def render_screenline_flow_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        data = self.data.summary("screenline_flow_comparisons", self.weighting_key)
        if not data:
            return [
                self.data_not_available_card(
                    detail="Screenline flow comparisons are unavailable.",
                    missing_items=["screenline_flow_comparisons"],
                )
            ]
        period = str(self.screenline_period_sel.value)
        facility_type = self.selected_screenline_facility_type_raw()
        scatter_data = self.query(
            lambda: screenline_scatter_data(
                data,
                period=period,
                facility_type=facility_type,
            )
        )
        fit_data = self.query(lambda: screenline_fit_line_data(scatter_data))
        return [
            self.plot.scatter(
                scatter_data,
                x="observed_volume",
                y="modeled_volume",
                title=f"Screenline Observed vs Modeled - {period}",
                x_title="Observed Screenline Flow (vehicles)",
                y_title="Modeled Screenline Flow (vehicles)",
                fit_overlays=fit_data,
                one_to_one=True,
                legend_on_right=True,
                panel_aspect_ratio=1.0,
            )
        ]

    def render_demo_facility_summary_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return [self.no_runs_message()]

        count_list = self.data.summary(
            "count_location_counts_validation_summary", self.weighting_key
        )
        volume_list = self.data.summary(
            "count_location_volumes_validation_summary", self.weighting_key
        )
        scatter_list = self.data.summary(
            "count_location_scatter_validation_summary", self.weighting_key
        )
        fit_list = self.data.summary(
            "count_location_fit_validation_summary", self.weighting_key
        )
        if not any((count_list, volume_list, scatter_list, fit_list)):
            return [
                self.data_not_available_card(
                    detail="Count-location facility summaries are unavailable.",
                    missing_items=[
                        "count_location_counts_validation_summary",
                        "count_location_volumes_validation_summary",
                    ],
                )
            ]

        # Keep this overview on unfiltered daily totals. The controls below it
        # belong only to the Traffic Volume Summaries sections.
        period = "Day"
        volume_col = DEMO_TRAFFIC_TIME_PERIODS[str(period)]
        facility_type = "All"
        if scatter_list:
            scatter_data = self.query(
                lambda: demo_count_scatter_data(
                    scatter_list,
                    period=str(period),
                    facility_type=facility_type,
                )
            )
        elif count_list and volume_list:
            scatter_data = self.query(
                lambda: demo_count_scatter_data_from_sources(
                    count_list,
                    volume_list,
                    volume_col=volume_col,
                    facility_type=facility_type,
                )
            )
        else:
            return []

        if not scatter_data:
            return []
        facility_comparison = self.query(
            lambda: demo_facility_comparison_table(
                scatter_data,
                fit_list,
                period=str(period),
                facility_type=facility_type,
                config=self.config,
            )
        )
        if not facility_comparison:
            return []
        return [
            data_table(
                facility_comparison,
                title="Count Location Summary by Facility Type",
                numeric_precision_by_column={"RMSE": 3, "R²": 3},
                column_sorters={"n": "number", "RMSE": "number", "R²": "number"},
            )
        ]

    def render_demo_traffic_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return [self.no_runs_message()]

        count_list = self.data.summary(
            "count_location_counts_validation_summary", self.weighting_key
        )
        volume_list = self.data.summary(
            "count_location_volumes_validation_summary", self.weighting_key
        )
        scatter_list = self.data.summary(
            "count_location_scatter_validation_summary", self.weighting_key
        )
        fit_list = self.data.summary(
            "count_location_fit_validation_summary", self.weighting_key
        )
        period = self.demo_period_sel.value
        volume_col = DEMO_TRAFFIC_TIME_PERIODS[str(period)]
        facility_type = self.selected_facility_type_raw()
        section: list[pn.viewable.Viewable] = []
        if scatter_list:
            scatter_data = self.query(
                lambda: demo_count_scatter_data(
                    scatter_list,
                    period=str(period),
                    facility_type=facility_type,
                )
            )
            fit_data = self.query(
                lambda: demo_count_fit_line_data(
                    fit_list,
                    period=str(period),
                    facility_type=facility_type,
                )
            )
            section.append(
                self.plot.scatter(
                    scatter_data,
                    x="observed_volume",
                    y="modeled_volume",
                    title=f"Count Location Observed vs Modeled - {period}",
                    x_title="Observed Count (vehicles)",
                    y_title="Modeled Volume (vehicles)",
                    fit_overlays=fit_data,
                    one_to_one=True,
                    legend_on_right=True,
                    panel_aspect_ratio=1.0,
                )
            )
        elif count_list and volume_list:
            scatter_data = self.query(
                lambda: demo_count_scatter_data_from_sources(
                    count_list,
                    volume_list,
                    volume_col=volume_col,
                    facility_type=facility_type,
                )
            )
            section.append(
                self.plot.scatter(
                    scatter_data,
                    x="observed_volume",
                    y="modeled_volume",
                    title=f"Count Location Observed vs Modeled - {period}",
                    x_title="Observed Count (vehicles)",
                    y_title="Modeled Volume (vehicles)",
                    one_to_one=True,
                    legend_on_right=True,
                    panel_aspect_ratio=1.0,
                )
            )
        else:
            section.append(
                self.data_not_available_card(
                    detail=(
                        "Count-location validation counts and volumes are both "
                        "required for this scatter plot."
                    ),
                    missing_items=[
                        "count_location_counts_validation_summary",
                        "count_location_volumes_validation_summary",
                    ],
                )
            )
        return section

    def render_demo_link_volume_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return [self.no_runs_message()]

        link_list = self.data.summary("link_validation_summary", self.weighting_key)
        if not link_list:
            return [
                self.data_not_available_card(
                    detail="Link validation summaries are unavailable.",
                    missing_items=["link_validation_summary"],
                )
            ]

        period = self.demo_period_sel.value
        aggregate_data = self.query(
            lambda: demo_link_aggregate_data(
                link_list,
                volume_col=DEMO_TRAFFIC_TIME_PERIODS[str(period)],
                facility_type="All",
                config=self.config,
            )
        )
        return [
            self.plot.bar(
                aggregate_data,
                x="facility_type_label",
                y="volume",
                title=f"Link Volume by Facility Type - {period}",
                x_title="Facility Type",
                y_title="Volume",
                category_order=[
                    option
                    for option in self.demo_facility_sel.options
                    if option != "All"
                ],
                show_legend=True,
            )
        ]

    def render_demo_top_count_section(self) -> list[pn.viewable.Viewable]:
        if not self.state.run_labels:
            return [self.no_runs_message()]

        link_list = self.data.summary("link_validation_summary", self.weighting_key)
        count_list = self.data.summary(
            "count_location_counts_validation_summary", self.weighting_key
        )
        volume_list = self.data.summary(
            "count_location_volumes_validation_summary", self.weighting_key
        )
        facility_type = self.selected_facility_type_raw()
        top_period = self.demo_top_period_sel.value
        top_volume_col = DEMO_TRAFFIC_TIME_PERIODS[str(top_period)]
        top_n = int(self.demo_top_n_sel.value)

        if count_list and volume_list:
            volume_comparison = self.query(
                lambda: label_category_data(
                    demo_volume_comparison_table(
                        count_list,
                        volume_list,
                        link_list=link_list,
                        volume_col=top_volume_col,
                        facility_type=facility_type,
                        top_n=top_n,
                    ),
                    source_col="facility_type",
                    category_id=FACILITY_TYPE_CATEGORY_ID,
                    config=self.config,
                    target_col="facility_type",
                )
            )
            return [
                pn.pane.Markdown(
                    "#### Observed vs Modeled Volumes - "
                    f"{top_period} (Top {top_n} by Modeled Volume)"
                ),
                data_table(
                    volume_comparison,
                    column_sorters={"Difference": "number"},
                ),
            ]
        return [
            self.data_not_available_card(
                detail=(
                    "Count-location validation counts and volumes are both "
                    "required for this comparison table."
                ),
                missing_items=[
                    "count_location_counts_validation_summary",
                    "count_location_volumes_validation_summary",
                ],
            )
        ]
