"""Vehicle ownership and type page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, kpi_box
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


def _rename_if_present(df: pl.DataFrame, alias_map: dict[str, str]) -> pl.DataFrame:
    rename_map = {
        source: target
        for source, target in alias_map.items()
        if source in df.columns and target not in df.columns
    }
    if not rename_map:
        return df
    return df.rename(rename_map)


def _normalize_vehicle_summary_columns(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    canonical_col: str,
    legacy_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (
            label,
            _rename_if_present(df, {legacy_col: canonical_col}),
        )
        for label, df in _nonempty(data_list)
    ]


def _av_kpi_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for label, df in _nonempty(data_list):
        if "household_with_autonomous_vehicle_count" not in df.columns or len(df) == 0:
            continue
        values.append(
            (
                label,
                float(df["household_with_autonomous_vehicle_count"][0]),
            )
        )
    return values


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

        auto_ownership = self.state.get_summary_table_set(
            "auto_ownership_distribution",
            self.weighting_key,
        )
        av_ownership = self.state.get_summary_table_set(
            "autonomous_vehicle_ownership_totals",
            self.weighting_key,
        )
        vehicle_age = self.state.get_summary_table_set(
            "vehicle_age_distribution",
            self.weighting_key,
        )
        vehicle_fuel = self.state.get_summary_table_set(
            "vehicle_fuel_type_distribution",
            self.weighting_key,
        )
        vehicle_body = self.state.get_summary_table_set(
            "vehicle_body_type_distribution",
            self.weighting_key,
        )

        if not any(
            summary is not None
            for summary in (
                auto_ownership,
                av_ownership,
                vehicle_age,
                vehicle_fuel,
                vehicle_body,
            )
        ):
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        top_row: list[pn.viewable.Viewable] = []
        if auto_ownership is not None:
            auto_own_list = _cast_category(
                auto_ownership,
                "household_vehicle_count",
            )
            top_row.append(
                bar_chart(
                    auto_own_list,
                    x_col="household_vehicle_count",
                    y_col="household_count",
                    title="Auto Ownership by Household Size",
                    xaxis_title="Household Vehicles",
                    yaxis_title="Households",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            top_row.append(
                self.data_not_available_card(
                    detail="The auto ownership summary is unavailable.",
                    missing_items=["auto_ownership_distribution"],
                )
            )

        if av_ownership is not None:
            av_values = _av_kpi_values(av_ownership)
            if av_values:
                top_row.append(
                    kpi_box(
                        "Autonomous Vehicle Ownership",
                        av_values,
                        format_fn=lambda value: f"{value:,.0f}",
                    )
                )
            else:
                top_row.append(
                    self.data_not_available_card(
                        detail="The autonomous vehicle ownership summary is empty.",
                        missing_items=["autonomous_vehicle_ownership_totals"],
                    )
                )
        else:
            top_row.append(
                self.data_not_available_card(
                    detail="The autonomous vehicle ownership summary is unavailable.",
                    missing_items=["autonomous_vehicle_ownership_totals"],
                )
            )

        vehicle_views: list[pn.viewable.Viewable] = []
        if vehicle_age is not None:
            vehicle_age = _normalize_vehicle_summary_columns(
                vehicle_age,
                canonical_col="age",
                legacy_col="vehicle_age",
            )
            vehicle_views.append(
                bar_chart(
                    _cast_category(vehicle_age, "age"),
                    x_col="age",
                    y_col="vehicle_count",
                    title="Vehicle Age",
                    xaxis_title="Vehicle Age",
                    yaxis_title="Vehicles",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            vehicle_views.append(
                self.data_not_available_card(
                    detail="The vehicle age summary is unavailable.",
                    missing_items=["vehicle_age_distribution"],
                )
            )

        if vehicle_fuel is not None:
            vehicle_fuel = _normalize_vehicle_summary_columns(
                vehicle_fuel,
                canonical_col="fuel_type",
                legacy_col="vehicle_fuel_type",
            )
            vehicle_views.append(
                bar_chart(
                    _cast_category(vehicle_fuel, "fuel_type"),
                    x_col="fuel_type",
                    y_col="vehicle_count",
                    title="Vehicle Fuel Type",
                    xaxis_title="Fuel Type",
                    yaxis_title="Vehicles",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            vehicle_views.append(
                self.data_not_available_card(
                    detail="The vehicle fuel summary is unavailable.",
                    missing_items=["vehicle_fuel_type_distribution"],
                )
            )

        if vehicle_body is not None:
            vehicle_body = _normalize_vehicle_summary_columns(
                vehicle_body,
                canonical_col="body_type",
                legacy_col="vehicle_body_type",
            )
            vehicle_views.append(
                bar_chart(
                    _cast_category(vehicle_body, "body_type"),
                    x_col="body_type",
                    y_col="vehicle_count",
                    title="Vehicle Body Type",
                    xaxis_title="Body Type",
                    yaxis_title="Vehicles",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            )
        else:
            vehicle_views.append(
                self.data_not_available_card(
                    detail="The vehicle body summary is unavailable.",
                    missing_items=["vehicle_body_type_distribution"],
                )
            )

        self._body.objects = [
            pn.Row(*top_row, sizing_mode="stretch_width"),
            pn.Row(*vehicle_views, sizing_mode="stretch_width"),
        ]


PAGE = DashboardPageDefinition(
    page_id="vehicle_ownership_type",
    title="Vehicle Ownership and Type",
    group_id="long_term_choices",
    order=26,
    page_cls=VehicleOwnershipTypePage,
    required_summary_ids=(
        "auto_ownership_distribution",
        "autonomous_vehicle_ownership_totals",
        "vehicle_age_distribution",
        "vehicle_fuel_type_distribution",
        "vehicle_body_type_distribution",
    ),
)

VehicleOwnershipTypePage.definition = PAGE
