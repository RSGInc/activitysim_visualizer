"""Page composition for Traffic Validation."""

from __future__ import annotations

import panel as pn

from dashboard.rendering import selector_row

from .contracts import *


class TrafficPageCompositionMixin:
    def build_page(self) -> pn.viewable.Viewable:
        self.demo_facility_raw_by_label = {"All": "All"}
        self.demo_period_sel = self.selector(
            "demo_period",
            widget=pn.widgets.Select(
                name="Period",
                options=list(DEMO_TRAFFIC_TIME_PERIODS),
                value="Day",
            ),
            label="Period",
        )
        self.demo_facility_sel = self.select(
            "demo_facility_type",
            "Facility Type",
            options=self._facility_options,
        )
        self.demo_top_period_sel = self.selector(
            "demo_top_period",
            widget=pn.widgets.Select(
                name="Period",
                options=list(DEMO_TRAFFIC_TIME_PERIODS),
                value="Day",
            ),
            label="Period",
        )
        self.demo_top_n_sel = self.selector(
            "demo_top_n",
            widget=pn.widgets.Select(
                name="Top N by Modeled Volume",
                options=[10, 25, 50, 100],
                value=25,
            ),
            label="Top N by Modeled Volume",
        )
        observed_fit = self.feature("observed_model_fit")
        facility = self.feature("facility_summaries")
        links = self.feature("link_tables")
        screenlines = self.feature("screenlines")
        self._external_volume_body = observed_fit.section(
            "body",
            selectors=(
                "demo_period",
                "demo_facility_type",
            ),
            render=self.render_demo_traffic_section,
        )
        self._facility_summary_body = facility.section(
            "body",
            render=self.render_demo_facility_summary_section,
        )
        self._link_volume_body = links.section(
            "volume",
            selectors=("demo_period",),
            render=self.render_demo_link_volume_section,
        )
        self._external_top_body = links.section(
            "top",
            selectors=(
                "demo_facility_type",
                "demo_top_period",
                "demo_top_n",
            ),
            render=self.render_demo_top_count_section,
        )
        self._screenline_body = screenlines.section(
            "body",
            render=self.render_screenline_flow_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Traffic Validation"),
            self._facility_summary_body,
            pn.pane.Markdown("### Traffic Volume Summaries"),
            selector_row(
                self.demo_period_sel,
                self.demo_facility_sel,
            ),
            self._external_volume_body,
            self._link_volume_body,
            pn.pane.Markdown("### Top Count Locations by Modeled Volume"),
            selector_row(self.demo_top_period_sel, self.demo_top_n_sel),
            self._external_top_body,
            pn.pane.Markdown("### Screenline Flow Summaries"),
            self._screenline_body,
            sizing_mode="stretch_width",
        )
