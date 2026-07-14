"""Tour distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import data_table, selector_row
from dashboard.data_access import RunTables
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
from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard.helpers.time_distance_helpers import distance_sort_expr
from dashboard import DashboardPage, dashboard_page
from dashboard.page_base import SectionContent


def tour_distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Prepare the distance distribution for one tour purpose."""
    return (
        RunTables.from_runs(data_list)
        .with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        .where(tour_purpose=purpose)
        .select(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col("tour_count"),
        )
        .with_columns(distance_sort_expr("distance_bin").alias("_sort_distance"))
        .sort("_sort_distance")
        .map(lambda frame: frame.drop("_sort_distance"))
    )


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
        category="nonmandatory_tour_purpose",
        average_col="average_tour_distance",
        weight_col="tour_count",
    )
    quantity_a_column = "Average Non-Mandatory Tour Distance"
    quantity_b_column = "Base Run Average Non-Mandatory Tour Distance"
    out: list[tuple[str, pl.DataFrame]] = []
    for run_label, run_df in runs:
        run_lookup = weighted_average_lookup(
            run_df,
            category="nonmandatory_tour_purpose",
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


@dashboard_page(
    page_id="tour_distance",
    title="Tour Distance",
    group_id="tour_summaries",
    order=44,
    required_summary_ids=(
        "tour_distance_by_tour_purpose",
        "average_mandatory_tour_distance_by_purpose_and_geography",
        "average_nonmandatory_tour_distance_by_purpose_and_geography",
    ),
)
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
        self.tour_purpose_sel = self.select(
            "tour_purpose",
            "Tour Purpose",
            options=self._purpose_options,
        )
        self.geo_level_sel = self.select(
            "geography_level",
            GEOGRAPHY_TYPE_SELECTOR_LABEL,
            options=self._geography_level_options,
        )
        self.geography_sel = self.select(
            "geography",
            GEOGRAPHY_NAME_SELECTOR_LABEL,
            options=self._geography_options,
        )
        self.tour_distance_range = DistanceRangeControls.create(
            self,
            "tour_distance",
            max_options=capped_distance_max_options(),
            reset_label="Reset distance range",
        )
        self._distance_section = self.section(
            "tour_distance_distribution",
            selectors=("tour_purpose", *self.tour_distance_range.selector_ids),
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
        return self.data.summaries(*self.required_summary_ids)

    def _distance_sources(self):
        summaries = self._summaries()
        if not summaries:
            return None, None, None
        nonmandatory_average = normalize_geography_data(
            summaries["average_nonmandatory_tour_distance_by_purpose_and_geography"]
        )
        mandatory_average = normalize_geography_data(
            summaries["average_mandatory_tour_distance_by_purpose_and_geography"]
        )

        return (
            summaries["tour_distance_by_tour_purpose"],
            nonmandatory_average,
            mandatory_average,
        )

    def _purpose_options(self) -> list[str]:
        distance_summary, _, _ = self._distance_sources()
        options, self._tour_purpose_to_raw = column_options(
            distance_summary or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            total_raw="all_tour_purposes",
            total_label=self.TOTAL_PURPOSE_LABEL,
        )
        return options or [self.TOTAL_PURPOSE_LABEL]

    def _geography_level_options(self) -> list[str]:
        _, nonmandatory_average, mandatory_average = self._distance_sources()
        options, self._geo_level_raw_by_label = geography_type_options(
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
            include_all_types=True,
        )
        return options or [ALL_GEOGRAPHY_TYPES_LABEL]

    def _geography_options(self) -> list[str]:
        _, nonmandatory_average, mandatory_average = self._distance_sources()
        geography_type = self.selected_geography_level_raw()
        options, self._geography_raw_by_label = geography_name_options_for_type(
            geography_type,
            nonmandatory_average or None,
            mandatory_average or None,
            config=self.config,
        )
        if getattr(self, "geography_sel", None) is not None:
            self.geography_sel.name = geography_name_selector_label(
                geography_type,
                config=self.config,
            )
        return options or [ALL_WITHIN_LEVEL_VALUE]

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
        distance_data = self.query(
            lambda: tour_distance_chart_data(
                summaries["tour_distance_by_tour_purpose"],
                str(raw_purpose),
            )
        )
        observed_bounds = distance_axis_bounds(distance_data)
        bounds = (0.0, 40.0) if observed_bounds is not None else None
        self.tour_distance_range.sync(
            (raw_purpose, self.weighting_key),
            bounds,
        )
        x_range = self.tour_distance_range.current_range()
        if bounds is not None and x_range is None:
            return [
                pn.pane.Markdown("### Tour Distance Distribution"),
                selector_row(self.tour_purpose_sel),
                self.tour_distance_range.row(),
                self.data_not_available_card(
                    detail="Tour distance controls require finite values with min less than max.",
                    title="Tour Distance Data Not Available",
                ),
            ]
        return [
            pn.pane.Markdown("### Tour Distance Distribution"),
            selector_row(self.tour_purpose_sel),
            self.tour_distance_range.row(),
            self.render_distance_chart(
                distance_data, selected_purpose, x_range=x_range
            ),
        ]

    def render_distance_chart(
        self,
        distance_data: list[tuple[str, pl.DataFrame]],
        display_purpose: str,
        *,
        x_range: tuple[float, float] | None,
    ) -> pn.viewable.Viewable:
        """Render the distance distribution chart for one selected purpose."""
        axis_data = with_distance_axis(distance_data)
        tickvals, ticktext = fixed_distance_axis_ticks()
        return self.plot.density(
            axis_data,
            x="_distance_axis",
            y="tour_count",
            title=f"Tour Distance Distribution - {display_purpose}",
            x_title="Distance (miles)",
            y_title="Tours",
            x_range=x_range,
            tick_values=tickvals,
            tick_text=ticktext,
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
        comparison_tables = self.query(
            lambda: average_distance_comparison_table(
                nonmandatory_average,
                geo_level,
                geography,
                "All",
                config=self.config,
            )
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
