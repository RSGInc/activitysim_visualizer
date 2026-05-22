"""Shadow pricing validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, scatter_chart
from dashboard.helpers.geography_helpers import detail_geography_levels
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    *,
    config: Config | None = None,
    total_label: str = "All",
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    if config is not None and col == "geography_type":
        vals = detail_geography_levels(vals, config=config)
        return vals or [total_label]
    vals = sorted(v for v in vals if v != total_label)
    return [total_label] + [v for v in vals if v != total_label]


def _filter_col(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    value: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if col in df.columns and value != "All":
            df = df.with_columns(pl.col(col).cast(pl.Utf8)).filter(pl.col(col) == value)
        out.append((label, df))
    return out


class ShadowPricingPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self._current_data: dict[str, object] = {}
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=["all_geographies"],
                value="all_geographies",
            ),
            label="Geography Level",
        )
        self.student_type_sel = self.selector(
            "student_type",
            widget=pn.widgets.Select(
                name="Student Type",
                options=["All"],
                value="All",
            ),
            label="Student Type",
        )
        self._workplace_plot_section = self.section(
            "workplace_plot",
            selectors=("geography_level",),
            render=self.render_workplace_plot,
        )
        self._workplace_table_section = self.section(
            "workplace_table",
            selectors=("geography_level",),
            render=self.render_workplace_table,
        )
        self._school_plot_section = self.section(
            "school_plot",
            selectors=("geography_level", "student_type"),
            render=self.render_school_plot,
        )
        self._school_table_section = self.section(
            "school_table",
            selectors=("geography_level", "student_type"),
            render=self.render_school_table,
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

    def sync_controls(self) -> None:
        self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]
        student_opts = self._current_data["student_opts"]
        self.student_type_sel.options = student_opts
        if self.student_type_sel.value not in student_opts:
            self.student_type_sel.value = student_opts[0]

    def _collect_data(self) -> dict[str, object]:
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": ["All"],
                "student_opts": ["All"],
            }
        workplace_summary = self.optional_summary(
            "workplace_location_employment_comparison"
        )
        school_summary = self.optional_summary("school_location_enrollment_comparison")
        return {
            "mode": "ready",
            "geo_opts": _options(
                workplace_summary or school_summary or [],
                "geography_type",
                config=self.config,
                total_label="all_geographies",
            ),
            "student_opts": _options(school_summary or [], "student_type"),
            "workplace_summary": workplace_summary,
            "school_summary": school_summary,
        }

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
            factory=lambda: _filter_col(
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
            factory=lambda: _filter_col(
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
            factory=lambda: _filter_col(
                _filter_col(
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
            factory=lambda: _filter_col(
                _filter_col(
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
