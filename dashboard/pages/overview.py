"""Overview page: KPI boxes, person type distribution, HH size distribution."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import _to_pandas, bar_chart, kpi_box
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from summarize.reader import Config

KPI_METRICS = [
    "population",
    "households",
    "employment",
    "tours",
    "trips",
    "stops",
    "pmt",
    "vmt",
    "vehicle_trips",
]

KPI_LABELS = [
    "Population",
    "Households",
    "Employment",
    "Tours",
    "Trips",
    "Stops",
    "PMT",
    "VMT",
    "Vehicle Trips",
]

KPI_ICONS = {
    "population": "",
    "households": "",
    "employment": "",
    "tours": "",
    "trips": "",
    "stops": "",
    "pmt": "",
    "vmt": "",
    "vehicle_trips": "",
}


def metric_value(df: pl.DataFrame, metric: str) -> float:
    """Return one KPI value from a totals table."""
    return float(df[metric][0]) if metric in df.columns and len(df) > 0 else 0.0


def percent_difference_table(
    totals_list: list[tuple[str, pl.DataFrame]],
) -> pl.DataFrame:
    """Build percent difference rows versus the first run."""
    if not totals_list:
        return pl.DataFrame()
    pct_rows = []
    base_label, base_df = totals_list[0]
    for metric, label in zip(KPI_METRICS, KPI_LABELS):
        base_val = metric_value(base_df, metric)
        row = {"Metric": label, base_label: "0.00%"}
        for run_label, tot_df in totals_list[1:]:
            val = metric_value(tot_df, metric)
            pct = ((val - base_val) / base_val * 100.0) if base_val != 0 else 0.0
            row[run_label] = f"{pct:.2f}%"
        pct_rows.append(row)
    return pl.DataFrame(pct_rows) if pct_rows else pl.DataFrame()


def person_type_chart_data(
    pertype_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Cast person type labels for chart display."""
    return [
        (label, df.with_columns(pl.col("ptype_name").cast(pl.Utf8)))
        for label, df in pertype_list
    ]


def hh_size_chart_data(
    hhsize_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Cast household size labels for chart display."""
    return [
        (label, df.with_columns(pl.col("HHSIZE").cast(pl.Utf8)))
        for label, df in hhsize_list
    ]


class OverviewPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Overview", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = self._body

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                pn.pane.Markdown("## Overview"),
                self.data_not_available_card(
                    detail=(
                        "This page only renders from precomputed summary tables."
                    ),
                    missing_items=list(self.required_summary_ids),
                ),
            ]
            return

        totals_list = summaries["totals"]
        pertype_list = summaries["person_type"]
        hhsize_list = summaries["hh_size"]
        pct_df = self.get_filtered_view(
            "overview_pct",
            factory=lambda: percent_difference_table(totals_list),
        )

        def _card(metric: str, label: str):
            return kpi_box(
                label=label,
                values=[
                    (
                        run_label,
                        metric_value(tot_df, metric),
                    )
                    for run_label, tot_df in totals_list
                ],
            )

        ptype_chart = bar_chart(
            person_type_chart_data(pertype_list),
            x_col="ptype_name",
            y_col="freq",
            title="Person Type Distribution",
            xaxis_title="Person Type",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        hhsize_chart = bar_chart(
            hh_size_chart_data(hhsize_list),
            x_col="HHSIZE",
            y_col="freq",
            title="Household Size Distribution",
            xaxis_title="HH Size",
            yaxis_title="Households",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            pn.pane.Markdown("## Overview"),
            pn.pane.Markdown("### Key Performance Indicators"),
            pn.Row(
                _card("population", "Population"),
                _card("households", "Households"),
                _card("vmt", "VMT"),
                sizing_mode="stretch_width",
            ),
            pn.Row(
                _card("tours", "Tours"),
                _card("trips", "Trips"),
                _card("stops", "Stops"),
                sizing_mode="stretch_width",
            ),
            pn.pane.Markdown("### Percent Difference vs Base Run"),
            (
                pn.widgets.Tabulator(
                    _to_pandas(pct_df), sizing_mode="stretch_width", height=260
                )
                if len(pct_df) > 0
                else pn.pane.Markdown("")
            ),
            pn.pane.Markdown("### Demographic Distributions"),
            pn.Row(ptype_chart, hhsize_chart),
        ]


PAGE = DashboardPageDefinition(
    page_id="overview",
    title="Overview",
    order=10,
    controller_cls=OverviewPage,
    required_summary_ids=("totals", "person_type", "hh_size"),
)

OverviewPage.definition = PAGE
