"""VMT validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import (
    bar_chart,
    control_row,
    control_row_spacer,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

VMT_VIEW_OPTIONS = [
    "Total Commercial VMT",
    "External VMT Only",
    "Internal VMT Only",
    "External minus Internal VMT",
]


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def commercial_vmt_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    vmt_view: str,
) -> list[tuple[str, pl.DataFrame]]:
    value_col = {
        "Total Commercial VMT": "total_vmt",
        "External VMT Only": "external_vmt",
        "Internal VMT Only": "internal_vmt",
        "External minus Internal VMT": "vmt_difference",
    }[vmt_view]

    out = []
    for label, df in _nonempty(data_list):
        if value_col == "vmt_difference":
            df = df.with_columns(
                (pl.col("external_vmt") - pl.col("internal_vmt")).alias("vmt")
            )
        else:
            df = df.with_columns(pl.col(value_col).alias("vmt"))

        out.append(
            (
                label,
                df.select(
                    pl.col("commercial_vehicle_type"),
                    pl.col("vmt"),
                ),
            )
        )

    return out


class VMTValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self.vmt_view_sel = self.selector(
            "commercial_vmt_view",
            widget=pn.widgets.Select(
                name="Commercial VMT View",
                options=VMT_VIEW_OPTIONS,
                value=VMT_VIEW_OPTIONS[0],
            ),
            label="Commercial VMT View",
        )
        self._body = self.section(
            "vmt_body",
            selectors=("commercial_vmt_view",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## VMT Validation"),
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        commercial_vmt = self.state.get_summary_table_set(
            "commercial_vmt_totals",
            self.weighting_key,
        )
        bicycle_vmt = self.state.get_summary_table_set(
            "bicycle_vmt_by_facility_type",
            self.weighting_key,
        )

        vmt_view = self.vmt_view_sel.value
        commercial_vehicle_type_values = sorted(
            {
                str(value)
                for _, df in _nonempty(commercial_vmt or [])
                for value in (
                    df["commercial_vehicle_type"].cast(pl.Utf8).to_list()
                    if "commercial_vehicle_type" in df.columns
                    else []
                )
            }
        )

        if commercial_vmt is not None:
            commercial_vmt_data = self.get_filtered_view(
                "commercial_vmt",
                vmt_view,
                factory=lambda: commercial_vmt_chart_data(
                    commercial_vmt,
                    vmt_view,
                ),
            )
            commercial_vmt_chart: pn.viewable.Viewable = bar_chart(
                commercial_vmt_data,
                x_col="commercial_vehicle_type",
                y_col="vmt",
                title=f"External vs. Internal Commercial Vehicle VMT - {vmt_view}",
                xaxis_title="Commercial Vehicle Type",
                yaxis_title="Vehicle Miles Traveled",
                as_percent=self.as_percent,
                xaxis_categoryarray=commercial_vehicle_type_values,
            )
        else:
            commercial_vmt_chart = self.data_not_available_card(
                detail="Commercial VMT summaries are unavailable.",
                missing_items=["commercial_vmt_totals"],
            )

        if bicycle_vmt is not None:
            bicycle_vmt_chart: pn.viewable.Viewable = bar_chart(
                _nonempty(bicycle_vmt),
                x_col="facility_type",
                y_col="bicycle_vmt",
                title="Bicycle VMT by Facility Type",
                xaxis_title="Bicycle Facility Type",
                yaxis_title="Bicycle VMT",
                pct_col="pct",
                as_percent=self.as_percent,
            )
        else:
            bicycle_vmt_chart = self.data_not_available_card(
                detail="Bicycle VMT summaries are unavailable.",
                missing_items=["bicycle_vmt_by_facility_type"],
            )

        return [
            pn.Row(
                pn.Column(
                    control_row(
                        pn.pane.Markdown("**Commercial VMT View:**"),
                        self.vmt_view_sel,
                    ),
                    commercial_vmt_chart,
                ),
                pn.Column(control_row_spacer(), bicycle_vmt_chart),
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="vmt",
    title="VMT Validation",
    group_id="validation",
    order=54,
    page_cls=VMTValidationPage,
    required_summary_ids=(
        "commercial_vmt_totals",
        "bicycle_vmt_by_facility_type",
    ),
)

VMTValidationPage.definition = PAGE
