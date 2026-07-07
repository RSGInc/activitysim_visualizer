"""Shadow pricing validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart, selector_row
from dashboard.helpers.comparison_helpers import format_percent_error_table
from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    GEOGRAPHY_TYPE_SELECTOR_LABEL,
    filter_geography_level,
    geography_column_options,
    geography_type_options,
    is_all_geographies,
    normalize_geography_level_value,
    normalize_geography_data,
)
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition


def filter_student_type(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    student_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter school-shadow-pricing summaries to one exact student type."""
    if not data_list:
        return []
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in data_list:
        if df is None or len(df) == 0:
            continue
        filtered = df
        if "student_type" in filtered.columns:
            filtered = filtered.with_columns(pl.col("student_type").cast(pl.Utf8))
            if student_type == "All":
                explicit_all = filtered.filter(pl.col("student_type") == "All")
                if len(explicit_all) > 0:
                    filtered = explicit_all
                else:
                    group_cols = [
                        column
                        for column in (
                            "geography_level",
                            "geography_type",
                            "geography",
                            "geography_id",
                        )
                        if column in filtered.columns
                    ]
                    agg_exprs: list[pl.Expr] = []
                    if "target_count" in filtered.columns:
                        agg_exprs.append(pl.col("target_count").sum().alias("target_count"))
                    if "modeled_count" in filtered.columns:
                        agg_exprs.append(pl.col("modeled_count").sum().alias("modeled_count"))
                    if "residual_count" in filtered.columns:
                        agg_exprs.append(pl.col("residual_count").sum().alias("residual_count"))
                    if "absolute_residual_count" in filtered.columns:
                        agg_exprs.append(
                            pl.col("absolute_residual_count").sum().alias("absolute_residual_count")
                        )
                    if "geography_count" in filtered.columns:
                        agg_exprs.append(pl.col("geography_count").sum().alias("geography_count"))
                    filtered = (
                        filtered.group_by(group_cols)
                        .agg(agg_exprs)
                        .with_columns(
                            pl.lit("All").alias("student_type"),
                            pl.when(pl.col("target_count") != 0)
                            .then(pl.col("residual_count") / pl.col("target_count") * 100.0)
                            .otherwise(None)
                            .alias("percent_error")
                            if {"target_count", "residual_count"}.issubset(filtered.columns)
                            else pl.lit(None).alias("percent_error")
                        )
                    )
            else:
                filtered = filtered.filter(pl.col("student_type") == student_type)
        out.append((label, filtered))
    return out


