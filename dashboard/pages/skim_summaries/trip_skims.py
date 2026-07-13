"""Trip skim summaries page."""

from __future__ import annotations

import panel as pn

from dashboard.components import control_row, data_table, density_chart
from dashboard import DashboardPage, dashboard_page
from dashboard.pages.skim_summaries._shared import (
    ALL_RECORDS_SCENARIO,
    CHOSEN_MODE_SCENARIO,
    TRIP_STATS_SUMMARY_ID,
    component_options,
    distribution_bins,
    distribution_data_bounds,
    family_stats_table,
    mode_options,
    skim_scenario_available,
    resolve_distribution_range,
    skim_family_options,
    skim_summary_precision_overrides,
)
TOP_SELECTOR_ROW_STYLESHEET = """
:host(.trip-skim-top-selector) {
  max-width: 240px;
}

:host(.trip-skim-top-selector-export) {
  max-width: 190px;
}
"""


@dashboard_page(
    page_id="trip_skims",
    title="Trip Skims",
    order=51,
    group_id="skim_summaries",
    default_enabled=True,
    prepared_data_mode="optional",
    required_prepared_tables=("trips",),
    required_summary_ids=(TRIP_STATS_SUMMARY_ID,),
)
class TripSkimsPage(DashboardPage):
    """Summary and live-distribution page for trip skim families."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the skim summary shell and the live-only distribution controls."""
        trip_stats = self.state.get_summary_series_set(
            TRIP_STATS_SUMMARY_ID, "weighted"
        )
        trip_family_options = skim_family_options(
            self.config,
            trip_stats,
            mode_column="trip_mode",
            target_table="trips",
        )
        initial_trip_family = trip_family_options[0]
        trip_component_options = component_options(trip_stats)
        initial_trip_component = trip_component_options[0]
        trip_scenario_options = ["Chosen Mode"]
        if skim_scenario_available(trip_stats, ALL_RECORDS_SCENARIO):
            trip_scenario_options.append("All Trips")

        self.trip_family_sel = self.selector(
            "trip_skim_family",
            widget=pn.widgets.Select(
                name="Trip Skim Family",
                options=trip_family_options,
                value=initial_trip_family,
            ),
            label="Trip Skim Family",
        )
        self.trip_scenario_sel = self.selector(
            "trip_skim_scenario",
            widget=pn.widgets.Select(
                name="Trip Skim Scenario",
                options=trip_scenario_options,
                value=trip_scenario_options[0],
            ),
            label="Trip Skim Scenario",
        )
        self._apply_top_selector_sizing(self.trip_family_sel)
        self._apply_top_selector_sizing(self.trip_scenario_sel)
        self.trip_component_sel = self.selector(
            "trip_distribution_component",
            widget=pn.widgets.Select(
                name="Trip Distribution Component",
                options=trip_component_options,
                value=initial_trip_component,
            ),
            label="Trip Distribution Component",
            exportable=False,
        )
        self.trip_mode_sel = self.selector(
            "trip_distribution_mode",
            widget=pn.widgets.Select(
                name="Trip Distribution Mode",
                options=mode_options(
                    trip_stats,
                    mode_column="trip_mode",
                    component=initial_trip_component,
                    skim_scenario=self._trip_skim_scenario_value(),
                ),
            ),
            label="Trip Distribution Mode",
            exportable=False,
        )
        self.trip_min_sel = self.selector(
            "trip_min",
            widget=pn.widgets.FloatInput(name="Trip Min", step=0.1, value=0.0),
            label="Trip Min",
            exportable=False,
        )
        self.trip_max_sel = self.selector(
            "trip_max",
            widget=pn.widgets.FloatInput(name="Trip Max", step=0.1, value=1.0),
            label="Trip Max",
            exportable=False,
        )
        self.trip_reset_btn = pn.widgets.Button(
            name="Reset to full range",
            button_type="default",
            width=150,
        )

        if self.trip_mode_sel.options:
            self.trip_mode_sel.value = self.trip_mode_sel.options[0]
        self.trip_reset_btn.on_click(lambda event: self._reset_distribution_range())

        self._summary_section = self.section(
            "trip_skim_summary_section",
            selectors=("trip_skim_family", "trip_skim_scenario"),
            render=self.render_summary_section,
        )
        self._distribution_section = self.section(
            "trip_skim_distribution_section",
            selectors=(
                "trip_skim_scenario",
                "trip_distribution_component",
                "trip_distribution_mode",
                "trip_min",
                "trip_max",
            ),
            export_data_mode="required",
            render=self.render_distribution_section,
        )

        content = [
            pn.pane.Markdown("## Trip Skims"),
            self._top_selector_row(),
            self._summary_section,
        ]
        if not self.state.export_mode:
            content.extend(
                [
                    pn.pane.Markdown("### Live Trip Distributions"),
                    control_row(self.trip_component_sel, self.trip_mode_sel),
                    self._distribution_section,
                ]
            )
        return self.new_section(*content)

    def _trip_summaries(self):
        """Return the skim trip statistics for the current weighting mode."""
        return self.state.get_summary_series_set(
            TRIP_STATS_SUMMARY_ID,
            self.weighting_key,
        )

    def _trip_prepared_runs(self):
        """Return prepared runs in the weighting mode expected by distribution charts."""
        return self.get_prepared_runs(weighted=(self.weighting_key == "weighted"))

    def _trip_skim_scenario_value(self) -> str:
        return (
            ALL_RECORDS_SCENARIO
            if getattr(self, "trip_scenario_sel", None) is not None
            and self.trip_scenario_sel.value == "All Trips"
            else CHOSEN_MODE_SCENARIO
        )

    def sync_controls(self) -> None:
        """Keep family, component, mode, and x-range controls in sync."""
        trip_stats = self._trip_summaries()

        trip_family_options = skim_family_options(
            self.config,
            trip_stats,
            mode_column="trip_mode",
            target_table="trips",
        )
        self.trip_family_sel.options = trip_family_options
        if self.trip_family_sel.value not in trip_family_options:
            self.trip_family_sel.value = trip_family_options[0]

        trip_scenario_options = ["Chosen Mode"]
        if skim_scenario_available(trip_stats, ALL_RECORDS_SCENARIO):
            trip_scenario_options.append("All Trips")
        self.trip_scenario_sel.options = trip_scenario_options
        if self.trip_scenario_sel.value not in trip_scenario_options:
            self.trip_scenario_sel.value = trip_scenario_options[0]

        trip_component_options = component_options(trip_stats)
        self.trip_component_sel.options = trip_component_options
        if self.trip_component_sel.value not in trip_component_options:
            self.trip_component_sel.value = trip_component_options[0]

        trip_mode_options = mode_options(
            trip_stats,
            mode_column="trip_mode",
            component=self.trip_component_sel.value,
            skim_scenario=self._trip_skim_scenario_value(),
        )
        self.trip_mode_sel.options = trip_mode_options
        if self.trip_mode_sel.value not in trip_mode_options:
            self.trip_mode_sel.value = trip_mode_options[0]

        self._sync_distribution_range_controls()

    def _sync_distribution_range_controls(self) -> None:
        """Auto-reset range widgets when the selected mode/component context changes."""
        context_key = (
            self.trip_component_sel.value,
            self.trip_mode_sel.value,
            self.weighting_key,
            self._trip_skim_scenario_value(),
        )
        bounds = distribution_data_bounds(
            self._trip_prepared_runs(),
            table_name="trips",
            mode_column="trip_mode",
            mode_value=self.trip_mode_sel.value,
            component=self.trip_component_sel.value,
            skim_scenario=self._trip_skim_scenario_value(),
        )
        target_range = bounds
        if target_range is None:
            self._page_state["trip_distribution_range_context"] = context_key
            self._page_state["trip_distribution_auto_range"] = None
            return

        last_context = self._page_state.get("trip_distribution_range_context")
        last_auto_range = self._page_state.get("trip_distribution_auto_range")
        current_range = resolve_distribution_range(
            self.trip_min_sel.value,
            self.trip_max_sel.value,
        )
        should_reset = (
            last_context != context_key
            or last_auto_range is None
            or current_range is None
            or (
                current_range is not None
                and last_auto_range is not None
                and tuple(current_range) == tuple(last_auto_range)
            )
        )
        if should_reset:
            self.trip_min_sel.value = float(target_range[0])
            self.trip_max_sel.value = float(target_range[1])

        self._page_state["trip_distribution_range_context"] = context_key
        self._page_state["trip_distribution_auto_range"] = tuple(target_range)

    def _reset_distribution_range(self) -> None:
        """Restore the current trip distribution x-range to its full observed extent."""
        auto_range = self._page_state.get("trip_distribution_auto_range")
        if not auto_range:
            return
        self.trip_min_sel.value = float(auto_range[0])
        self.trip_max_sel.value = float(auto_range[1])

    def render_summary_section(self):
        """Render summary statistics for the selected trip skim family."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        trip_stats = self._trip_summaries()
        if trip_stats is None:
            return [
                self.data_not_available_card(
                    detail="Trip skim summaries require the precomputed skim trip statistics table.",
                    missing_items=[TRIP_STATS_SUMMARY_ID],
                ),
            ]

        family = self.trip_family_sel.value
        if family == "No skim families available":
            return [
                self.data_not_available_card(
                    detail="Trip skim summaries are available only when skim-enriched trip summary tables contain supported skim-family modes.",
                    missing_items=[TRIP_STATS_SUMMARY_ID],
                ),
            ]

        trip_stats_data = self.get_filtered_view(
            "trip_skim_family_stats",
            family,
            self._trip_skim_scenario_value(),
            factory=lambda: family_stats_table(
                self.config,
                trip_stats,
                family=family,
                mode_column="trip_mode",
                target_table="trips",
                skim_scenario=self._trip_skim_scenario_value(),
            ),
        )
        if not any(not df.is_empty() for _, df in trip_stats_data):
            return [
                self.data_not_available_card(
                    detail=f"No trip skim summary data is available for family `{family}`.",
                ),
            ]

        return [
            self.render_summary_table(trip_stats_data, family),
        ]

    def render_distribution_section(self):
        """Render the live prepared-trip skim distribution controls and chart."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        component = self.trip_component_sel.value
        trip_mode = self.trip_mode_sel.value
        trip_distribution_x_range = resolve_distribution_range(
            self.trip_min_sel.value,
            self.trip_max_sel.value,
        )
        if trip_distribution_x_range is None:
            return [
                control_row(self.trip_min_sel, self.trip_max_sel, self.trip_reset_btn),
                self.data_not_available_card(
                    detail="Trip distribution controls require finite values with min less than max.",
                ),
            ]

        trip_distribution_data = self.get_filtered_view(
            "trip_skim_distribution",
            component,
            trip_mode,
            self.weighting_key,
            self._trip_skim_scenario_value(),
            trip_distribution_x_range[0],
            trip_distribution_x_range[1],
            factory=lambda: distribution_bins(
                self._trip_prepared_runs(),
                table_name="trips",
                mode_column="trip_mode",
                mode_value=trip_mode,
                component=component,
                x_range=trip_distribution_x_range,
                skim_scenario=self._trip_skim_scenario_value(),
            ),
        )

        trip_distribution_view = (
            self.render_distribution_chart(
                trip_distribution_data,
                component=component,
                trip_mode=trip_mode,
                x_range=trip_distribution_x_range,
            )
            if any(not df.is_empty() for _, df in trip_distribution_data)
            else self.data_not_available_card(
                detail=(
                    "The disaggregated trip skim distribution requires loaded prepared trip "
                    "tables with non-null values for the selected component and mode."
                ),
            )
        )

        return [
            control_row(self.trip_min_sel, self.trip_max_sel, self.trip_reset_btn),
            trip_distribution_view,
        ]

    def render_summary_table(
        self,
        trip_stats_data,
        family: str,
    ) -> pn.viewable.Viewable:
        """Render the summary-statistics table for one skim family."""
        return data_table(
            trip_stats_data,
            title=f"Trip Summary Statistics - {family}",
            height=280,
            numeric_precision=2,
            numeric_precision_by_column=skim_summary_precision_overrides(),
        )

    def render_distribution_chart(
        self,
        trip_distribution_data,
        *,
        component: str,
        trip_mode: str,
        x_range: tuple[float, float],
    ) -> pn.viewable.Viewable:
        """Render the live prepared-trip skim distribution chart."""
        return density_chart(
            trip_distribution_data,
            x_col="bin_mid",
            y_col="freq",
            title=f"Trip Distribution - {component} / {trip_mode}",
            xaxis_title="Skim Value",
            yaxis_title="Trips",
            normalize=self.as_percent,
            height=320,
            as_percent=False,
            xaxis_range=x_range,
        )

    def _apply_top_selector_sizing(self, widget: pn.widgets.Widget) -> None:
        css_classes = list(getattr(widget, "css_classes", []) or [])
        base_class = "trip-skim-top-selector"
        export_class = "trip-skim-top-selector-export"
        if base_class not in css_classes:
            css_classes.append(base_class)
        if self.state.export_mode and export_class not in css_classes:
            css_classes.append(export_class)
        widget.css_classes = css_classes
        stylesheets = list(getattr(widget, "stylesheets", []) or [])
        if TOP_SELECTOR_ROW_STYLESHEET not in stylesheets:
            stylesheets.append(TOP_SELECTOR_ROW_STYLESHEET)
        widget.stylesheets = stylesheets

    def _top_selector_row(self) -> pn.Row:
        gap = "4px" if self.state.export_mode else "6px"
        return pn.Row(
            self.trip_family_sel,
            self.trip_scenario_sel,
            sizing_mode="stretch_width",
            min_height=72,
            margin=(0, 0, 8, 0),
            styles={
                "justify-content": "flex-start",
                "align-items": "flex-start",
                "flex-wrap": "nowrap",
                "column-gap": gap,
            },
        )
