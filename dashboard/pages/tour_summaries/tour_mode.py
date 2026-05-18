"""Tour mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import column_options, nonempty
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def _options(
    data_list: list[tuple[str, pl.DataFrame]], col: str, total_label: str = "All"
) -> list[str]:
    if col == "auto_sufficiency":
        return ["All", "Zero Auto", "Auto Deficient", "Auto Sufficient"]
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
    for label, df in nonempty(data_list):
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
    data_list: list[tuple[str, pl.DataFrame]], purpose: str, auto_sufficiency: str
):
    value_col = {
        "All": "tour_count_all_households",
        "Zero Auto": "tour_count_zero_auto",
        "Auto Deficient": "tour_count_auto_deficient",
        "Auto Sufficient": "tour_count_auto_sufficient",
    }[auto_sufficiency]
    out = []
    for label, df in nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        df = df.filter(
            pl.col("tour_purpose")
            == purpose
        )
        out.append(
            (
                label,
                df.select(
                    pl.col("tour_mode"), pl.col(value_col).alias("tour_count")
                ).sort("tour_mode"),
            )
        )
    return out


class TourModePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        mode_data = self.state.get_summary_table_set(
            "tour_mode_by_tour_purpose_and_auto_sufficiency", "weighted"
        )
        veh_data = self.state.get_summary_table_set(
            "allocated_vehicle_age_by_occupancy", "weighted"
        )
        purpose_opts, self._purpose_to_raw = column_options(
            mode_data or [],
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
        if not purpose_opts:
            purpose_opts = ["Total"]
        self.purpose_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purpose_opts,
                value=purpose_opts[0],
            ),
            label="Tour Purpose",
        )
        self.auto_suff_sel = self.selector(
            "auto_sufficiency",
            widget=pn.widgets.Select(
                name="Household Auto Sufficiency",
                options=_options(mode_data or [], "auto_sufficiency"),
                value=_options(mode_data or [], "auto_sufficiency")[0],
            ),
            label="Household Auto Sufficiency",
        )
        self.occupancy_sel = self.selector(
            "vehicle_occupancy",
            widget=pn.widgets.Select(
                name="Vehicle Occupancy",
                options=_options(veh_data or [], "occupancy"),
                value=_options(veh_data or [], "occupancy")[0],
            ),
            label="Vehicle Occupancy",
        )
        self._mode_section = self.section(
            "tour_mode_modes",
            selectors=("tour_purpose", "auto_sufficiency"),
            render=self.render_modes,
        )
        self._vehicle_section = self.section(
            "tour_mode_vehicles",
            selectors=("vehicle_occupancy",),
            render=self.render_vehicles,
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
            self.optional_summary("tour_mode_by_tour_purpose_and_auto_sufficiency"),
            self.optional_summary("allocated_vehicle_age_by_occupancy"),
            self.optional_summary("allocated_vehicle_fuel_type_by_occupancy"),
            self.optional_summary("allocated_vehicle_body_type_by_occupancy"),
        )

    def sync_controls(self) -> None:
        mode_summary, age_summary, fuel_summary, body_summary = self._summaries()
        purpose_opts, self._purpose_to_raw = column_options(
            mode_summary or [],
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
        for widget, opts in [
            (self.purpose_sel, purpose_opts),
            (self.auto_suff_sel, _options(mode_summary or [], "auto_sufficiency")),
            (
                self.occupancy_sel,
                _options(
                    age_summary or fuel_summary or body_summary or [], "occupancy"
                ),
            ),
        ]:
            widget.options = opts
            if widget.value not in opts:
                widget.value = opts[0]

    def render_modes(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]
        mode_summary, _, _, _ = self._summaries()
        purpose = self.purpose_sel.value
        raw_purpose = self._purpose_to_raw.get(purpose, "all_tour_purposes")
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
            (raw_purpose, auto_suff),
            factory=lambda: tour_mode_chart_data(mode_summary, raw_purpose, auto_suff),
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
