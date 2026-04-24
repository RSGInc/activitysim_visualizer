"""VMT validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


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
    def __init__(self, state, config: Config) -> None:
        super().__init__("VMT Validation", state, config)

        self.vmt_view_sel = pn.widgets.Select(
            name="Commercial VMT View",
            options=VMT_VIEW_OPTIONS,
            value=VMT_VIEW_OPTIONS[0],
        )
        self._watch_widget(self.vmt_view_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## VMT Validation"),
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

        vmt_view = self.vmt_view_sel.value

        commercial_vmt_data = self.get_filtered_view(
            "commercial_vmt",
            vmt_view,
            factory=lambda: commercial_vmt_chart_data(
                summaries["commercial_vmt_totals"],
                vmt_view,
            ),
        )

        bicycle_vmt_data = _nonempty(summaries["bicycle_vmt_by_facility_type"])

        commercial_vmt_chart = bar_chart(
            commercial_vmt_data,
            x_col="commercial_vehicle_type",
            y_col="vmt",
            title=f"External vs. Internal Commercial Vehicle VMT - {vmt_view}",
            xaxis_title="Commercial Vehicle Type",
            yaxis_title="Vehicle Miles Traveled",
            as_percent=self.as_percent,
        )

        bicycle_vmt_chart = bar_chart(
            bicycle_vmt_data,
            x_col="facility_type",
            y_col="bicycle_vmt",
            title="Bicycle VMT by Facility Type",
            xaxis_title="Bicycle Facility Type",
            yaxis_title="Bicycle VMT",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            pn.Row(
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Commercial VMT View:**"),
                        self.vmt_view_sel,
                    ),
                    commercial_vmt_chart,
                ),
                bicycle_vmt_chart,
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="vmt",
    title="VMT Validation",
    order=54,
    controller_cls=VMTValidationPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="commercial_vmt_view",
            widget_attr="vmt_view_sel",
            label="Commercial VMT View",
        ),
    ),
    required_summary_ids=(
        "commercial_vmt_totals",
        "bicycle_vmt_by_facility_type",
    ),
)

VMTValidationPage.definition = PAGE
