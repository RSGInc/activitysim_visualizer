"""Tour skim summaries page."""

from __future__ import annotations

import panel as pn

from dashboard.components import control_row, data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages.skim_summaries._shared import (
    TOUR_STATS_SUMMARY_ID,
    directional_component_name,
    distribution_bins,
    distribution_data_bounds,
    family_stats_table,
    resolve_distribution_range,
    skim_direction_options,
    skim_family_options,
    skim_summary_precision_overrides,
    tour_component_base_options,
    tour_mode_options,
)


class TourSkimsPage(DashboardPage):
    """Summary and live-distribution page for tour skim families."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the summary shell and the live directional distribution controls."""
        tour_stats = self.state.get_summary_series_set(
            TOUR_STATS_SUMMARY_ID, "weighted"
        )
        family_options = skim_family_options(
            self.config,
            tour_stats,
            mode_column="tour_mode",
            target_table="tours",
        )
        initial_family = family_options[0]
        direction_options = skim_direction_options(tour_stats)
        initial_direction = direction_options[0]
        component_base_options = tour_component_base_options(tour_stats)
        initial_component_base = component_base_options[0]

        self.tour_family_sel = self.selector(
            "tour_skim_family",
            widget=pn.widgets.Select(
                name="Tour Skim Family",
                options=family_options,
                value=initial_family,
            ),
            label="Tour Skim Family",
        )
        self.tour_direction_sel = self.selector(
            "tour_skim_direction",
            widget=pn.widgets.Select(
                name="Direction",
                options=direction_options,
                value=initial_direction,
            ),
            label="Direction",
        )
        self.tour_component_sel = self.selector(
            "tour_distribution_component",
            widget=pn.widgets.Select(
                name="Tour Distribution Component",
                options=component_base_options,
                value=initial_component_base,
            ),
            label="Tour Distribution Component",
            exportable=False,
        )
        self.tour_mode_sel = self.selector(
            "tour_distribution_mode",
            widget=pn.widgets.Select(
                name="Tour Distribution Mode",
                options=tour_mode_options(
                    tour_stats,
                    mode_column="tour_mode",
                    component_base=initial_component_base,
                ),
            ),
            label="Tour Distribution Mode",
            exportable=False,
        )
        self.outbound_min_sel = self.selector(
            "outbound_min",
            widget=pn.widgets.FloatInput(name="Outbound Min", step=0.1, value=0.0),
            label="Outbound Min",
            exportable=False,
        )
        self.outbound_max_sel = self.selector(
            "outbound_max",
            widget=pn.widgets.FloatInput(name="Outbound Max", step=0.1, value=1.0),
            label="Outbound Max",
            exportable=False,
        )
        self.outbound_reset_btn = pn.widgets.Button(
            name="Reset outbound range",
            button_type="default",
            width=170,
        )
        self.inbound_min_sel = self.selector(
            "inbound_min",
            widget=pn.widgets.FloatInput(name="Inbound Min", step=0.1, value=0.0),
            label="Inbound Min",
            exportable=False,
        )
        self.inbound_max_sel = self.selector(
            "inbound_max",
            widget=pn.widgets.FloatInput(name="Inbound Max", step=0.1, value=1.0),
            label="Inbound Max",
            exportable=False,
        )
        self.inbound_reset_btn = pn.widgets.Button(
            name="Reset inbound range",
            button_type="default",
            width=170,
        )

        if self.tour_mode_sel.options:
            self.tour_mode_sel.value = self.tour_mode_sel.options[0]
        self.outbound_reset_btn.on_click(
            lambda event: self._reset_distribution_range("outbound")
        )
        self.inbound_reset_btn.on_click(
            lambda event: self._reset_distribution_range("inbound")
        )

        self._summary_section = self.section(
            "tour_skim_summary_section",
            selectors=("tour_skim_family", "tour_skim_direction"),
            render=self.render_summary_section,
        )
        self._distribution_section = self.section(
            "tour_skim_distribution_section",
            selectors=(
                "tour_distribution_component",
                "tour_distribution_mode",
                "outbound_min",
                "outbound_max",
                "inbound_min",
                "inbound_max",
            ),
            export_data_mode="required",
            render=self.render_distribution_section,
        )

        content = [
            pn.pane.Markdown("## Tour Skims"),
            control_row(
                pn.pane.Markdown("**Tour Skim Family:**"),
                self.tour_family_sel,
                pn.pane.Markdown("**Direction:**"),
                self.tour_direction_sel,
            ),
            self._summary_section,
        ]
        if not self.state.export_mode:
            content.extend(
                [
                    pn.pane.Markdown("### Live Tour Distributions"),
                    control_row(
                        pn.pane.Markdown("**Tour Distribution Component:**"),
                        self.tour_component_sel,
                        pn.pane.Markdown("**Tour Distribution Mode:**"),
                        self.tour_mode_sel,
                    ),
                    self._distribution_section,
                ]
            )
        return self.new_section(*content)

    def _tour_summaries(self):
        """Return the skim tour statistics for the current weighting mode."""
        return self.state.get_summary_series_set(
            TOUR_STATS_SUMMARY_ID,
            self.weighting_key,
        )

    def _tour_prepared_runs(self):
        """Return prepared runs in the weighting mode expected by live distributions."""
        return self.get_prepared_runs(weighted=(self.weighting_key == "weighted"))

    def sync_controls(self) -> None:
        """Keep family, direction, component, mode, and x-range controls aligned."""
        tour_stats = self._tour_summaries()

        family_options = skim_family_options(
            self.config,
            tour_stats,
            mode_column="tour_mode",
            target_table="tours",
        )
        self.tour_family_sel.options = family_options
        if self.tour_family_sel.value not in family_options:
            self.tour_family_sel.value = family_options[0]

        direction_options = skim_direction_options(tour_stats)
        self.tour_direction_sel.options = direction_options
        if self.tour_direction_sel.value not in direction_options:
            self.tour_direction_sel.value = direction_options[0]

        component_base_options = tour_component_base_options(tour_stats)
        self.tour_component_sel.options = component_base_options
        if self.tour_component_sel.value not in component_base_options:
            self.tour_component_sel.value = component_base_options[0]

        mode_options = tour_mode_options(
            tour_stats,
            mode_column="tour_mode",
            component_base=self.tour_component_sel.value,
        )
        self.tour_mode_sel.options = mode_options
        if self.tour_mode_sel.value not in mode_options:
            self.tour_mode_sel.value = mode_options[0]

        self._sync_distribution_range_controls("outbound")
        self._sync_distribution_range_controls("inbound")

    def _directional_component(self, direction: str) -> str:
        """Map the selected component base to one directional skim component."""
        return directional_component_name(self.tour_component_sel.value, direction)

    def _sync_distribution_range_controls(self, direction: str) -> None:
        """Auto-reset range widgets when the directional distribution context changes."""
        min_widget = getattr(self, f"{direction}_min_sel")
        max_widget = getattr(self, f"{direction}_max_sel")
        component = self._directional_component(direction)
        context_key = (component, self.tour_mode_sel.value, self.weighting_key)
        state_key = f"{direction}_distribution_range_context"
        auto_key = f"{direction}_distribution_auto_range"

        bounds = distribution_data_bounds(
            self._tour_prepared_runs(),
            table_name="tours",
            mode_column="tour_mode",
            mode_value=self.tour_mode_sel.value,
            component=component,
        )
        if bounds is None:
            self._page_state[state_key] = context_key
            self._page_state[auto_key] = None
            return

        last_context = self._page_state.get(state_key)
        last_auto_range = self._page_state.get(auto_key)
        current_range = resolve_distribution_range(min_widget.value, max_widget.value)
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
            min_widget.value = float(bounds[0])
            max_widget.value = float(bounds[1])

        self._page_state[state_key] = context_key
        self._page_state[auto_key] = tuple(bounds)

    def _reset_distribution_range(self, direction: str) -> None:
        """Restore one directional distribution x-range to its full observed extent."""
        auto_range = self._page_state.get(f"{direction}_distribution_auto_range")
        if not auto_range:
            return
        getattr(self, f"{direction}_min_sel").value = float(auto_range[0])
        getattr(self, f"{direction}_max_sel").value = float(auto_range[1])

    def render_summary_table(self):
        """Render the summary-statistics table for the selected family and direction."""
        tour_stats = self._tour_summaries()
        family = self.tour_family_sel.value
        direction = self.tour_direction_sel.value

        if tour_stats is None:
            return self.data_not_available_card(
                detail="Tour skim summaries require the precomputed skim tour statistics table.",
                missing_items=[TOUR_STATS_SUMMARY_ID],
                title="Data Not Available",
            )

        if family == "No skim families available":
            return self.data_not_available_card(
                detail="Tour skim summaries are available only when skim-enriched tour summary tables contain supported skim-family modes.",
                missing_items=[TOUR_STATS_SUMMARY_ID],
                title="Data Not Available",
            )

        stats_data = self.get_filtered_view(
            "tour_skim_family_stats",
            family,
            direction,
            factory=lambda: family_stats_table(
                self.config,
                tour_stats,
                family=family,
                mode_column="tour_mode",
                target_table="tours",
                direction=direction,
            ),
        )
        if not any(not df.is_empty() for _, df in stats_data):
            return self.data_not_available_card(
                detail=f"No {direction.lower()} tour skim summary data is available for family `{family}`.",
                title="Data Not Available",
            )

        return data_table(
            stats_data,
            title=f"Tour Summary Statistics - {family} / {direction}",
            height=280,
            numeric_precision=2,
            numeric_precision_by_column=skim_summary_precision_overrides(),
        )

    def render_summary_section(self):
        """Render the selected tour skim summary table."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        return [
            self.render_summary_table(),
        ]

    def render_directional_distribution_chart(self, direction: str):
        """Render one directional live tour skim distribution."""
        component = self._directional_component(direction)
        mode = self.tour_mode_sel.value
        min_widget = getattr(self, f"{direction}_min_sel")
        max_widget = getattr(self, f"{direction}_max_sel")
        x_range = resolve_distribution_range(min_widget.value, max_widget.value)
        title = direction.title()
        if x_range is None:
            return self.data_not_available_card(
                detail=f"{title} distribution controls require finite values with min less than max.",
                title=f"{title} Data Not Available",
            )

        distribution_data = self.get_filtered_view(
            f"tour_skim_distribution_{direction}",
            component,
            mode,
            self.weighting_key,
            x_range[0],
            x_range[1],
            factory=lambda: distribution_bins(
                self._tour_prepared_runs(),
                table_name="tours",
                mode_column="tour_mode",
                mode_value=mode,
                component=component,
                x_range=x_range,
            ),
        )
        if not any(not df.is_empty() for _, df in distribution_data):
            return self.data_not_available_card(
                detail=(
                    f"The disaggregated {direction} tour skim distribution requires loaded prepared tour "
                    "tables with non-null values for the selected component and mode."
                ),
                title=f"{title} Data Not Available",
            )

        return density_chart(
            distribution_data,
            x_col="bin_mid",
            y_col="freq",
            title=f"{title} Tour Distribution - {component} / {mode}",
            xaxis_title="Skim Value",
            yaxis_title="Tours",
            normalize=self.as_percent,
            height=320,
            as_percent=False,
            xaxis_range=x_range,
        )

    def render_distribution_section(self):
        """Render the outbound and inbound live distribution controls and charts."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        return [
            control_row(
                pn.pane.Markdown("**Outbound Min:**"),
                self.outbound_min_sel,
                pn.pane.Markdown("**Outbound Max:**"),
                self.outbound_max_sel,
                self.outbound_reset_btn,
            ),
            self.render_directional_distribution_chart("outbound"),
            control_row(
                pn.pane.Markdown("**Inbound Min:**"),
                self.inbound_min_sel,
                pn.pane.Markdown("**Inbound Max:**"),
                self.inbound_max_sel,
                self.inbound_reset_btn,
            ),
            self.render_directional_distribution_chart("inbound"),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_skims",
    title="Tour Skims",
    page_cls=TourSkimsPage,
    order=50,
    group_id="skim_summaries",
    child_order=10,
    default_enabled=True,
    prepared_data_mode="optional",
    required_prepared_tables=("tours",),
    required_summary_ids=(TOUR_STATS_SUMMARY_ID,),
)

TourSkimsPage.definition = PAGE
