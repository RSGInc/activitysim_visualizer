"""Trip skim summaries page."""

from __future__ import annotations

import panel as pn

from dashboard.components import control_row, data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages.skim_summaries._shared import (
    TRIP_STATS_SUMMARY_ID,
    component_options,
    distribution_bins,
    distribution_data_bounds,
    filter_stats,
    mode_options,
    resolve_distribution_range,
)


class TripSkimsPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        trip_stats = self.state.get_summary_table_set(TRIP_STATS_SUMMARY_ID, "weighted")
        trip_component_options = component_options(trip_stats)
        initial_trip_component = trip_component_options[0]

        self.trip_component_sel = self.selector(
            "trip_skim_component",
            widget=pn.widgets.Select(
                name="Trip Skim Component",
                options=trip_component_options,
                value=initial_trip_component,
            ),
            label="Trip Skim Component",
        )
        self.trip_mode_sel = self.selector(
            "trip_mode",
            widget=pn.widgets.Select(
                name="Trip Mode",
                options=mode_options(
                    trip_stats,
                    mode_column="trip_mode",
                    component=initial_trip_component,
                ),
            ),
            label="Trip Mode",
        )
        self.trip_min_sel = self.selector(
            "trip_min",
            widget=pn.widgets.FloatInput(name="Trip Min", step=0.1, value=0.0),
            label="Trip Min",
        )
        self.trip_max_sel = self.selector(
            "trip_max",
            widget=pn.widgets.FloatInput(name="Trip Max", step=0.1, value=1.0),
            label="Trip Max",
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
            selectors=("trip_skim_component", "trip_mode"),
            render=self.render_summary_section,
        )
        self._distribution_section = self.section(
            "trip_skim_distribution_section",
            selectors=("trip_skim_component", "trip_mode", "trip_min", "trip_max"),
            export_data_mode="required",
            render=self.render_distribution_section,
        )

        return self.new_section(
            pn.pane.Markdown("## Trip Skims"),
            control_row(
                pn.pane.Markdown("**Trip Skim Component:**"),
                self.trip_component_sel,
            ),
            self._summary_section,
            self._distribution_section,
        )

    def _trip_summaries(self):
        return self.optional_summary(TRIP_STATS_SUMMARY_ID)

    def _trip_prepared_runs(self):
        return self.get_prepared_runs(weighted=(self.weighting_key == "weighted"))

    def sync_controls(self) -> None:
        trip_stats = self._trip_summaries()

        trip_component_options = component_options(trip_stats)
        self.trip_component_sel.options = trip_component_options
        if self.trip_component_sel.value not in trip_component_options:
            self.trip_component_sel.value = trip_component_options[0]

        trip_mode_options = mode_options(
            trip_stats,
            mode_column="trip_mode",
            component=self.trip_component_sel.value,
        )
        self.trip_mode_sel.options = trip_mode_options
        if self.trip_mode_sel.value not in trip_mode_options:
            self.trip_mode_sel.value = trip_mode_options[0]

        self._sync_distribution_range_controls()

    def _sync_distribution_range_controls(self) -> None:
        context_key = (
            self.trip_component_sel.value,
            self.trip_mode_sel.value,
            self.weighting_key,
        )
        bounds = distribution_data_bounds(
            self._trip_prepared_runs(),
            table_name="trips",
            mode_column="trip_mode",
            mode_value=self.trip_mode_sel.value,
            component=self.trip_component_sel.value,
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
        auto_range = self._page_state.get("trip_distribution_auto_range")
        if not auto_range:
            return
        self.trip_min_sel.value = float(auto_range[0])
        self.trip_max_sel.value = float(auto_range[1])

    def render_summary_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        trip_stats = self._trip_summaries()
        if trip_stats is None:
            return [
                control_row(
                    pn.pane.Markdown("**Trip Mode:**"),
                    self.trip_mode_sel,
                ),
                self.data_not_available_card(
                    detail="Trip skim summaries require the precomputed skim trip statistics table.",
                    missing_items=[TRIP_STATS_SUMMARY_ID],
                ),
            ]

        component = self.trip_component_sel.value
        trip_mode = self.trip_mode_sel.value
        if component == "No components available" or trip_mode == "No modes available":
            return [
                control_row(
                    pn.pane.Markdown("**Trip Mode:**"),
                    self.trip_mode_sel,
                ),
                self.data_not_available_card(
                    detail="Trip skim summaries are available only when skim-enriched trip summary tables contain numeric components.",
                    missing_items=[TRIP_STATS_SUMMARY_ID],
                ),
            ]

        trip_stats_data = self.get_filtered_view(
            "trip_skim_stats",
            component,
            trip_mode,
            factory=lambda: filter_stats(
                trip_stats,
                component=component,
                mode_column="trip_mode",
                mode_value=trip_mode,
            ),
        )
        if not any(not df.is_empty() for _, df in trip_stats_data):
            return [
                control_row(
                    pn.pane.Markdown("**Trip Mode:**"),
                    self.trip_mode_sel,
                ),
                self.data_not_available_card(
                    detail=f"No trip skim summary data is available for component `{component}` and mode `{trip_mode}`.",
                ),
            ]

        return [
            control_row(
                pn.pane.Markdown("**Trip Mode:**"),
                self.trip_mode_sel,
            ),
            data_table(
                trip_stats_data,
                title=f"Trip Summary Statistics - {component} / {trip_mode}",
                height=130,
            ),
        ]

    def render_distribution_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        component = self.trip_component_sel.value
        trip_mode = self.trip_mode_sel.value
        trip_distribution_x_range = resolve_distribution_range(
            self.trip_min_sel.value,
            self.trip_max_sel.value,
        )
        if trip_distribution_x_range is None:
            return [
                control_row(
                    pn.pane.Markdown("**Trip Distribution Min:**"),
                    self.trip_min_sel,
                    pn.pane.Markdown("**Trip Distribution Max:**"),
                    self.trip_max_sel,
                    self.trip_reset_btn,
                ),
                self.data_not_available_card(
                    detail="Trip distribution controls require finite values with min less than max.",
                ),
            ]

        trip_distribution_data = self.get_filtered_view(
            "trip_skim_distribution",
            component,
            trip_mode,
            self.weighting_key,
            trip_distribution_x_range[0],
            trip_distribution_x_range[1],
            factory=lambda: distribution_bins(
                self._trip_prepared_runs(),
                table_name="trips",
                mode_column="trip_mode",
                mode_value=trip_mode,
                component=component,
                x_range=trip_distribution_x_range,
            ),
        )

        trip_distribution_view = (
            density_chart(
                trip_distribution_data,
                x_col="bin_mid",
                y_col="freq",
                title=f"Trip Distribution - {component} / {trip_mode}",
                xaxis_title="Skim Value",
                yaxis_title="Trips",
                normalize=self.as_percent,
                height=320,
                as_percent=False,
                xaxis_range=trip_distribution_x_range,
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
            control_row(
                pn.pane.Markdown("**Trip Distribution Min:**"),
                self.trip_min_sel,
                pn.pane.Markdown("**Trip Distribution Max:**"),
                self.trip_max_sel,
                self.trip_reset_btn,
            ),
            trip_distribution_view,
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_skims",
    title="Trip Skims",
    page_cls=TripSkimsPage,
    order=50,
    group_id="skims",
    child_order=10,
    default_enabled=True,
    prepared_data_mode="optional",
    required_prepared_tables=("trips",),
    required_summary_ids=(TRIP_STATS_SUMMARY_ID,),
)

TripSkimsPage.definition = PAGE
