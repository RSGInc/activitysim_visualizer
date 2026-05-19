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
    filter_stats,
    resolve_distribution_range,
    tour_component_base_options,
    tour_mode_options,
)


class TourSkimsPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        tour_stats = self.state.get_summary_table_set(TOUR_STATS_SUMMARY_ID, "weighted")
        component_base_options = tour_component_base_options(tour_stats)
        initial_component_base = component_base_options[0]

        self.tour_component_sel = self.selector(
            "tour_skim_component",
            widget=pn.widgets.Select(
                name="Tour Skim Component",
                options=component_base_options,
                value=initial_component_base,
            ),
            label="Tour Skim Component",
        )
        self.tour_mode_sel = self.selector(
            "tour_mode",
            widget=pn.widgets.Select(
                name="Tour Mode",
                options=tour_mode_options(
                    tour_stats,
                    mode_column="tour_mode",
                    component_base=initial_component_base,
                ),
            ),
            label="Tour Mode",
        )
        self.outbound_min_sel = self.selector(
            "outbound_min",
            widget=pn.widgets.FloatInput(name="Outbound Min", step=0.1, value=0.0),
            label="Outbound Min",
        )
        self.outbound_max_sel = self.selector(
            "outbound_max",
            widget=pn.widgets.FloatInput(name="Outbound Max", step=0.1, value=1.0),
            label="Outbound Max",
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
        )
        self.inbound_max_sel = self.selector(
            "inbound_max",
            widget=pn.widgets.FloatInput(name="Inbound Max", step=0.1, value=1.0),
            label="Inbound Max",
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
            selectors=("tour_skim_component", "tour_mode"),
            render=self.render_summary_section,
        )
        self._distribution_section = self.section(
            "tour_skim_distribution_section",
            selectors=(
                "tour_skim_component",
                "tour_mode",
                "outbound_min",
                "outbound_max",
                "inbound_min",
                "inbound_max",
            ),
            export_data_mode="required",
            render=self.render_distribution_section,
        )

        return self.new_section(
            pn.pane.Markdown("## Tour Skims"),
            control_row(
                pn.pane.Markdown("**Tour Skim Component:**"),
                self.tour_component_sel,
            ),
            self._summary_section,
            self._distribution_section,
        )

    def _tour_summaries(self):
        return self.optional_summary(TOUR_STATS_SUMMARY_ID)

    def _tour_prepared_runs(self):
        return self.get_prepared_runs(weighted=(self.weighting_key == "weighted"))

    def sync_controls(self) -> None:
        tour_stats = self._tour_summaries()

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
        return directional_component_name(self.tour_component_sel.value, direction)

    def _sync_distribution_range_controls(self, direction: str) -> None:
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
        auto_range = self._page_state.get(f"{direction}_distribution_auto_range")
        if not auto_range:
            return
        getattr(self, f"{direction}_min_sel").value = float(auto_range[0])
        getattr(self, f"{direction}_max_sel").value = float(auto_range[1])

    def _render_directional_summary(self, direction: str):
        tour_stats = self._tour_summaries()
        component_base = self.tour_component_sel.value
        tour_mode = self.tour_mode_sel.value
        component = self._directional_component(direction)
        title = direction.title()

        if tour_stats is None:
            return self.data_not_available_card(
                detail="Tour skim summaries require the precomputed skim tour statistics table.",
                missing_items=[TOUR_STATS_SUMMARY_ID],
                title=f"{title} Data Not Available",
            )

        if (
            component_base == "No components available"
            or tour_mode == "No modes available"
        ):
            return self.data_not_available_card(
                detail="Tour skim summaries are available only when skim-enriched tour summary tables contain numeric components.",
                missing_items=[TOUR_STATS_SUMMARY_ID],
                title=f"{title} Data Not Available",
            )

        stats_data = self.get_filtered_view(
            f"tour_skim_stats_{direction}",
            component,
            tour_mode,
            factory=lambda: filter_stats(
                tour_stats,
                component=component,
                mode_column="tour_mode",
                mode_value=tour_mode,
            ),
        )
        if not any(not df.is_empty() for _, df in stats_data):
            return self.data_not_available_card(
                detail=f"No {direction} tour skim summary data is available for component `{component}` and mode `{tour_mode}`.",
                title=f"{title} Data Not Available",
            )

        return data_table(
            stats_data,
            title=f"{title} Tour Summary Statistics - {component} / {tour_mode}",
            height=130,
        )

    def render_summary_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        return [
            control_row(
                pn.pane.Markdown("**Tour Mode:**"),
                self.tour_mode_sel,
            ),
            pn.Row(
                self._render_directional_summary("outbound"),
                self._render_directional_summary("inbound"),
                sizing_mode="stretch_width",
            ),
        ]

    def _render_directional_distribution(self, direction: str):
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
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        return [
            control_row(
                pn.pane.Markdown("**Outbound Min:**"),
                self.outbound_min_sel,
                pn.pane.Markdown("**Outbound Max:**"),
                self.outbound_max_sel,
                self.outbound_reset_btn,
            ),
            self._render_directional_distribution("outbound"),
            control_row(
                pn.pane.Markdown("**Inbound Min:**"),
                self.inbound_min_sel,
                pn.pane.Markdown("**Inbound Max:**"),
                self.inbound_max_sel,
                self.inbound_reset_btn,
            ),
            self._render_directional_distribution("inbound"),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_skims",
    title="Tour Skims",
    page_cls=TourSkimsPage,
    order=51,
    group_id="skims",
    child_order=20,
    default_enabled=True,
    prepared_data_mode="optional",
    required_prepared_tables=("tours",),
    required_summary_ids=(TOUR_STATS_SUMMARY_ID,),
)

TourSkimsPage.definition = PAGE
