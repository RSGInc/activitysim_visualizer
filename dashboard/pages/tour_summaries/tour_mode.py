"""Tour mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import (
    column_options,
    common_column_options,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

AUTO_SUFFICIENCY_LEVELS = [
    "All",
    "Zero Auto",
    "Auto Deficient",
    "Auto Sufficient",
]


def auto_sufficiency_definitions_markdown(config) -> str:
    """Describe the configured household basis behind the auto sufficiency split."""
    basis_noun = {
        "licensed_drivers": "licensed drivers",
        "workers": "workers",
        "adults": "adults",
    }[config.prepare_auto_sufficiency.basis]
    return f"""
    **Auto sufficiency definitions**

    - **Zero Auto**: household has no vehicles.
    - **Auto Deficient**: household has fewer vehicles than {basis_noun}.
    - **Auto Sufficient**: household has at least as many vehicles as {basis_noun}.
    """


def vehicle_attribute_data(
    data_list: list[tuple[str, pl.DataFrame]],
    occupancy: str,
    *,
    category_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter one allocated-vehicle summary to the selected occupancy level."""

    def sort_filtered(df: pl.DataFrame) -> pl.DataFrame:
        if "age" in df.columns:
            return (
                df.with_columns(
                    pl.when(pl.col("age").cast(pl.Utf8) == "20+")
                    .then(999)
                    .otherwise(pl.col("age").cast(pl.Int64, strict=False))
                    .alias("_sort_age")
                )
                .sort("_sort_age")
                .drop("_sort_age")
            )
        return df.sort(category_col) if category_col in df.columns else df

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df
        if "occupancy" in filtered.columns:
            filtered = filtered.with_columns(pl.col("occupancy").cast(pl.Utf8))
            if occupancy == "All":
                filtered = (
                    filtered.group_by(category_col)
                    .agg(vehicle_count=pl.col("vehicle_count").sum())
                )
            else:
                filtered = filtered.filter(pl.col("occupancy") == occupancy)
        out.append((label, sort_filtered(filtered)))
    return out


