"""Vehicle ownership and type page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _cast_category(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, df.with_columns(pl.col(category_col).cast(pl.Utf8)))
        for label, df in _nonempty(data_list)
    ]


class VehicleOwnershipTypePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Vehicle Ownership and Type", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Vehicle Ownership and Type"),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        auto_own_list = _cast_category(
            summaries["auto_ownership_distribution"],
            "household_vehicle_count",
        )
        av_own_list = _nonempty(summaries["autonomous_vehicle_ownership_totals"])
        vehicle_age_list = _cast_category(
            summaries["vehicle_age_distribution"],
            "vehicle_age",
        )
        vehicle_fuel_list = _cast_category(
            summaries["vehicle_fuel_type_distribution"],
            "vehicle_fuel_type",
        )
        vehicle_body_list = _cast_category(
            summaries["vehicle_body_type_distribution"],
            "vehicle_body_type",
        )

        auto_ownership_chart = bar_chart(
            auto_own_list,
            x_col="household_vehicle_count",
            y_col="household_count",
            title="Auto Ownership by Household Size",
            xaxis_title="Household Vehicles",
            yaxis_title="Households",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        av_kpi = data_table(
            av_own_list,
            "Autonomous Vehicle Ownership",
        )

        vehicle_age_chart = bar_chart(
            vehicle_age_list,
            x_col="vehicle_age",
            y_col="vehicle_count",
            title="Vehicle Age",
            xaxis_title="Vehicle Age",
            yaxis_title="Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        vehicle_fuel_chart = bar_chart(
            vehicle_fuel_list,
            x_col="vehicle_fuel_type",
            y_col="vehicle_count",
            title="Vehicle Fuel Type",
            xaxis_title="Fuel Type",
            yaxis_title="Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        vehicle_body_chart = bar_chart(
            vehicle_body_list,
            x_col="vehicle_body_type",
            y_col="vehicle_count",
            title="Vehicle Body Type",
            xaxis_title="Body Type",
            yaxis_title="Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            pn.Row(auto_ownership_chart, av_kpi, sizing_mode="stretch_width"),
            pn.Row(
                vehicle_age_chart,
                vehicle_fuel_chart,
                vehicle_body_chart,
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="vehicle_ownership_type",
    title="Vehicle Ownership and Type",
    order=26,
    controller_cls=VehicleOwnershipTypePage,
    required_summary_ids=(
        "auto_ownership_distribution",
        "autonomous_vehicle_ownership_totals",
        "vehicle_age_distribution",
        "vehicle_fuel_type_distribution",
        "vehicle_body_type_distribution",
    ),
)

VehicleOwnershipTypePage.definition = PAGE
