"""Internal vs. external tours page."""

from __future__ import annotations

import panel as pn

from dashboard.components import data_table, selector_row
from dashboard.helpers.geography_helpers import (
    filter_geography_level,
    geography_level_options,
    normalize_geography_data,
)
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition


class InternalExternalToursPage(DashboardPage):
    """Compare internal/external non-mandatory tours across geography levels."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page with one shared geography-level selector."""
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=["Total"],
                value="Total",
            ),
            label="Geography Level",
        )
        self._body = self.section(
            "internal_external_tours_body",
            selectors=("geography_level",),
            render=self.render_body_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Internal vs. External Tours"),
            selector_row(self.geo_level_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        """Keep the geography-level selector aligned with available summaries."""
        summaries = self.optional_summaries_dict(
            "internal_external_nonmandatory_tour_frequency_by_home_geography",
            "external_nonmandatory_tour_locations",
        )
        geo_opts = geography_level_options(
            normalize_geography_data(
                summaries["internal_external_nonmandatory_tour_frequency_by_home_geography"]
            )
            or None,
            normalize_geography_data(summaries["external_nonmandatory_tour_locations"])
            or None,
            config=self.config,
            total_label="Total",
        )
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

    def render_body_section(self) -> SectionContent:
        """Render the two tour tables side by side for the selected level."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        geo_level = str(self.geo_level_sel.value)
        summaries = self.optional_summaries_dict(
            "internal_external_nonmandatory_tour_frequency_by_home_geography",
            "external_nonmandatory_tour_locations",
        )
        int_ext_widget = self.render_internal_external_table(
            geo_level,
            normalize_geography_data(
                summaries["internal_external_nonmandatory_tour_frequency_by_home_geography"]
            ),
        )
        external_locations_widget = self.render_external_locations_table(
            geo_level,
            normalize_geography_data(summaries["external_nonmandatory_tour_locations"]),
        )
        return [
            pn.Row(
                int_ext_widget,
                external_locations_widget,
                sizing_mode="stretch_width",
            )
        ]

    def render_internal_external_table(
        self,
        geo_level: str,
        summary_data,
    ) -> pn.viewable.Viewable:
        """Render internal/external non-mandatory tour frequencies."""
        if not summary_data:
            return self.data_not_available_card(
                detail="The internal/external non-mandatory tour summary is unavailable.",
                missing_items=[
                    "internal_external_nonmandatory_tour_frequency_by_home_geography"
                ],
            )

        table_data = self.get_filtered_view(
            "internal_external_nonmandatory_tours",
            geo_level,
            factory=lambda: filter_geography_level(summary_data, geo_level),
        )
        return data_table(
            table_data,
            "Internal vs. External Non-Mandatory Tour Frequency",
        )

    def render_external_locations_table(
        self,
        geo_level: str,
        summary_data,
    ) -> pn.viewable.Viewable:
        """Render the location breakdown for external non-mandatory tours."""
        if not summary_data:
            return self.data_not_available_card(
                detail="The external non-mandatory tour location summary is unavailable.",
                missing_items=["external_nonmandatory_tour_locations"],
            )

        table_data = self.get_filtered_view(
            "external_nonmandatory_tour_locations",
            geo_level,
            factory=lambda: filter_geography_level(summary_data, geo_level),
        )
        return data_table(table_data, "External Non-Mandatory Tour Location")


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
