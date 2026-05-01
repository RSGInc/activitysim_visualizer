"""Shadow pricing validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, scatter_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportPartDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    *,
    total_label: str = "All",
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    return [total_label] + sorted(v for v in vals if v != total_label)


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
    def __init__(self, state, config: Config) -> None:
        super().__init__("Shadow Pricing", state, config)

        workplace_data = self.state.get_summary_table_set(
            "workplace_location_employment_comparison",
            "weighted",
        )
        school_data = self.state.get_summary_table_set(
            "school_location_enrollment_comparison",
            "weighted",
        )
        geo_opts = _options(workplace_data or school_data or [], "geography_type")
        student_opts = _options(school_data or [], "student_type")

        self.geo_level_sel = pn.widgets.Select(
            name="Geography Level",
            options=geo_opts,
            value=geo_opts[0],
        )
        self._watch_widget(self.geo_level_sel)

        self.student_type_sel = pn.widgets.Select(
            name="Student Type",
            options=student_opts,
            value=student_opts[0],
        )
        self._watch_widget(self.student_type_sel)

        self._workplace_plot_section = self.new_section()
        self._workplace_table_section = self.new_section()
        self._school_plot_section = self.new_section()
        self._school_table_section = self.new_section()
        self._workplace_section = self.new_section(
            self._workplace_plot_section,
            self._workplace_table_section,
        )
        self._school_section = self.new_section(
            self._school_plot_section,
            self._school_table_section,
        )
        self.view = self.new_section(
            pn.pane.Markdown("## Shadow Pricing"),
            self._workplace_section,
            self._school_section,
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._workplace_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._school_section.objects = []
            return

        workplace_summary = self.optional_summary(
            "workplace_location_employment_comparison"
        )
        school_summary = self.optional_summary("school_location_enrollment_comparison")

        geo_opts = _options(workplace_summary or school_summary or [], "geography_type")
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]
        geo_level = self.geo_level_sel.value

        student_opts = _options(school_summary or [], "student_type")
        self.student_type_sel.options = student_opts
        if self.student_type_sel.value not in student_opts:
            self.student_type_sel.value = student_opts[0]
        student_type = self.student_type_sel.value

        if workplace_summary is not None:
            workplace_data = self.get_filtered_view(
                "shadow_pricing_workplace",
                geo_level,
                factory=lambda: _filter_col(
                    workplace_summary,
                    "geography_type",
                    geo_level,
                ),
            )
            workplace_plot_views: list[pn.viewable.Viewable] = [
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
            workplace_table_views = [
                data_table(
                    workplace_data,
                    "Workplace Employment Comparison by Geography",
                )
            ]
        else:
            workplace_plot_views = [
                self.data_not_available_card(
                    detail="The workplace employment comparison summary is unavailable.",
                    missing_items=["workplace_location_employment_comparison"],
                )
            ]
            workplace_table_views = []
        self._workplace_plot_section.objects = workplace_plot_views
        self._workplace_table_section.objects = workplace_table_views

        if school_summary is not None:
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
            school_plot_views = [
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
            school_table_views = [
                data_table(school_data, "School Enrollment Comparison by Geography")
            ]
        else:
            school_plot_views = [
                self.data_not_available_card(
                    detail="The school enrollment comparison summary is unavailable.",
                    missing_items=["school_location_enrollment_comparison"],
                )
            ]
            school_table_views = []
        self._school_plot_section.objects = school_plot_views
        self._school_table_section.objects = school_table_views


PAGE = DashboardPageDefinition(
    page_id="shadow_pricing",
    title="Shadow Pricing",
    group_id="long_term_choices",
    child_id="shadow_pricing",
    order=28,
    controller_cls=ShadowPricingPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="geography_level",
            widget_attr="geo_level_sel",
            label="Geography Level",
        ),
        PageSelectorDefinition(
            selector_id="student_type",
            widget_attr="student_type_sel",
            label="Student Type",
        ),
    ),
    export_parts=(
        PageExportPartDefinition(
            part_id="workplace_plot",
            view_attr="_workplace_plot_section",
            selector_ids=("geography_level",),
        ),
        PageExportPartDefinition(
            part_id="workplace_table",
            view_attr="_workplace_table_section",
            selector_ids=("geography_level",),
        ),
        PageExportPartDefinition(
            part_id="school_plot",
            view_attr="_school_plot_section",
            selector_ids=("geography_level", "student_type"),
        ),
        PageExportPartDefinition(
            part_id="school_table",
            view_attr="_school_table_section",
            selector_ids=("geography_level", "student_type"),
        ),
    ),
    required_summary_ids=(
        "workplace_location_employment_comparison",
        "school_location_enrollment_comparison",
    ),
)

ShadowPricingPage.definition = PAGE
