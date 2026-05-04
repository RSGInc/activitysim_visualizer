"""Overview page: KPI boxes, person type distribution, HH size distribution."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import _to_pandas, bar_chart, kpi_box
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config

KPI_METRICS = [
    ("person_count", "Population"),
    ("household_count", "Households"),
    ("auto_vmt", "VMT"),
    ("tour_count", "Tours"),
    ("trip_count", "Trips"),
    ("stop_count", "Stops"),
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
    vmt_list: list[tuple[str, pl.DataFrame]],
) -> pl.DataFrame:
    """Build percent difference rows versus the first run."""
    if not totals_list or not vmt_list:
        return pl.DataFrame()
    pct_rows = []
    base_label, base_df = totals_list[0]
    _, base_vmt_df = vmt_list[0]
    for metric, label in KPI_METRICS:
        source_list = vmt_list if metric == "auto_vmt" else totals_list
        source_base = base_vmt_df if metric == "auto_vmt" else base_df
        base_val = metric_value(source_base, metric)
        row = {"Metric": label, base_label: "0.00%"}
        for run_label, source_df in source_list[1:]:
            val = metric_value(source_df, metric)
            pct = ((val - base_val) / base_val * 100.0) if base_val != 0 else 0.0
            row[run_label] = f"{pct:.2f}%"
        pct_rows.append(row)
    return pl.DataFrame(pct_rows) if pct_rows else pl.DataFrame()


def person_type_chart_data(
    pertype_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Cast person type labels for chart display."""
    return [
        (label, df.with_columns(pl.col("person_type_label").cast(pl.Utf8)))
        for label, df in pertype_list
    ]


def hh_size_chart_data(
    hhsize_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Cast household size labels for chart display."""
    return [
        (label, df.with_columns(pl.col("household_size").cast(pl.Utf8)))
        for label, df in hhsize_list
    ]


class OverviewPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self._body = self.section("body", render=self.render_body)
        return self._body

    def render_body(self) -> SectionContent:
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        objects: list[pn.viewable.Viewable] = [pn.pane.Markdown("## Overview")]

        kpi_result = self.resolve_summary_visualization(
            "overview_kpis",
            summary_requirements={
                "population_totals": (
                    "person_count",
                    "household_count",
                    "tour_count",
                    "trip_count",
                    "stop_count",
                ),
                "auto_vmt_totals": ("auto_vmt",),
            },
        )
        objects.append(pn.pane.Markdown("### Key Performance Indicators"))
        if kpi_result.has_usable_runs:
            totals_list = kpi_result.usable_by_input["population_totals"]
            vmt_list = kpi_result.usable_by_input["auto_vmt_totals"]
            pct_df = self.get_filtered_view(
                "overview_pct",
                tuple(label for label, _ in totals_list),
                factory=lambda: percent_difference_table(totals_list, vmt_list),
            )

            def _card(metric: str, label: str):
                return kpi_box(
                    label=label,
                    values=[
                        (run_label, metric_value(tot_df, metric))
                        for run_label, tot_df in totals_list
                    ],
                )

            vmt_box = kpi_box(
                label="VMT",
                values=[
                    (run_label, metric_value(tot_df, "auto_vmt"))
                    for run_label, tot_df in vmt_list
                ],
            )
            objects.extend(
                [
                    pn.Row(
                        _card("person_count", "Population"),
                        _card("household_count", "Households"),
                        vmt_box,
                        sizing_mode="stretch_width",
                    ),
                    pn.Row(
                        _card("tour_count", "Tours"),
                        _card("trip_count", "Trips"),
                        _card("stop_count", "Stops"),
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
                ]
            )
        else:
            objects.append(
                self.unavailable_visualization(
                    kpi_result,
                    detail="Overview KPIs require the population totals and auto VMT summary tables.",
                )
            )

        objects.append(pn.pane.Markdown("### Demographic Distributions"))
        ptype_result = self.resolve_summary_visualization(
            "overview_person_type_distribution",
            summary_requirements={
                "person_type_distribution": ("person_type_label", "person_count")
            },
        )
        hhsize_result = self.resolve_summary_visualization(
            "overview_household_size_distribution",
            summary_requirements={
                "household_size_distribution": ("household_size", "household_count")
            },
        )
        ptype_widget = (
            bar_chart(
                person_type_chart_data(
                    ptype_result.usable_by_input["person_type_distribution"]
                ),
                x_col="person_type_label",
                y_col="person_count",
                title="Person Type Distribution",
                xaxis_title="Person Type",
                yaxis_title="Persons",
                pct_col="pct",
                as_percent=self.as_percent,
            )
            if ptype_result.has_usable_runs
            else self.unavailable_visualization(
                ptype_result,
                detail="Person type distribution is unavailable.",
            )
        )
        hhsize_widget = (
            bar_chart(
                hh_size_chart_data(
                    hhsize_result.usable_by_input["household_size_distribution"]
                ),
                x_col="household_size",
                y_col="household_count",
                title="Household Size Distribution",
                xaxis_title="Household Size",
                yaxis_title="Households",
                pct_col="pct",
                as_percent=self.as_percent,
            )
            if hhsize_result.has_usable_runs
            else self.unavailable_visualization(
                hhsize_result,
                detail="Household size distribution is unavailable.",
            )
        )
        objects.append(pn.Row(ptype_widget, hhsize_widget))
        return objects


PAGE = DashboardPageDefinition(
    page_id="overview",
    title="Overview",
    order=10,
    page_cls=OverviewPage,
    required_summary_ids=(
        "population_totals",
        "person_type_distribution",
        "household_size_distribution",
        "auto_vmt_totals",
    ),
)

OverviewPage.definition = PAGE
