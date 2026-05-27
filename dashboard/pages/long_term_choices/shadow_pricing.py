"""Shadow pricing validation page."""

from __future__ import annotations

import math

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart
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
    include_all_geographies: bool = False,
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    if config is not None and col == "geography_type":
        if include_all_geographies:
            detail_vals = sorted(v for v in vals if v != "all_geographies")
            return ["all_geographies"] + detail_vals if "all_geographies" in vals else detail_vals
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


def _filter_col_exact(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    value: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Utf8)).filter(pl.col(col) == value)
        out.append((label, df))
    return out


def _format_percent_error_table(df: pl.DataFrame) -> pl.DataFrame:
    if "percent_error" not in df.columns:
        return df
    return df.with_columns(
        pl.col("percent_error")
        .map_elements(
            lambda value: (
                ""
                if value is None
                or (isinstance(value, float) and not math.isfinite(value))
                else f"{float(value):.2f}%"
            ),
            return_dtype=pl.Utf8,
        )
        .alias("percent_error")
    )


class ShadowPricingPage(DashboardPage):
    def _maz_tables_disabled(self) -> bool:
        return str(self.geo_level_sel.value).lower() == "maz" and not self.config.enable_maz_geographies

    def _all_geographies_distribution_card(self, *, subject: str) -> pn.Card:
        return self.data_not_available_card(
            title=f"{subject} Residual Distribution Unavailable",
            detail=(
                f'The residual for "All Geographies" is a point mass that cannot be plotted as a '
                f'distribution. Please refer to the table below for the {subject.lower()} shadow '
                f'pricing values for "All Geographies".'
            ),
        )

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
                "geo_opts": ["all_geographies"],
                "student_opts": ["All"],
            }
        workplace_summary = self.optional_summary("workplace_shadow_pricing_residuals")
        school_summary = self.optional_summary("school_shadow_pricing_residuals")
        workplace_hist = self.optional_summary("workplace_shadow_pricing_residual_histogram")
        school_hist = self.optional_summary("school_shadow_pricing_residual_histogram")
        return {
            "mode": "ready",
            "geo_opts": _options(
                workplace_hist or school_hist or workplace_summary or school_summary or [],
                "geography_type",
                config=self.config,
                total_label="all_geographies",
                include_all_geographies=True,
            ),
            "student_opts": _options(school_hist or school_summary or [], "student_type"),
            "workplace_summary": workplace_summary,
            "school_summary": school_summary,
            "workplace_hist": workplace_hist,
            "school_hist": school_hist,
        }

    def render_workplace_plot(self) -> SectionContent:
        if self._current_data["mode"] == "no_runs":
            return [pn.pane.Markdown("No runs loaded.")]
        workplace_hist = self._current_data["workplace_hist"]
        if workplace_hist is None:
            return [
                self.data_not_available_card(
                    detail="The workplace shadow pricing residual histogram summary is unavailable.",
                    missing_items=["workplace_shadow_pricing_residual_histogram"],
                )
            ]
        geo_level = str(self.geo_level_sel.value)
        if geo_level == "all_geographies":
            return [
                pn.pane.Markdown("### Workplace Shadow Pricing"),
                pn.Row(
                    pn.pane.Markdown("**Geography Level:**"),
                    self.geo_level_sel,
                ),
                self._all_geographies_distribution_card(subject="Workplace"),
            ]
        workplace_data = self.get_filtered_view(
            "shadow_pricing_workplace_hist",
            geo_level,
            factory=lambda: _filter_col(
                workplace_hist,
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

    def render_workplace_table(self) -> SectionContent:
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
                [
                    (
                        label,
                        _format_percent_error_table(
                            df.select(
                                [
                                    "geography_id",
                                    "target_count",
                                    "modeled_count",
                                    "residual_count",
                                    "absolute_residual_count",
                                    "percent_error",
                                ]
                            )
                        ),
                    )
                    for label, df in workplace_data
                ],
                "Workplace Shadow Pricing Residuals by Geography",
            )
        ]

    def render_school_plot(self) -> SectionContent:
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
        geo_level = str(self.geo_level_sel.value)
        student_type = str(self.student_type_sel.value)
        if geo_level == "all_geographies":
            return [
                pn.pane.Markdown("### School Shadow Pricing"),
                pn.Row(
                    pn.pane.Markdown("**Student Type:**"),
                    self.student_type_sel,
                ),
                self._all_geographies_distribution_card(subject="School"),
            ]
        school_data = self.get_filtered_view(
            "shadow_pricing_school_hist",
            (geo_level, student_type),
            factory=lambda: _filter_col_exact(
                _filter_col(
                    school_hist,
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

    def render_school_table(self) -> SectionContent:
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
        geo_level = str(self.geo_level_sel.value)
        student_type = str(self.student_type_sel.value)
        school_data = self.get_filtered_view(
            "shadow_pricing_school",
            (geo_level, student_type),
            factory=lambda: _filter_col_exact(
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
            data_table(
                [
                    (
                        label,
                        _format_percent_error_table(
                            df.select(
                                [
                                    "geography_id",
                                    "student_type",
                                    "target_count",
                                    "modeled_count",
                                    "residual_count",
                                    "absolute_residual_count",
                                    "percent_error",
                                ]
                            )
                        ),
                    )
                    for label, df in school_data
                ],
                "School Shadow Pricing Residuals by Geography",
            )
        ]


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
