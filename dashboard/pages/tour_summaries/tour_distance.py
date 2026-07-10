"""Tour distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart, selector_row
from dashboard.helpers.category_helpers import (
    column_options,
    nonempty,
    ordered_category_values,
)
from dashboard.helpers.comparison_helpers import (
    build_ab_comparison_row,
    build_ab_comparison_table,
    weighted_average_lookup,
)
from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    ALL_GEOGRAPHY_TYPES_VALUE,
    ALL_WITHIN_LEVEL_VALUE,
    GEOGRAPHY_NAME_SELECTOR_LABEL,
    GEOGRAPHY_TYPE_SELECTOR_LABEL,
    filter_geography,
    filter_geography_level,
    geography_name_options_for_type,
    geography_name_selector_label,
    geography_type_options,
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
                .with_columns(
                    distance_sort_expr("distance_bin").alias("_sort_distance")
                )
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
) -> list[tuple[str, pl.DataFrame]]:
    """Compare average non-mandatory tour distances against the base run."""
    filtered = filter_geography(
        filter_geography_level(data_list, geography_level),
        geography,
    )
    if purpose != "All":
        filtered = [
            (
                label,
                df.with_columns(
                    pl.col("nonmandatory_tour_purpose").cast(pl.Utf8)
                ).filter(pl.col("nonmandatory_tour_purpose") == purpose),
            )
            for label, df in nonempty(filtered)
        ]

    runs = nonempty(filtered)
    if not runs:
        return []

    purpose_values = ordered_category_values(
        runs,
        "nonmandatory_tour_purpose",
        category_id="tour_purpose",
        config=config,
    )
    if not purpose_values:
        return []

    _, base_run_df = runs[0]
    base_lookup = weighted_average_lookup(
        base_run_df,
        category_col="nonmandatory_tour_purpose",
        average_col="average_tour_distance",
        weight_col="tour_count",
    )
    quantity_a_column = "Average Non-Mandatory Tour Distance"
    quantity_b_column = "Base Run Average Non-Mandatory Tour Distance"
    out: list[tuple[str, pl.DataFrame]] = []
    for run_label, run_df in runs:
        run_lookup = weighted_average_lookup(
            run_df,
            category_col="nonmandatory_tour_purpose",
            average_col="average_tour_distance",
            weight_col="tour_count",
        )
        rows = []
        for raw_purpose in purpose_values:
            display_purpose = config.label_value("tour_purpose", raw_purpose)
            rows.append(
                build_ab_comparison_row(
                    keys={"Non-Mandatory Tour Purpose": display_purpose},
                    quantity_a=run_lookup.get(str(raw_purpose)),
                    quantity_b=base_lookup.get(str(raw_purpose)),
                    quantity_a_column=quantity_a_column,
                    quantity_b_column=quantity_b_column,
                )
            )

        table = build_ab_comparison_table(
            rows,
            key_columns=["Non-Mandatory Tour Purpose"],
            quantity_a_column=quantity_a_column,
            quantity_b_column=quantity_b_column,
        )
        if not table.is_empty():
            out.append((run_label, table))
    return out


class TourDistancePage(DashboardPage):
    """Render tour distance distributions and average-distance comparisons."""

    TOTAL_PURPOSE_LABEL = "All Tour Purposes"

    def build_page(self) -> pn.viewable.Viewable:
        """Build the persistent page layout and selector widgets."""
        self._tour_purpose_to_raw: dict[str, str | None] = {}
        self._geo_level_raw_by_label: dict[str, str | None] = {
            ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
        }
        self._geography_raw_by_label: dict[str, str | None] = {
            ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE
        }
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
                name=GEOGRAPHY_TYPE_SELECTOR_LABEL,
                options=[ALL_GEOGRAPHY_TYPES_LABEL],
                value=ALL_GEOGRAPHY_TYPES_LABEL,
            ),
            label=GEOGRAPHY_TYPE_SELECTOR_LABEL,
        )
        self.geography_sel = self.selector(
            "geography",
            widget=pn.widgets.Select(
                name=GEOGRAPHY_NAME_SELECTOR_LABEL,
                options=[ALL_WITHIN_LEVEL_VALUE],
                value=ALL_WITHIN_LEVEL_VALUE,
            ),
            label=GEOGRAPHY_NAME_SELECTOR_LABEL,
        )
        self._distance_section = self.section(
            "tour_distance_distribution",
            selectors=("tour_purpose",),
            render=self.render_distance_section,
        )
        self._average_section = self.section(
            "tour_distance_averages",
            selectors=("geography_level", "geography"),
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
        geography_type_options_list, self._geo_level_raw_by_label = geography_type_options(
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
            include_all_types=True,
        )

        for widget, options in (
            (self.tour_purpose_sel, tour_purpose_options or [self.TOTAL_PURPOSE_LABEL]),
            (self.geo_level_sel, geography_type_options_list or [ALL_GEOGRAPHY_TYPES_LABEL]),
        ):
            widget.options = options
            if widget.value not in options:
                widget.value = options[0]

        geography_type = self.selected_geography_level_raw()
        geography_options, self._geography_raw_by_label = geography_name_options_for_type(
            geography_type,
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
        )
        self.geography_sel.name = geography_name_selector_label(
            geography_type,
            config=self.config,
        )
        self.geography_sel.options = geography_options
        if self.geography_sel.value not in geography_options:
            self.geography_sel.value = geography_options[0]

    def selected_geography_level_raw(self) -> str:
        """Return the raw geography type selected in the display selector."""
        selected = str(self.geo_level_sel.value)
        raw_value = self._geo_level_raw_by_label.get(selected, selected)
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def selected_geography_raw(self) -> str:
        """Return the raw geography id selected in the display selector."""
        selected = str(self.geography_sel.value)
        raw_value = self._geography_raw_by_label.get(selected, selected)
        return ALL_WITHIN_LEVEL_VALUE if raw_value is None else str(raw_value)

    def render_distance_section(self) -> SectionContent:
        """Render the tour distance distribution chart."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._summaries()
        if summaries is None:
            return [self.summary_only_unavailable_card()]

        selected_purpose = str(self.tour_purpose_sel.value)
        raw_purpose = self._tour_purpose_to_raw.get(
            selected_purpose, "all_tour_purposes"
        )
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
            selector_row(self.tour_purpose_sel),
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
        geo_level = self.selected_geography_level_raw()
        geography = self.selected_geography_raw()
        comparison_tables = self.get_filtered_view(
            "average_nonmandatory_tour_distance",
            (geo_level, geography),
            factory=lambda: average_distance_comparison_table(
                nonmandatory_average,
                geo_level,
                geography,
                "All",
                config=self.config,
            ),
        )
        return [
            pn.pane.Markdown("### Average Non-Mandatory Tour Distance vs Base Run"),
            selector_row(self.geo_level_sel, self.geography_sel),
            self.render_average_distance_table(comparison_tables),
        ]

    def render_average_distance_table(
        self, comparison_tables: list[tuple[str, pl.DataFrame]]
    ) -> pn.viewable.Viewable:
        """Render the average-distance comparison table."""
        return data_table(comparison_tables)


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
