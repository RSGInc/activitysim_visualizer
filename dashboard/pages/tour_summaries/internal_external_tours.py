"""Internal vs. external tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.geography import (
    filter_geo_level,
    geo_level_options,
    normalize_geography_columns,
)


class InternalExternalToursPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        geo_data = self.state.get_summary_table_set(
            "internal_external_nonmandatory_tour_frequency_by_home_geography",
            "weighted",
        )
        geo_opts = geo_level_options(geo_data or [])
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=geo_opts,
                value=geo_opts[0],
            ),
            label="Geography Level",
        )
        self._body = self.section(
            "internal_external_tours_body",
            selectors=("geography_level",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Internal vs. External Tours"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        int_ext_list = self.optional_summary(
            "internal_external_nonmandatory_tour_frequency_by_home_geography"
        )
        external_loc_list = self.optional_summary(
            "external_nonmandatory_tour_locations"
        )
        normalized_int_ext = (
            [(label, normalize_geography_columns(df)) for label, df in int_ext_list]
            if int_ext_list is not None
            else []
        )
        normalized_external_loc = (
            [
                (label, normalize_geography_columns(df))
                for label, df in external_loc_list
            ]
            if external_loc_list is not None
            else []
        )
        geo_opts = geo_level_options(normalized_int_ext or normalized_external_loc)
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        int_ext_list = self.optional_summary(
            "internal_external_nonmandatory_tour_frequency_by_home_geography"
        )
        external_loc_list = self.optional_summary(
            "external_nonmandatory_tour_locations"
        )

        normalized_int_ext = (
            [(label, normalize_geography_columns(df)) for label, df in int_ext_list]
            if int_ext_list is not None
            else []
        )
        normalized_external_loc = (
            [
                (label, normalize_geography_columns(df))
                for label, df in external_loc_list
            ]
            if external_loc_list is not None
            else []
        )
        geo_level = self.geo_level_sel.value

        if normalized_int_ext:
            int_ext_data = self.get_filtered_view(
                "internal_external_nonmandatory_tours",
                geo_level,
                factory=lambda: filter_geo_level(normalized_int_ext, geo_level),
            )
            int_ext_widget: pn.viewable.Viewable = data_table(
                int_ext_data,
                "Internal vs. External Non-Mandatory Tour Frequency",
            )
        else:
            int_ext_widget = self.data_not_available_card(
                detail="The internal/external non-mandatory tour summary is unavailable.",
                missing_items=[
                    "internal_external_nonmandatory_tour_frequency_by_home_geography"
                ],
            )

        if normalized_external_loc:
            external_loc_data = self.get_filtered_view(
                "external_nonmandatory_tour_locations",
                geo_level,
                factory=lambda: filter_geo_level(normalized_external_loc, geo_level),
            )
            external_loc_widget: pn.viewable.Viewable = data_table(
                external_loc_data,
                "External Non-Mandatory Tour Location",
            )
        else:
            external_loc_widget = self.data_not_available_card(
                detail="The external non-mandatory tour location summary is unavailable.",
                missing_items=["external_nonmandatory_tour_locations"],
            )

        return [
            pn.Row(
                int_ext_widget,
                external_loc_widget,
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="internal_external_tours",
    title="Internal vs. External Tours",
    group_id="tour_summaries",
    order=46,
    page_cls=InternalExternalToursPage,
    required_summary_ids=(
        "internal_external_nonmandatory_tour_frequency_by_home_geography",
        "external_nonmandatory_tour_locations",
    ),
)

InternalExternalToursPage.definition = PAGE