def tour_mode_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    auto_sufficiency: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one tour mode distribution for a selected purpose and sufficiency slice."""
    value_col = {
        "All": "tour_count_all_households",
        "Zero Auto": "tour_count_zero_auto",
        "Auto Deficient": "tour_count_auto_deficient",
        "Auto Sufficient": "tour_count_auto_sufficient",
    }[auto_sufficiency]
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8)).filter(
            pl.col("tour_purpose") == purpose
        )
        out.append(
            (
                label,
                filtered.select(pl.col("tour_mode"), pl.col(value_col).alias("tour_count")).sort(
                    "tour_mode"
                ),
            )
        )
    return out


class TourModePage(DashboardPage):
    """Render tour mode splits and allocated vehicle characteristics."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell and persistent selectors."""
        self._purpose_to_raw: dict[str, str | None] = {}
        purpose_options = self._initial_purpose_options()
        occupancy_options = self._initial_occupancy_options()
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_options,
                value=purpose_options[0],
            ),
            label="Tour Purpose",
        )
        self.occupancy_sel = self.selector(
            "vehicle_occupancy",
            widget=pn.widgets.Select(
                name="Vehicle Occupancy",
                options=occupancy_options,
                value=occupancy_options[0],
            ),
            label="Vehicle Occupancy",
        )
        self._mode_section = self.section(
            "tour_mode_modes",
            selectors=("tour_purpose",),
            render=self.render_modes_section,
        )
        self._vehicle_section = self.section(
            "tour_mode_vehicles",
            selectors=("vehicle_occupancy",),
            render=self.render_vehicle_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Mode"),
            pn.pane.Markdown(auto_sufficiency_definitions_markdown(self.config)),
            self._mode_section,
            self._vehicle_section,
        )

    def _initial_purpose_options(self) -> list[str]:
        """Populate the purpose selector before the first page refresh."""
        summaries = self.state.get_summary_table_set(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            "weighted",
        )
        options, self._purpose_to_raw = column_options(
            summaries or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_mode",
                "tour_mode_by_tour_purpose_and_auto_sufficiency",
                "tour_purpose",
                "weighted",
            ),
            total_raw="all_tour_purposes",
            total_label="Total",
        )
        return options or ["Total"]

    def _initial_occupancy_options(self) -> list[str]:
        """Populate the occupancy selector before the first page refresh."""
        age_summary = self.state.get_summary_table_set(
            "allocated_vehicle_age_by_occupancy",
            "weighted",
        )
        fuel_summary = self.state.get_summary_table_set(
            "allocated_vehicle_fuel_type_by_occupancy",
            "weighted",
        )
        body_summary = self.state.get_summary_table_set(
            "allocated_vehicle_body_type_by_occupancy",
            "weighted",
        )
        options, _ = common_column_options(
            age_summary,
            fuel_summary,
            body_summary,
            column="occupancy",
            total_raw="All",
            total_label="All",
        )
        return options or ["All"]

    def _summaries(self):
        """Load every summary used by either page section."""
        return self.optional_summaries_dict(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            "allocated_vehicle_age_by_occupancy",
            "allocated_vehicle_fuel_type_by_occupancy",
            "allocated_vehicle_body_type_by_occupancy",
        )

    def sync_controls(self) -> None:
        """Keep selector domains synchronized with current summary availability."""
        summaries = self._summaries()
        purpose_options, self._purpose_to_raw = column_options(
            summaries["tour_mode_by_tour_purpose_and_auto_sufficiency"] or [],
            "tour_purpose",
            category_id="tour_purpose",
            config=self.config,
            state=self.state,
            cache_key=(
                "tour_mode",
                "tour_mode_by_tour_purpose_and_auto_sufficiency",
                "tour_purpose",
                self.weighting_key,
            ),
            total_raw="all_tour_purposes",
            total_label="Total",
        )
        occupancy_options, _ = common_column_options(
            summaries["allocated_vehicle_age_by_occupancy"],
            summaries["allocated_vehicle_fuel_type_by_occupancy"],
            summaries["allocated_vehicle_body_type_by_occupancy"],
            column="occupancy",
            total_raw="All",
            total_label="All",
        )
        for widget, options in (
            (self.purpose_sel, purpose_options or ["Total"]),
            (self.occupancy_sel, occupancy_options or ["All"]),
        ):
            widget.options = options
            if widget.value not in options:
                widget.value = options[0]

    def render_modes_section(self):
        """Render the tour mode charts by auto sufficiency."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._summaries()
        mode_summary = summaries["tour_mode_by_tour_purpose_and_auto_sufficiency"]
        selected_purpose = str(self.purpose_sel.value)
        raw_purpose = self._purpose_to_raw.get(selected_purpose, "all_tour_purposes")
        if mode_summary is None:
            return [
                pn.pane.Markdown("### Tour Mode"),
                pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purpose_sel),
                self.data_not_available_card(
                    detail="The tour mode summary is unavailable.",
                    missing_items=["tour_mode_by_tour_purpose_and_auto_sufficiency"],
                ),
            ]

        mode_values = [
            value
            for value in ordered_category_values(
                mode_summary,
                "tour_mode",
                category_id="mode",
                config=self.config,
            )
            if value != "all_tour_modes"
        ]
        return [
            pn.pane.Markdown("### Tour Mode"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purpose_sel),
            *[
                self.render_tour_mode_chart(
                    mode_summary,
                    str(raw_purpose),
                    selected_purpose,
                    auto_sufficiency,
                    mode_values,
                )
                for auto_sufficiency in AUTO_SUFFICIENCY_LEVELS
            ],
        ]

    def render_tour_mode_chart(
        self,
        summary_data,
        raw_purpose: str,
        display_purpose: str,
        auto_sufficiency: str,
        mode_values: list[str],
    ) -> pn.viewable.Viewable:
        """Render one auto-sufficiency slice of the selected tour purpose."""
        mode_data = self.get_filtered_view(
            "tour_mode",
            (raw_purpose, auto_sufficiency),
            factory=lambda: tour_mode_chart_data(
                summary_data,
                raw_purpose,
                auto_sufficiency,
            ),
        )
        labeled = label_category_data(
            mode_data,
            source_col="tour_mode",
            category_id="mode",
            config=self.config,
            target_col="tour_mode_label",
        )
        return bar_chart(
            labeled,
            "tour_mode_label",
            "tour_count",
            f"Tour Mode - {auto_sufficiency}",
            "Tour Mode",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=self.config.ordered_labels("mode", mode_values),
        )

    def render_vehicle_section(self):
        """Render the three allocated vehicle characteristic charts."""
        summaries = self._summaries()
        occupancy = str(self.occupancy_sel.value)
        return [
            pn.pane.Markdown("### Allocated Vehicle Characteristics"),
            pn.Row(pn.pane.Markdown("**Vehicle Occupancy:**"), self.occupancy_sel),
            pn.Row(
                self.render_vehicle_age_chart(
                    summaries["allocated_vehicle_age_by_occupancy"],
                    occupancy,
                ),
                self.render_vehicle_fuel_chart(
                    summaries["allocated_vehicle_fuel_type_by_occupancy"],
                    occupancy,
                ),
                self.render_vehicle_body_chart(
                    summaries["allocated_vehicle_body_type_by_occupancy"],
                    occupancy,
                ),
            ),
        ]

    def render_vehicle_age_chart(self, summary_data, occupancy: str) -> pn.viewable.Viewable:
        """Render allocated vehicle age by occupancy level."""
        if summary_data is None:
            return self.data_not_available_card(
                detail="The allocated vehicle age summary is unavailable.",
                missing_items=["allocated_vehicle_age_by_occupancy"],
            )
        age_values = self.ordered_vehicle_values(summary_data, "age")
        chart_data = self.get_filtered_view(
            "allocated_vehicle_age",
            occupancy,
            factory=lambda: vehicle_attribute_data(
                summary_data,
                occupancy,
                category_col="age",
            ),
        )
        return bar_chart(
            chart_data,
            "age",
            "vehicle_count",
            "Allocated Vehicle Age by Occupancy Level",
            "Vehicle Age",
            yaxis_title="Allocated Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=age_values,
        )

    def render_vehicle_fuel_chart(self, summary_data, occupancy: str) -> pn.viewable.Viewable:
        """Render allocated vehicle fuel type by occupancy level."""
        if summary_data is None:
            return self.data_not_available_card(
                detail="The allocated vehicle fuel summary is unavailable.",
                missing_items=["allocated_vehicle_fuel_type_by_occupancy"],
            )
        fuel_values = self.ordered_vehicle_values(summary_data, "fuel_type")
        chart_data = self.get_filtered_view(
            "allocated_vehicle_fuel",
            occupancy,
            factory=lambda: vehicle_attribute_data(
                summary_data,
                occupancy,
                category_col="fuel_type",
            ),
        )
        return bar_chart(
            chart_data,
            "fuel_type",
            "vehicle_count",
            "Allocated Vehicle Fuel Type by Occupancy Level",
            "Vehicle Fuel Type",
            yaxis_title="Allocated Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=fuel_values,
        )

    def render_vehicle_body_chart(self, summary_data, occupancy: str) -> pn.viewable.Viewable:
        """Render allocated vehicle body type by occupancy level."""
        if summary_data is None:
            return self.data_not_available_card(
                detail="The allocated vehicle body summary is unavailable.",
                missing_items=["allocated_vehicle_body_type_by_occupancy"],
            )
        body_values = self.ordered_vehicle_values(summary_data, "body_type")
        chart_data = self.get_filtered_view(
            "allocated_vehicle_body",
            occupancy,
            factory=lambda: vehicle_attribute_data(
                summary_data,
                occupancy,
                category_col="body_type",
            ),
        )
        return bar_chart(
            chart_data,
            "body_type",
            "vehicle_count",
            "Allocated Vehicle Body Type by Occupancy Level",
            "Vehicle Body Type",
            yaxis_title="Allocated Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=body_values,
        )

    def ordered_vehicle_values(
        self,
        summary_data: list[tuple[str, pl.DataFrame]],
        column: str,
    ) -> list[str]:
        """Return a stable x-axis order for vehicle attributes."""
        values = {
            str(value)
            for _, df in nonempty(summary_data)
            for value in (df[column].cast(pl.Utf8).to_list() if column in df.columns else [])
        }
        if column == "age":
            return sorted(
                values,
                key=lambda value: 999 if value == "20+" else int(value) if value.isdigit() else 1000,
            )
        return sorted(values)


PAGE = DashboardPageDefinition(
    page_id="tour_mode",
    title="Tour Mode",
    group_id="tour_summaries",
    order=42,
    page_cls=TourModePage,
    required_summary_ids=(
        "tour_mode_by_tour_purpose_and_auto_sufficiency",
        "allocated_vehicle_age_by_occupancy",
        "allocated_vehicle_fuel_type_by_occupancy",
        "allocated_vehicle_body_type_by_occupancy",
    ),
)

TourModePage.definition = PAGE
