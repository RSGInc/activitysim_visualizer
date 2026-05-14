"""Shadow pricing validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, scatter_chart
from dashboard.page_base import (
    CollectedStatePage,
    SectionContent,
    SectionSpec,
    SelectorSpec,
)
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_options, filter_runs_by_column


class ShadowPricingPage(CollectedStatePage):
    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="geography_level",
                label="Geography Level",
                attr_name="geo_level_sel",
                options_factory=lambda page: list(
                    page._current_data.get("geo_opts", ["All"])
                ),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Geography Level",
                    options=options,
                    value=value,
                ),
            ),
            SelectorSpec(
                selector_id="student_type",
                label="Student Type",
                attr_name="student_type_sel",
                options_factory=lambda page: list(
                    page._current_data.get("student_opts", ["All"])
                ),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Student Type",
                    options=options,
                    value=value,
                ),
            ),
        )

    def build_page(self) -> pn.viewable.Viewable:
        self.register_selectors(*self.selector_specs())
        self.register_sections(
            SectionSpec(
                section_id="workplace_plot",
                selector_ids=("geography_level",),
                render=lambda page: page.render_workplace_plot(),
                attr_name="_workplace_plot_section",
            ),
            SectionSpec(
                section_id="workplace_table",
                selector_ids=("geography_level",),
                render=lambda page: page.render_workplace_table(),
                attr_name="_workplace_table_section",
            ),
            SectionSpec(
                section_id="school_plot",
                selector_ids=("geography_level", "student_type"),
                render=lambda page: page.render_school_plot(),
                attr_name="_school_plot_section",
            ),
            SectionSpec(
                section_id="school_table",
                selector_ids=("geography_level", "student_type"),
                render=lambda page: page.render_school_table(),
                attr_name="_school_table_section",
            ),
        )
        self._workplace_section = self.new_section(
            self._workplace_plot_section,
            self._workplace_table_section,
        )
        self._school_section = self.new_section(
            self._school_plot_section,
            self._school_table_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Shadow Pricing"),
            self._workplace_section,
            self._school_section,
        )

    def collect_base_state(self) -> dict[str, object]:
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": ["All"],
                "student_opts": ["All"],
            }
        workplace_summary = self.get_refresh_summary(
            "workplace_location_employment_comparison",
            optional=True,
        )
        school_summary = self.get_refresh_summary(
            "school_location_enrollment_comparison",
            optional=True,
        )
        return {
            "mode": "ready",
            "geo_opts": column_options(
                workplace_summary or school_summary or [], "geography_type"
            ),
            "student_opts": column_options(school_summary or [], "student_type"),
            "workplace_summary": workplace_summary,
            "school_summary": school_summary,
        }

    def collect_selector_state(self, base_state: dict[str, object]) -> dict[str, object]:
        return dict(base_state)

    def collect_page_state(self) -> dict[str, object]:
        return self.collect_base_state()

    def render_workplace_plot(self) -> SectionContent:
        if self._current_data["mode"] == "no_runs":
            return [pn.pane.Markdown("No runs loaded.")]
        workplace_summary = self._current_data["workplace_summary"]
        if workplace_summary is None:
            return [
                self.data_not_available_card(
                    detail="The workplace employment comparison summary is unavailable.",
                    missing_items=["workplace_location_employment_comparison"],
                )
            ]
        geo_level = str(self.geo_level_sel.value)
        workplace_data = self.get_filtered_view(
            "shadow_pricing_workplace",
            geo_level,
            factory=lambda: filter_runs_by_column(
                workplace_summary,
                "geography_type",
                geo_level,
            ),
        )
        return [
            pn.pane.Markdown("### Workplace Shadow Pricing"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            scatter_chart(
                workplace_data,
                x_col="employment_count",
                y_col="worker_count",
                title="Workplace Location vs Land Use Employment",
                xaxis_title="Land Use Employment",
                yaxis_title="Workers",
                drop_zero_y=True,
            ),
        ]

    def render_workplace_table(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        workplace_summary = self._current_data["workplace_summary"]
        if workplace_summary is None:
            return []
        geo_level = str(self.geo_level_sel.value)
        workplace_data = self.get_filtered_view(
            "shadow_pricing_workplace",
            geo_level,
            factory=lambda: filter_runs_by_column(
                workplace_summary,
                "geography_type",
                geo_level,
            ),
        )
        return [
            data_table(
                workplace_data,
                "Workplace Employment Comparison by Geography",
            )
        ]

    def render_school_plot(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        school_summary = self._current_data["school_summary"]
        if school_summary is None:
            return [
                self.data_not_available_card(
                    detail="The school enrollment comparison summary is unavailable.",
                    missing_items=["school_location_enrollment_comparison"],
                )
            ]
        geo_level = str(self.geo_level_sel.value)
        student_type = str(self.student_type_sel.value)
        school_data = self.get_filtered_view(
            "shadow_pricing_school",
            (geo_level, student_type),
            factory=lambda: filter_runs_by_column(
                filter_runs_by_column(
                    school_summary,
                    "geography_type",
                    geo_level,
                ),
                "student_type",
                student_type,
            ),
        )
        return [
            pn.pane.Markdown("### School Shadow Pricing"),
            pn.Row(
                pn.pane.Markdown("**Student Type:**"),
                self.student_type_sel,
            ),
            scatter_chart(
                school_data,
                x_col="enrollment_count",
                y_col="student_count",
                title="School Location vs Land Use Enrollment",
                xaxis_title="Land Use Enrollment",
                yaxis_title="Students",
                drop_zero_y=True,
            ),
        ]

    def render_school_table(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        school_summary = self._current_data["school_summary"]
        if school_summary is None:
            return []
        geo_level = str(self.geo_level_sel.value)
        student_type = str(self.student_type_sel.value)
        school_data = self.get_filtered_view(
            "shadow_pricing_school",
            (geo_level, student_type),
            factory=lambda: filter_runs_by_column(
                filter_runs_by_column(
                    school_summary,
                    "geography_type",
                    geo_level,
                ),
                "student_type",
                student_type,
            ),
        )
        return [data_table(school_data, "School Enrollment Comparison by Geography")]


PAGE = DashboardPageDefinition(
    page_id="shadow_pricing",
    title="Shadow Pricing",
    group_id="long_term_choices",
    order=28,
    page_cls=ShadowPricingPage,
    required_summary_ids=(
        "workplace_location_employment_comparison",
        "school_location_enrollment_comparison",
    ),
)

ShadowPricingPage.definition = PAGE
