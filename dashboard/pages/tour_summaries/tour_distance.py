"""Tour distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart
from dashboard.helpers.category_helpers import (
    column_options,
    nonempty,
    ordered_category_values,
)
from dashboard.helpers.comparison_helpers import (
    build_base_run_percent_difference_table,
    weighted_average_lookup,
)
from dashboard.helpers.geography_helpers import (
    filter_geography,
    filter_geography_level,
    geography_level_options,
    geography_options_for_level,
    normalize_geography_data,
)
from dashboard.helpers.time_distance_helpers import distance_sort_expr
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition


def tour_distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Prepare the distance distribution for one tour purpose."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8)).filter(
            pl.col("tour_purpose") == purpose
        )
        out.append(
            (
                label,
                filtered.select(
                    pl.col("distance_bin").cast(pl.Utf8),
                    pl.col("tour_count"),
                )
                .with_columns(distance_sort_expr("distance_bin").alias("_sort_distance"))
                .sort("_sort_distance")
                .drop("_sort_distance"),
            )
        )
    return out


def average_distance_comparison_table(
    data_list: list[tuple[str, pl.DataFrame]],
    geography_level: str,
    geography: str,
    purpose: str,
    *,
    config,
) -> pl.DataFrame:
    """Compare average non-mandatory tour distances against the base run."""
    filtered = filter_geography(
        filter_geography_level(data_list, geography_level),
        geography,
    )
    if purpose != "All":
        filtered = [
            (
                label,
                df.with_columns(pl.col("nonmandatory_tour_purpose").cast(pl.Utf8)).filter(
                    pl.col("nonmandatory_tour_purpose") == purpose
                ),
            )
            for label, df in nonempty(filtered)
        ]

    runs = nonempty(filtered)
    if not runs:
        return pl.DataFrame()

    purpose_values = ordered_category_values(
        runs,
        "nonmandatory_tour_purpose",
        category_id="tour_purpose",
        config=config,
    )
    if not purpose_values:
        return pl.DataFrame()

    run_labels = [label for label, _ in runs]
    base_run_label = run_labels[0]
    row_values: dict[str, dict[str, float | None]] = {}
    for raw_purpose in purpose_values:
        display_purpose = config.label_value("tour_purpose", raw_purpose)
        row_values[display_purpose] = {}
        for run_label, run_df in runs:
            row_values[display_purpose][run_label] = weighted_average_lookup(
                run_df,
                category_col="nonmandatory_tour_purpose",
                average_col="average_tour_distance",
                weight_col="tour_count",
            ).get(str(raw_purpose))

    return build_base_run_percent_difference_table(
        run_labels=run_labels,
        base_run_label=base_run_label,
        row_header="Non-Mandatory Tour Purpose",
        row_values=row_values,
    )


class TourDistancePage(DashboardPage):
    """Render tour distance distributions and average-distance comparisons."""
    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        """Build the persistent page layout and selector widgets."""
        self._tour_purpose_to_raw: dict[str, str | None] = {}
        self._nonmandatory_purpose_to_raw: dict[str, str | None] = {}
        self.tour_purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=[self.TOTAL_PURPOSE_LABEL],
                value=self.TOTAL_PURPOSE_LABEL,
            ),
            label="Tour Purpose",
        )
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=["Total"],
                value="Total",
            ),
            label="Geography Level",
        )
        self.geography_sel = self.selector(
            "geography",
            widget=pn.widgets.Select(
                name="Geography",
                options=[self.TOTAL_PURPOSE_LABEL],
                value=self.TOTAL_PURPOSE_LABEL,
            ),
            label="Geography",
        )
        self.nonmandatory_purpose_sel = self.selector(
            "nonmandatory_tour_purpose",
            widget=pn.widgets.Select(
                name="Non-Mandatory Tour Purpose",
                options=["All"],
                value="All",
            ),
            label="Non-Mandatory Tour Purpose",
        )
        self._distance_section = self.section(
            "tour_distance_distribution",
            selectors=("tour_purpose",),
            render=self.render_distance_section,
        )
        self._average_section = self.section(
            "tour_distance_averages",
            selectors=("geography_level", "geography", "nonmandatory_tour_purpose"),
            render=self.render_average_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Distance"),
            self._distance_section,
            self._average_section,
        )

    def _summaries(self) -> dict[str, object] | None:
        """Return the required summary bundle for this page."""
        return self.require_summaries(*self.required_summary_ids)

    def sync_controls(self) -> None:
        """Recompute selector domains from the current summary tables."""
        summaries = self._summaries()
        if summaries is None:
            return

        distance_summary = summaries["tour_distance_by_tour_purpose"]
        nonmandatory_average = normalize_geography_data(
            summaries["average_nonmandatory_tour_distance_by_purpose_and_geography"]
        )
        mandatory_average = normalize_geography_data(
            summaries["average_mandatory_tour_distance_by_purpose_and_geography"]
        )

        tour_purpose_options, self._tour_purpose_to_raw = column_options(
            distance_summary,
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_distance",
                "tour_distance_by_tour_purpose",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        nonmandatory_options, self._nonmandatory_purpose_to_raw = column_options(
            nonmandatory_average,
            "nonmandatory_tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_distance",
                "average_nonmandatory_tour_distance_by_purpose_and_geography",
                "nonmandatory_tour_purpose",
                self.weighting_key,
            ),
            total_raw="All",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        geography_level_options_list = geography_level_options(
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
            total_label="Total",
        )
        geography_options = geography_options_for_level(
            str(self.geo_level_sel.value),
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
        )

        for widget, options in (
            (self.tour_purpose_sel, tour_purpose_options or [self.TOTAL_PURPOSE_LABEL]),
            (self.nonmandatory_purpose_sel, nonmandatory_options or [self.TOTAL_PURPOSE_LABEL]),
            (self.geo_level_sel, geography_level_options_list or ["Total"]),
        ):
            widget.options = options
            if widget.value not in options:
                widget.value = options[0]

        geography_options = geography_options_for_level(
            str(self.geo_level_sel.value),
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
        )
        self.geography_sel.options = geography_options
        if self.geography_sel.value not in geography_options:
            self.geography_sel.value = geography_options[0]

    def render_distance_section(self) -> SectionContent:
        """Render the tour distance distribution chart."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._summaries()
        if summaries is None:
            return [self.summary_only_unavailable_card()]

        selected_purpose = str(self.tour_purpose_sel.value)
        raw_purpose = self._tour_purpose_to_raw.get(selected_purpose, "all_tour_purposes")
        distance_data = self.get_filtered_view(
            "tour_distance",
            raw_purpose,
            factory=lambda: tour_distance_chart_data(
                summaries["tour_distance_by_tour_purpose"],
                str(raw_purpose),
            ),
        )
        return [
            pn.pane.Markdown("### Tour Distance Distribution"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.tour_purpose_sel),
            self.render_distance_chart(distance_data, selected_purpose),
        ]

    def render_distance_chart(
        self,
        distance_data: list[tuple[str, pl.DataFrame]],
        display_purpose: str,
    ) -> pn.viewable.Viewable:
        """Render the distance distribution chart for one selected purpose."""
        return density_chart(
            distance_data,
            "distance_bin",
            "tour_count",
            f"Tour Distance Distribution - {display_purpose}",
            "Distance (miles)",
            normalize=False,
            yaxis_title="Tours",
            as_percent=self.as_percent,
        )

    def render_average_section(self) -> SectionContent:
        """Render the average non-mandatory distance comparison table."""
        summaries = self._summaries()
        if summaries is None:
            return []

        nonmandatory_average = normalize_geography_data(
            summaries["average_nonmandatory_tour_distance_by_purpose_and_geography"]
        )
        geo_level = str(self.geo_level_sel.value)
        geography = str(self.geography_sel.value)
        raw_purpose = str(
            self._nonmandatory_purpose_to_raw.get(
                str(self.nonmandatory_purpose_sel.value),
                self.nonmandatory_purpose_sel.value,
            )
        )
        comparison_df = self.get_filtered_view(
            "average_nonmandatory_tour_distance",
            (geo_level, geography, raw_purpose),
            factory=lambda: average_distance_comparison_table(
                nonmandatory_average,
                geo_level,
                geography,
                raw_purpose,
                config=self.config,
            ),
        )
        return [
            pn.pane.Markdown("### Average Tour Distance by Geography"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
                pn.pane.Markdown("**Geography:**"),
                self.geography_sel,
            ),
            pn.Column(
                pn.Row(
                    pn.pane.Markdown("**Non-Mandatory Tour Purpose:**"),
                    self.nonmandatory_purpose_sel,
                ),
                self.render_average_distance_table(comparison_df),
            ),
        ]

    def render_average_distance_table(self, comparison_df: pl.DataFrame) -> pn.viewable.Viewable:
        """Render the average-distance comparison table."""
        return data_table(
            [("Comparison", comparison_df)],
            "Average Non-Mandatory Tour Distance vs Base Run",
        )


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
