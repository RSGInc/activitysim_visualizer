"""Long-term choices page for household vehicle ownership and vehicle mix."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, kpi_box
from dashboard.helpers.category_helpers import cap_numeric_category_data, nonempty
from dashboard.helpers.geography_helpers import rename_present
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def _cast_category(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Cast one chart category column to strings for stable display ordering."""
    return [
        (label, df.with_columns(pl.col(category_col).cast(pl.Utf8)))
        for label, df in nonempty(data_list)
    ]


def _normalize_vehicle_summary_columns(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    canonical_col: str,
    legacy_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Accept legacy summary column names while exposing one canonical chart column."""
    return [
        (
            label,
            rename_present(df, {legacy_col: canonical_col}),
        )
        for label, df in nonempty(data_list)
    ]


def _av_kpi_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, float]]:
    """Extract one autonomous-vehicle household total per run when available."""
    values: list[tuple[str, float]] = []
    for label, df in nonempty(data_list):
        if "household_with_autonomous_vehicle_count" not in df.columns or len(df) == 0:
            continue
        values.append((label, float(df["household_with_autonomous_vehicle_count"][0])))
    return values


class VehicleOwnershipTypePage(DashboardPage):
    """Reference page for multi-section summary-only pages without selectors."""

    def build_page(self) -> pn.viewable.Viewable:
        self._ownership_section = self.section(
            "vehicle_ownership_summary",
            render=self.render_ownership_summary,
        )
        self._vehicle_mix_section = self.section(
            "vehicle_ownership_mix",
            render=self.render_vehicle_mix,
        )
        return self.new_section(
            pn.pane.Markdown("## Vehicle Ownership and Type"),
            self._ownership_section,
            self._vehicle_mix_section,
            sizing_mode="stretch_width",
        )

    def _optional_summaries(self) -> dict[str, list[tuple[str, pl.DataFrame]] | None]:
        return self.optional_summaries_dict(*self.required_summary_ids)

    def _summary_only_unavailable(self) -> pn.Card:
        return self.summary_only_unavailable_card()

    def render_ownership_summary(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._optional_summaries()
        if not any(summary is not None for summary in summaries.values()):
            return [self._summary_only_unavailable()]

        top_row: list[pn.viewable.Viewable] = []
        auto_ownership = summaries["auto_ownership_distribution"]
        av_ownership = summaries["autonomous_vehicle_ownership_totals"]

        top_row.append(self.render_auto_ownership_chart(auto_ownership))

        top_row.append(self.render_autonomous_vehicle_kpi(av_ownership))

        return [pn.Row(*top_row, sizing_mode="stretch_width")]

    def render_vehicle_mix(self):
        if not self.state.run_labels:
            return []

        summaries = self._optional_summaries()
        if not any(summary is not None for summary in summaries.values()):
            return []

        vehicle_views: list[pn.viewable.Viewable] = []
        chart_specs = [
            (
                "vehicle_age_distribution",
                "age",
                "vehicle_age",
                "Vehicle Age",
                "Vehicle Age",
            ),
            (
                "vehicle_fuel_type_distribution",
                "fuel_type",
                "vehicle_fuel_type",
                "Vehicle Fuel Type",
                "Fuel Type",
            ),
            (
                "vehicle_body_type_distribution",
                "body_type",
                "vehicle_body_type",
                "Vehicle Body Type",
                "Body Type",
            ),
        ]

        for summary_id, canonical_col, legacy_col, title, xaxis_title in chart_specs:
            summary = summaries[summary_id]
            vehicle_views.append(
                self.render_vehicle_attribute_chart(
                    summary,
                    summary_id=summary_id,
                    canonical_col=canonical_col,
                    legacy_col=legacy_col,
                    title=title,
                    xaxis_title=xaxis_title,
                )
            )

        return [pn.Row(*vehicle_views, sizing_mode="stretch_width")]

    def render_auto_ownership_chart(self, summary_data):
        """Render household auto ownership or an unavailable card."""
        if summary_data is None:
            return self.data_not_available_card(
                detail="The auto ownership summary is unavailable.",
                missing_items=["auto_ownership_distribution"],
            )
        return bar_chart(
            cap_numeric_category_data(
                summary_data,
                category_col="household_vehicle_count",
                cap_value=4,
                value_cols=("household_count",),
            ),
            x_col="household_vehicle_count",
            y_col="household_count",
            title="Auto Ownership by Household Size",
            xaxis_title="Household Vehicles",
            yaxis_title="Households",
            pct_col="pct",
            as_percent=self.as_percent,
        )

    def render_autonomous_vehicle_kpi(self, summary_data):
        """Render the autonomous vehicle ownership KPI or an unavailable state."""
        if summary_data is None:
            return self.data_not_available_card(
                detail="The autonomous vehicle ownership summary is unavailable.",
                missing_items=["autonomous_vehicle_ownership_totals"],
            )
        av_values = _av_kpi_values(summary_data)
        if not av_values:
            return self.data_not_available_card(
                detail="The autonomous vehicle ownership summary is empty.",
                missing_items=["autonomous_vehicle_ownership_totals"],
            )
        return kpi_box(
            "Autonomous Vehicle Ownership",
            av_values,
            format_fn=lambda value: f"{value:,.0f}",
        )

    def render_vehicle_attribute_chart(
        self,
        summary_data,
        *,
        summary_id: str,
        canonical_col: str,
        legacy_col: str,
        title: str,
        xaxis_title: str,
    ):
        """Render one vehicle attribute distribution chart or its unavailable state."""
        if summary_data is None:
            return self.data_not_available_card(
                detail=f"The {title.lower()} summary is unavailable.",
                missing_items=[summary_id],
            )
        normalized = _normalize_vehicle_summary_columns(
            summary_data,
            canonical_col=canonical_col,
            legacy_col=legacy_col,
        )
        return bar_chart(
            _cast_category(normalized, canonical_col),
            x_col=canonical_col,
            y_col="vehicle_count",
            title=title,
            xaxis_title=xaxis_title,
            yaxis_title="Vehicles",
            pct_col="pct",
            as_percent=self.as_percent,
        )


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
