"""Tour distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_options, nonempty_runs
from dashboard.pages._shared.purposes import raw_tour_purpose, tour_purpose_options
from dashboard.pages._shared.time_distance import distance_bin_sort_expr

GEO_LEVEL_COL = "geography_level"


def tour_distance_chart_data(data_list: list[tuple[str, pl.DataFrame]], purpose: str):
    out = []
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8)).filter(
            pl.col("tour_purpose") == purpose
        )
        out.append(
            (
                label,
                df.select(pl.col("distance_bin"), pl.col("tour_count"))
                .with_columns(
                    distance_bin_sort_expr("distance_bin").alias("_sort_distance")
                )
                .sort("_sort_distance")
                .drop("_sort_distance"),
            )
        )
    return out


def avg_distance_table_data(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
    purpose_col: str,
    purpose: str,
):
    out = []
    for label, df in nonempty_runs(data_list):
        if GEO_LEVEL_COL in df.columns and geo_level != "All":
            df = df.with_columns(pl.col(GEO_LEVEL_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_LEVEL_COL) == geo_level
            )
        if purpose_col in df.columns and purpose != "All":
            df = df.with_columns(pl.col(purpose_col).cast(pl.Utf8)).filter(
                pl.col(purpose_col) == purpose
            )
        out.append((label, df))
    return out


class TourDistancePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        dist_data = self.state.get_summary_table_set(
            "tour_distance_by_tour_purpose", "weighted"
        )
        mand_data = self.state.get_summary_table_set(
            "average_mandatory_tour_distance_by_purpose_and_geography", "weighted"
        )
        nonmand_data = self.state.get_summary_table_set(
            "average_nonmandatory_tour_distance_by_purpose_and_geography", "weighted"
        )
        self.tour_purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=tour_purpose_options(dist_data or []),
                value=tour_purpose_options(dist_data or [])[0],
            ),
            label="Tour Purpose",
        )
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=column_options(mand_data or [], GEO_LEVEL_COL),
                value=column_options(mand_data or [], GEO_LEVEL_COL)[0],
            ),
            label="Geography Level",
        )
        self.mand_purpose_sel = self.selector(
            "mandatory_tour_purpose",
            widget=pn.widgets.Select(
                name="Mandatory Tour Purpose",
                options=column_options(mand_data or [], "mandatory_tour_purpose"),
                value=column_options(mand_data or [], "mandatory_tour_purpose")[0],
            ),
            label="Mandatory Tour Purpose",
        )
        self.nonmand_purpose_sel = self.selector(
            "nonmandatory_tour_purpose",
            widget=pn.widgets.Select(
                name="Non-Mandatory Tour Purpose",
                options=column_options(nonmand_data or [], "nonmandatory_tour_purpose"),
                value=column_options(nonmand_data or [], "nonmandatory_tour_purpose")[0],
            ),
            label="Non-Mandatory Tour Purpose",
        )
        self._distance_section = self.section(
            "tour_distance_distribution",
            selectors=("tour_purpose",),
            render=self.render_distance,
        )
        self._average_section = self.section(
            "tour_distance_averages",
            selectors=(
                "geography_level",
                "mandatory_tour_purpose",
                "nonmandatory_tour_purpose",
            ),
            render=self.render_averages,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Distance"),
            self._distance_section,
            self._average_section,
        )

    def _summaries(self):
        return self.require_summaries(*self.required_summary_ids)

    def sync_controls(self) -> None:
        summaries = self._summaries()
        if summaries is None:
            return
        dist_list = summaries["tour_distance_by_tour_purpose"]
        mand_list = summaries[
            "average_mandatory_tour_distance_by_purpose_and_geography"
        ]
        nonmand_list = summaries[
            "average_nonmandatory_tour_distance_by_purpose_and_geography"
        ]
        for widget, opts in [
            (self.tour_purpose_sel, tour_purpose_options(dist_list)),
            (self.geo_level_sel, column_options(mand_list, GEO_LEVEL_COL)),
            (
                self.mand_purpose_sel,
                column_options(mand_list, "mandatory_tour_purpose"),
            ),
            (
                self.nonmand_purpose_sel,
                column_options(nonmand_list, "nonmandatory_tour_purpose"),
            ),
        ]:
            widget.options = opts
            if widget.value not in opts:
                widget.value = opts[0]

    def render_distance(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]
        summaries = self._summaries()
        if summaries is None:
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
        tour_purpose = self.tour_purpose_sel.value
        distance_data = self.get_filtered_view(
            "tour_distance",
            raw_tour_purpose(tour_purpose),
            factory=lambda: tour_distance_chart_data(
                summaries["tour_distance_by_tour_purpose"],
                raw_tour_purpose(tour_purpose),
            ),
        )
        return [
            pn.pane.Markdown("### Tour Distance Distribution"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.tour_purpose_sel),
            density_chart(
                distance_data,
                "distance_bin",
                "tour_count",
                f"Tour Distance Distribution - {tour_purpose}",
                "Distance (miles)",
                normalize=False,
                yaxis_title="Tours",
                as_percent=self.as_percent,
            ),
        ]

    def render_averages(self):
        summaries = self._summaries()
        if summaries is None:
            return []
        geo_level = self.geo_level_sel.value
        mand_purpose = self.mand_purpose_sel.value
        nonmand_purpose = self.nonmand_purpose_sel.value
        mand_avg_data = self.get_filtered_view(
            "average_mandatory_tour_distance",
            (geo_level, mand_purpose),
            factory=lambda: avg_distance_table_data(
                summaries["average_mandatory_tour_distance_by_purpose_and_geography"],
                geo_level,
                "mandatory_tour_purpose",
                mand_purpose,
            ),
        )
        nonmand_avg_data = self.get_filtered_view(
            "average_nonmandatory_tour_distance",
            (geo_level, nonmand_purpose),
            factory=lambda: avg_distance_table_data(
                summaries[
                    "average_nonmandatory_tour_distance_by_purpose_and_geography"
                ],
                geo_level,
                "nonmandatory_tour_purpose",
                nonmand_purpose,
            ),
        )
        return [
            pn.pane.Markdown("### Average Tour Distance by Geography"),
            pn.Row(pn.pane.Markdown("**Geography Level:**"), self.geo_level_sel),
            pn.Row(
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Mandatory Tour Purpose:**"),
                        self.mand_purpose_sel,
                    ),
                    data_table(mand_avg_data, "Average Mandatory Tour Distance"),
                ),
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Non-Mandatory Tour Purpose:**"),
                        self.nonmand_purpose_sel,
                    ),
                    data_table(nonmand_avg_data, "Average Non-Mandatory Tour Distance"),
                ),
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_distance",
    title="Tour Distance",
    group_id="tour_summaries",
    order=44,
    page_cls=TourDistancePage,
    required_summary_ids=(
        "tour_distance_by_tour_purpose",
        "average_mandatory_tour_distance_by_purpose_and_geography",
        "average_nonmandatory_tour_distance_by_purpose_and_geography",
    ),
)

TourDistancePage.definition = PAGE
