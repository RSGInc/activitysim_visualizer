"""Tour mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import MultiSelectorComparisonPage, SectionSpec, SelectorSpec
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_options, column_value_union, nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    *,
    total_label: str = "All",
    category_id: str | None = None,
    config=None,
) -> list[str]:
    if col == "auto_sufficiency":
        return ["All", "Zero Auto", "Auto Deficient", "Auto Sufficient"]
    return column_options(
        data_list,
        col,
        total_label=total_label,
        category_id=category_id,
        config=config,
    )


def _filter_col(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    value: str,
    total_label: str = "All",
):
    def _sort_filtered(df: pl.DataFrame) -> pl.DataFrame:
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
        sort_cols = [
            name for name in df.columns if name not in {"vehicle_count", "pct", col}
        ]
        return df.sort(sort_cols[0]) if sort_cols else df

    out = []
    for label, df in nonempty_runs(data_list):
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Utf8))
            if value == total_label:
                if "vehicle_count" in df.columns:
                    group_cols = [
                        name
                        for name in df.columns
                        if name not in {col, "vehicle_count"}
                    ]
                    if len(group_cols) == 1:
                        df = df.group_by(group_cols[0]).agg(
                            vehicle_count=pl.col("vehicle_count").sum()
                        )
                        df = _sort_filtered(df)
                else:
                    value_cols = [name for name in df.columns if name != col]
                    if len(value_cols) == 1:
                        df = (
                            df.group_by(col)
                            .agg(pl.col(value_cols[0]).sum().alias(value_cols[0]))
                            .sort(col)
                        )
            else:
                df = _sort_filtered(df.filter(pl.col(col) == value))
        out.append((label, df))
    return out


def tour_mode_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    auto_sufficiency: str,
    *,
    config,
):
    value_col = {
        "All": "tour_count_all_households",
        "Zero Auto": "tour_count_zero_auto",
        "Auto Deficient": "tour_count_auto_deficient",
        "Auto Sufficient": "tour_count_auto_sufficient",
    }[auto_sufficiency]
    ordered_modes = config.ordered_values("mode", column_value_union(data_list, "tour_mode"))
    base = pl.DataFrame({"tour_mode": ordered_modes})
    out = []
    for label, df in nonempty_runs(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        df = df.filter(
            pl.col("tour_purpose")
            == ("all_tour_purposes" if purpose == "Total" else purpose)
        )
        out.append(
            (
                label,
                base.join(
                    df.select(
                        pl.col("tour_mode"), pl.col(value_col).alias("tour_count")
                    ),
                    on="tour_mode",
                    how="left",
                ).with_columns(pl.col("tour_count").fill_null(0.0)),
            )
        )
    return out


class TourModePage(MultiSelectorComparisonPage):
    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        self._tour_purpose_to_raw = {"Total": "all_tour_purposes"}
        return (
            SelectorSpec(
                selector_id="tour_purpose",
                label="Tour Purpose",
                attr_name="purpose_sel",
                options_factory=lambda page: page._purpose_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Tour Purpose",
                    options=options,
                    value=value,
                ),
            ),
            SelectorSpec(
                selector_id="auto_sufficiency",
                label="Household Auto Sufficiency",
                attr_name="auto_suff_sel",
                options_factory=lambda page: page._auto_sufficiency_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Household Auto Sufficiency",
                    options=options,
                    value=value,
                ),
            ),
            SelectorSpec(
                selector_id="vehicle_occupancy",
                label="Vehicle Occupancy",
                attr_name="occupancy_sel",
                options_factory=lambda page: page._occupancy_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Vehicle Occupancy",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _purpose_options(self) -> list[object]:
        raw_values = self.state.get_summary_column_values(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            "tour_purpose",
            self.weighting_key,
        )
        options, self._tour_purpose_to_raw = tour_purpose_mapping(
            raw_values,
            config=self.config,
        )
        return options or ["Total"]

    def _auto_sufficiency_options(self) -> list[object]:
        mode_data = self.get_refresh_summary(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            optional=True,
        )
        return _options(mode_data or [], "auto_sufficiency")

    def _occupancy_options(self) -> list[object]:
        age_summary = self.get_refresh_summary(
            "allocated_vehicle_age_by_occupancy",
            optional=True,
        )
        fuel_summary = self.get_refresh_summary(
            "allocated_vehicle_fuel_type_by_occupancy",
            optional=True,
        )
        body_summary = self.get_refresh_summary(
            "allocated_vehicle_body_type_by_occupancy",
            optional=True,
        )
        return column_options(
            age_summary or fuel_summary or body_summary or [],
            "occupancy",
        )

    def build_page(self) -> pn.viewable.Viewable:
        self.register_selectors(*self.selector_specs())
        self.register_sections(
            SectionSpec(
                section_id="tour_mode_modes",
                selector_ids=("tour_purpose", "auto_sufficiency"),
                render=lambda page: page.render_modes(),
                attr_name="_mode_section",
            ),
            SectionSpec(
                section_id="tour_mode_vehicles",
                selector_ids=("vehicle_occupancy",),
                render=lambda page: page.render_vehicles(),
                attr_name="_vehicle_section",
            ),
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Mode"),
            pn.pane.Markdown("""
            **Auto sufficiency definitions**

            - **Zero Auto**: household has no vehicles.
            - **Auto Deficient**: household has fewer vehicles than licensed drivers.
            - **Auto Sufficient**: household has at least as many vehicles as licensed drivers.
            """),
            self._mode_section,
            self._vehicle_section,
        )

    def _summaries(self):
        return (
            self.get_refresh_summary(
                "tour_mode_by_tour_purpose_and_auto_sufficiency",
                optional=True,
            ),
            self.get_refresh_summary("allocated_vehicle_age_by_occupancy", optional=True),
            self.get_refresh_summary(
                "allocated_vehicle_fuel_type_by_occupancy",
                optional=True,
            ),
            self.get_refresh_summary(
                "allocated_vehicle_body_type_by_occupancy",
                optional=True,
            ),
        )

    def render_modes(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]
        mode_summary, _, _, _ = self._summaries()
        purpose = self.purpose_sel.value
        auto_suff = self.auto_suff_sel.value
        if mode_summary is None:
            return [
                pn.pane.Markdown("### Tour Mode"),
                pn.Row(
                    pn.pane.Markdown("**Tour Purpose:**"),
                    self.purpose_sel,
                    pn.pane.Markdown("**Household Auto Sufficiency:**"),
                    self.auto_suff_sel,
                ),
                self.data_not_available_card(
                    detail="The tour mode summary is unavailable.",
                    missing_items=["tour_mode_by_tour_purpose_and_auto_sufficiency"],
                ),
            ]
        mode_data = self.get_filtered_view(
            "tour_mode",
            (purpose, auto_suff),
            factory=lambda: tour_mode_chart_data(
                mode_summary,
                self._tour_purpose_to_raw.get(str(purpose), str(purpose)),
                auto_suff,
                config=self.config,
            ),
        )
        return [
            pn.pane.Markdown("### Tour Mode"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.purpose_sel,
                pn.pane.Markdown("**Household Auto Sufficiency:**"),
                self.auto_suff_sel,
            ),
            bar_chart(
                mode_data,
                "tour_mode",
                "tour_count",
                "Tour Mode by Tour Purpose and Household Auto Sufficiency",
                "Tour Mode",
                yaxis_title="Tours",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=self.config.ordered_values(
                    "mode",
                    column_value_union(mode_data, "tour_mode"),
                ),
            ),
        ]

    def render_vehicles(self):
        _, age_summary, fuel_summary, body_summary = self._summaries()
        occupancy = self.occupancy_sel.value
        widgets: list[pn.viewable.Viewable] = []
        if age_summary is not None:
            widgets.append(
                bar_chart(
                    self.get_filtered_view(
                        "allocated_vehicle_age",
                        occupancy,
                        factory=lambda: _filter_col(
                            age_summary, "occupancy", occupancy
                        ),
                    ),
                    "age",
                    "vehicle_count",
                    "Allocated Vehicle Age by Occupancy Level",
                    "Vehicle Age",
                    yaxis_title="Allocated Vehicles",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            widgets.append(
                self.data_not_available_card(
                    detail="The allocated vehicle age summary is unavailable.",
                    missing_items=["allocated_vehicle_age_by_occupancy"],
                )
            )
        if fuel_summary is not None:
            widgets.append(
                bar_chart(
                    self.get_filtered_view(
                        "allocated_vehicle_fuel",
                        occupancy,
                        factory=lambda: _filter_col(
                            fuel_summary, "occupancy", occupancy
                        ),
                    ),
                    "fuel_type",
                    "vehicle_count",
                    "Allocated Vehicle Fuel Type by Occupancy Level",
                    "Vehicle Fuel Type",
                    yaxis_title="Allocated Vehicles",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            widgets.append(
                self.data_not_available_card(
                    detail="The allocated vehicle fuel summary is unavailable.",
                    missing_items=["allocated_vehicle_fuel_type_by_occupancy"],
                )
            )
        if body_summary is not None:
            widgets.append(
                bar_chart(
                    self.get_filtered_view(
                        "allocated_vehicle_body",
                        occupancy,
                        factory=lambda: _filter_col(
                            body_summary, "occupancy", occupancy
                        ),
                    ),
                    "body_type",
                    "vehicle_count",
                    "Allocated Vehicle Body Type by Occupancy Level",
                    "Vehicle Body Type",
                    yaxis_title="Allocated Vehicles",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            widgets.append(
                self.data_not_available_card(
                    detail="The allocated vehicle body summary is unavailable.",
                    missing_items=["allocated_vehicle_body_type_by_occupancy"],
                )
            )
        return [
            pn.pane.Markdown("### Allocated Vehicle Characteristics"),
            pn.Row(pn.pane.Markdown("**Vehicle Occupancy:**"), self.occupancy_sel),
            pn.Row(*widgets),
        ]


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
