"""Tour mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    total_label: str = "All",
) -> list[str]:
    if col == "auto_sufficiency":
        return ["All", "Zero Auto", "Auto Deficient", "Auto Sufficient"]
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    if col == "tour_purpose":
        options = []
        if "all_tour_purposes" in vals:
            options.append("Total")
        options.extend(
            sorted(
                v for v in vals if v not in {total_label, "Total", "all_tour_purposes"}
            )
        )
        return options or ["Total"]
    return [total_label] + sorted(v for v in vals if v != total_label)


def _filter_col(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    value: str,
    total_label: str = "All",
) -> list[tuple[str, pl.DataFrame]]:
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
        return df

    out = []
    for label, df in _nonempty(data_list):
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
                        group_col = group_cols[0]
                        df = (
                            df.group_by(group_col)
                            .agg(vehicle_count=pl.col("vehicle_count").sum())
                        )
                        df = _sort_filtered(df)
                else:
                    value_cols = [name for name in df.columns if name != col]
                    if len(value_cols) == 1:
                        value_col = value_cols[0]
                        df = (
                            df.group_by(col)
                            .agg(pl.col(value_col).sum().alias(value_col))
                            .sort(col)
                        )
            else:
                df = df.filter(pl.col(col) == value)
                df = _sort_filtered(df)
        out.append((label, df))
    return out


def tour_mode_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    auto_sufficiency: str,
) -> list[tuple[str, pl.DataFrame]]:
    value_col_map = {
        "All": "tour_count_all_households",
        "Zero Auto": "tour_count_zero_auto",
        "Auto Deficient": "tour_count_auto_deficient",
        "Auto Sufficient": "tour_count_auto_sufficient",
    }
    value_col = value_col_map[auto_sufficiency]
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))
        if purpose == "Total":
            df = df.filter(pl.col("tour_purpose") == "all_tour_purposes")
        else:
            df = df.filter(pl.col("tour_purpose") == purpose)
        out.append(
            (
                label,
                df.select(
                    pl.col("tour_mode"),
                    pl.col(value_col).alias("tour_count"),
                ).sort("tour_mode"),
            )
        )
    return out


class TourModePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Mode", state, config)

        mode_data = self.state.get_summary_table_set(
            "tour_mode_by_tour_purpose_and_auto_sufficiency", "weighted"
        )
        veh_data = self.state.get_summary_table_set(
            "allocated_vehicle_age_by_occupancy", "weighted"
        )

        self.purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=_options(mode_data or [], "tour_purpose"),
            value=_options(mode_data or [], "tour_purpose")[0],
        )
        self._watch_widget(self.purpose_sel)

        self.auto_suff_sel = pn.widgets.Select(
            name="Household Auto Sufficiency",
            options=_options(mode_data or [], "auto_sufficiency"),
            value=_options(mode_data or [], "auto_sufficiency")[0],
        )
        self._watch_widget(self.auto_suff_sel)

        self.occupancy_sel = pn.widgets.Select(
            name="Vehicle Occupancy",
            options=_options(veh_data or [], "occupancy"),
            value=_options(veh_data or [], "occupancy")[0],
        )
        self._watch_widget(self.occupancy_sel)

        self._mode_section = self.new_section()
        self._vehicle_section = self.new_section()

        self.view = self.new_section(
            pn.pane.Markdown("## Tour Mode"),
            self._mode_section,
            self._vehicle_section,
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._mode_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._vehicle_section.objects = []
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._mode_section.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            self._vehicle_section.objects = []
            return

        mode_summary = summaries["tour_mode_by_tour_purpose_and_auto_sufficiency"]

        purpose_opts = _options(mode_summary, "tour_purpose")
        self.purpose_sel.options = purpose_opts
        if self.purpose_sel.value not in purpose_opts:
            self.purpose_sel.value = purpose_opts[0]

        auto_opts = _options(mode_summary, "auto_sufficiency")
        self.auto_suff_sel.options = auto_opts
        if self.auto_suff_sel.value not in auto_opts:
            self.auto_suff_sel.value = auto_opts[0]

        occupancy_opts = _options(
            summaries["allocated_vehicle_age_by_occupancy"],
            "occupancy",
        )
        self.occupancy_sel.options = occupancy_opts
        if self.occupancy_sel.value not in occupancy_opts:
            self.occupancy_sel.value = occupancy_opts[0]

        purpose = self.purpose_sel.value
        auto_suff = self.auto_suff_sel.value
        occupancy = self.occupancy_sel.value

        mode_data = self.get_filtered_view(
            "tour_mode",
            (purpose, auto_suff),
            factory=lambda: tour_mode_chart_data(mode_summary, purpose, auto_suff),
        )

        vehicle_age_data = self.get_filtered_view(
            "allocated_vehicle_age",
            occupancy,
            factory=lambda: _filter_col(
                summaries["allocated_vehicle_age_by_occupancy"],
                "occupancy",
                occupancy,
            ),
        )

        vehicle_fuel_data = self.get_filtered_view(
            "allocated_vehicle_fuel",
            occupancy,
            factory=lambda: _filter_col(
                summaries["allocated_vehicle_fuel_type_by_occupancy"],
                "occupancy",
                occupancy,
            ),
        )

        vehicle_body_data = self.get_filtered_view(
            "allocated_vehicle_body",
            occupancy,
            factory=lambda: _filter_col(
                summaries["allocated_vehicle_body_type_by_occupancy"],
                "occupancy",
                occupancy,
            ),
        )

        mode_chart = bar_chart(
            mode_data,
            x_col="tour_mode",
            y_col="tour_count",
            title="Tour Mode by Tour Purpose and Household Auto Sufficiency",
            xaxis_title="Tour Mode",
            yaxis_title="Tours",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        age_chart = bar_chart(
            vehicle_age_data,
            x_col="age",
            y_col="vehicle_count",
            title="Allocated Vehicle Age by Occupancy Level",
            xaxis_title="Vehicle Age",
            yaxis_title="Allocated Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        fuel_chart = bar_chart(
            vehicle_fuel_data,
            x_col="fuel_type",
            y_col="vehicle_count",
            title="Allocated Vehicle Fuel Type by Occupancy Level",
            xaxis_title="Vehicle Fuel Type",
            yaxis_title="Allocated Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        body_chart = bar_chart(
            vehicle_body_data,
            x_col="body_type",
            y_col="vehicle_count",
            title="Allocated Vehicle Body Type by Occupancy Level",
            xaxis_title="Vehicle Body Type",
            yaxis_title="Allocated Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._mode_section.objects = [
            pn.pane.Markdown("### Tour Mode"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.purpose_sel,
                pn.pane.Markdown("**Household Auto Sufficiency:**"),
                self.auto_suff_sel,
            ),
            mode_chart,
        ]

        self._vehicle_section.objects = [
            pn.pane.Markdown("### Allocated Vehicle Characteristics"),
            pn.Row(
                pn.pane.Markdown("**Vehicle Occupancy:**"),
                self.occupancy_sel,
            ),
            pn.Row(age_chart, fuel_chart, body_chart),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_mode",
    title="Tour Mode",
    group_id="tour_summaries",
    child_id="tour_mode",
    order=42,
    controller_cls=TourModePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="purpose_sel",
            label="Tour Purpose",
        ),
        PageSelectorDefinition(
            selector_id="auto_sufficiency",
            widget_attr="auto_suff_sel",
            label="Household Auto Sufficiency",
        ),
        PageSelectorDefinition(
            selector_id="vehicle_occupancy",
            widget_attr="occupancy_sel",
            label="Vehicle Occupancy",
        ),
    ),
    required_summary_ids=(
        "tour_mode_by_tour_purpose_and_auto_sufficiency",
        "allocated_vehicle_age_by_occupancy",
        "allocated_vehicle_fuel_type_by_occupancy",
        "allocated_vehicle_body_type_by_occupancy",
    ),
)

TourModePage.definition = PAGE