class ShadowPricingPage(DashboardPage):
    """Render workplace and school shadow-pricing residual diagnostics."""

    def _maz_tables_disabled(self) -> bool:
        """Return whether MAZ tables should be hidden by configuration."""
        return self.selected_geography_level_raw().lower() == "maz" and not self.config.enable_maz_geographies

    def _all_geographies_distribution_card(self, *, subject: str) -> pn.Card:
        """Explain the aggregate-level histogram special case."""
        return self.data_not_available_card(
            title=f"{subject} Residual Distribution Unavailable",
            detail=(
                f'The residual for "All Geographies" is a point mass that cannot be plotted as a '
                f'distribution. Please refer to the table below for the {subject.lower()} shadow '
                'pricing values for "All Geographies".'
            ),
        )

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page with geography and student selectors."""
        self._current_data: dict[str, object] = {}
        self._geo_level_raw_by_label: dict[str, str | None] = {
            ALL_GEOGRAPHY_TYPES_LABEL: "all_geographies"
        }
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_TYPE_SELECTOR_LABEL,
                options=[ALL_GEOGRAPHY_TYPES_LABEL],
                value=ALL_GEOGRAPHY_TYPES_LABEL,
            ),
            label=GEOGRAPHY_TYPE_SELECTOR_LABEL,
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
            render=self.render_workplace_plot_section,
        )
        self._workplace_table_section = self.section(
            "workplace_table",
            selectors=("geography_level",),
            render=self.render_workplace_table_section,
        )
        self._school_plot_section = self.section(
            "school_plot",
            selectors=("geography_level", "student_type"),
            render=self.render_school_plot_section,
        )
        self._school_table_section = self.section(
            "school_table",
            selectors=("geography_level", "student_type"),
            render=self.render_school_table_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Shadow Pricing"),
            self.new_section(self._workplace_plot_section, self._workplace_table_section),
            self.new_section(self._school_plot_section, self._school_table_section),
        )

    def sync_controls(self) -> None:
        """Refresh summary state and reconcile selector domains."""
        self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self._geo_level_raw_by_label = self._current_data["geo_raw_by_label"]
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

        student_opts = self._current_data["student_opts"]
        self.student_type_sel.options = student_opts
        if self.student_type_sel.value not in student_opts:
            self.student_type_sel.value = student_opts[0]

    def selected_geography_level_raw(self) -> str:
        """Return the raw geography type selected in the display selector."""
        selected = str(self.geo_level_sel.value)
        raw_value = self._geo_level_raw_by_label.get(selected, selected)
        return "all_geographies" if raw_value is None else normalize_geography_level_value(str(raw_value))

    def _collect_data(self) -> dict[str, object]:
        """Collect and normalize every summary used on the page."""
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": [ALL_GEOGRAPHY_TYPES_LABEL],
                "geo_raw_by_label": {ALL_GEOGRAPHY_TYPES_LABEL: "all_geographies"},
                "student_opts": ["All"],
            }

        workplace_summary = normalize_geography_data(
            self.optional_summary("workplace_shadow_pricing_residuals")
        )
        school_summary = normalize_geography_data(
            self.optional_summary("school_shadow_pricing_residuals")
        )
        workplace_hist = normalize_geography_data(
            self.optional_summary("workplace_shadow_pricing_residual_histogram")
        )
        school_hist = normalize_geography_data(
            self.optional_summary("school_shadow_pricing_residual_histogram")
        )
        geo_opts, geo_raw_by_label = geography_type_options(
            workplace_hist or school_hist or workplace_summary or school_summary,
            config=self.config,
            include_all_types=False,
            include_disabled_maz=True,
        )
        return {
            "mode": "ready",
            "geo_opts": geo_opts or [ALL_GEOGRAPHY_TYPES_LABEL],
            "geo_raw_by_label": geo_raw_by_label or {ALL_GEOGRAPHY_TYPES_LABEL: "all_geographies"},
            "student_opts": geography_column_options(
                school_hist or school_summary,
                "student_type",
                total_label="All",
            ),
            "workplace_summary": workplace_summary or None,
            "school_summary": school_summary or None,
            "workplace_hist": workplace_hist or None,
            "school_hist": school_hist or None,
        }

    def render_workplace_plot_section(self) -> SectionContent:
        """Render the workplace residual distribution."""
        if self._current_data["mode"] == "no_runs":
            return [self.no_runs_message()]

        workplace_hist = self._current_data["workplace_hist"]
        if workplace_hist is None:
            return [
                self.data_not_available_card(
                    detail="The workplace shadow pricing residual histogram summary is unavailable.",
                    missing_items=["workplace_shadow_pricing_residual_histogram"],
                )
            ]

        geo_level = self.selected_geography_level_raw()
        if is_all_geographies(geo_level):
            return [
                pn.pane.Markdown("### Workplace Shadow Pricing"),
                selector_row(self.geo_level_sel),
                self._all_geographies_distribution_card(subject="Workplace"),
            ]

        workplace_data = self.get_filtered_view(
            "shadow_pricing_workplace_hist",
            geo_level,
            factory=lambda: filter_geography_level(workplace_hist, geo_level),
        )
        if not any("bin_start" in df.columns for _, df in workplace_data):
            return [
                pn.pane.Markdown("### Workplace Shadow Pricing"),
                selector_row(self.geo_level_sel),
                self._all_geographies_distribution_card(subject="Workplace"),
            ]
        return [
            pn.pane.Markdown("### Workplace Shadow Pricing"),
            selector_row(self.geo_level_sel),
            density_chart(
                workplace_data,
                x_col="bin_start",
                y_col="geography_count",
                title="Workplace Residual Distribution",
                xaxis_title="Residual (Modeled - Target)",
                yaxis_title="Geographies",
                normalize=False,
                as_percent=self.as_percent,
            ),
        ]

    def render_workplace_table_section(self) -> SectionContent:
        """Render the workplace residual table."""
        if self._current_data["mode"] != "ready":
            return []

        workplace_summary = self._current_data["workplace_summary"]
        if workplace_summary is None:
            return []
        if self._maz_tables_disabled():
            return [
                self.data_not_available_card(
                    title="Workplace Shadow Pricing Residuals by Geography",
                    detail="MAZ-level shadow pricing tables are hidden when visualizer.enable_maz_geographies is false.",
                )
            ]

        geo_level = self.selected_geography_level_raw()
        workplace_data = self.get_filtered_view(
            "shadow_pricing_workplace",
            geo_level,
            factory=lambda: filter_geography_level(workplace_summary, geo_level),
        )
        return [
            data_table(
                [(label, self.render_workplace_table(df)) for label, df in workplace_data],
                "Workplace Shadow Pricing Residuals by Geography",
            )
        ]

    def render_workplace_table(self, df: pl.DataFrame) -> pl.DataFrame:
        """Select and format workplace residual columns for display."""
        geography_col = "geography_id" if "geography_id" in df.columns else "geography"
        return format_percent_error_table(
            df.select(
                [
                    geography_col,
                    "target_count",
                    "modeled_count",
                    "residual_count",
                    "absolute_residual_count",
                    "percent_error",
                ]
            ).rename({geography_col: "geography_id"})
        )

    def render_school_plot_section(self) -> SectionContent:
        """Render the school residual distribution for one student type."""
        if self._current_data["mode"] != "ready":
            return []

        school_hist = self._current_data["school_hist"]
        if school_hist is None:
            return [
                self.data_not_available_card(
                    detail="The school shadow pricing residual histogram summary is unavailable.",
                    missing_items=["school_shadow_pricing_residual_histogram"],
                )
            ]

        geo_level = self.selected_geography_level_raw()
        student_type = str(self.student_type_sel.value)
        if is_all_geographies(geo_level):
            return [
                pn.pane.Markdown("### School Shadow Pricing"),
                selector_row(self.student_type_sel),
                self._all_geographies_distribution_card(subject="School"),
            ]

        school_data = self.get_filtered_view(
            "shadow_pricing_school_hist",
            (geo_level, student_type),
            factory=lambda: filter_student_type(
                filter_geography_level(school_hist, geo_level),
                student_type,
            ),
        )
        if not any("bin_start" in df.columns for _, df in school_data):
            return [
                pn.pane.Markdown("### School Shadow Pricing"),
                selector_row(self.student_type_sel),
                self._all_geographies_distribution_card(subject="School"),
            ]
        return [
            pn.pane.Markdown("### School Shadow Pricing"),
            selector_row(self.student_type_sel),
            density_chart(
                school_data,
                x_col="bin_start",
                y_col="geography_count",
                title="School Residual Distribution",
                xaxis_title="Residual (Modeled - Target)",
                yaxis_title="Geographies",
                normalize=False,
                as_percent=self.as_percent,
            ),
        ]

    def render_school_table_section(self) -> SectionContent:
        """Render school residuals for the selected geography level and student type."""
        if self._current_data["mode"] != "ready":
            return []

        school_summary = self._current_data["school_summary"]
        if school_summary is None:
            return []
        if self._maz_tables_disabled():
            return [
                self.data_not_available_card(
                    title="School Shadow Pricing Residuals by Geography",
                    detail="MAZ-level shadow pricing tables are hidden when visualizer.enable_maz_geographies is false.",
                )
            ]

        geo_level = self.selected_geography_level_raw()
        student_type = str(self.student_type_sel.value)
        school_data = self.get_filtered_view(
            "shadow_pricing_school",
            (geo_level, student_type),
            factory=lambda: filter_student_type(
                filter_geography_level(school_summary, geo_level),
                student_type,
            ),
        )
        return [
            data_table(
                [(label, self.render_school_table(df)) for label, df in school_data],
                "School Shadow Pricing Residuals by Geography",
            )
        ]

    def render_school_table(self, df: pl.DataFrame) -> pl.DataFrame:
        """Select and format school residual columns for display."""
        geography_col = "geography_id" if "geography_id" in df.columns else "geography"
        return format_percent_error_table(
            df.select(
                [
                    geography_col,
                    "student_type",
                    "target_count",
                    "modeled_count",
                    "residual_count",
                    "absolute_residual_count",
                    "percent_error",
                ]
            ).rename({geography_col: "geography_id"})
        )


PAGE = DashboardPageDefinition(
    page_id="shadow_pricing",
    title="Shadow Pricing",
    group_id="long_term_choices",
    order=28,
    page_cls=ShadowPricingPage,
    required_summary_ids=(
        "workplace_shadow_pricing_residuals",
        "workplace_shadow_pricing_residual_histogram",
        "school_shadow_pricing_residuals",
        "school_shadow_pricing_residual_histogram",
    ),
)

ShadowPricingPage.definition = PAGE
