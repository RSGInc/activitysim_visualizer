"""Overview page: KPI boxes, person type distribution, HH size distribution."""

from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart, kpi_box, _to_pandas
from summarize.reader import RunData, Config
from summarize import demographics, totals


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    """Build Overview page."""
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    totals_list = [(label, totals.system_totals(rd, config)) for label, rd in runs]
    pertype_list = [(label, demographics.person_type(rd, config)) for label, rd in runs]
    hhsize_list = [(label, demographics.hh_size(rd)) for label, rd in runs]

    kpi_metrics = [
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
    kpi_labels = [
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
    kpi_icons = {
        "population": "👤",
        "households": "🏠",
        "employment": "💼",
        "tours": "🧭",
        "trips": "🚗",
        "stops": "🛑",
        "pmt": "📏",
        "vmt": "🛣️",
        "vehicle_trips": "🚙",
    }

    def _card(metric: str, label: str):
        return kpi_box(
            label=label,
            values=[
                (
                    run_label,
                    (
                        float(tot_df[metric][0])
                        if metric in tot_df.columns and len(tot_df) > 0
                        else 0
                    ),
                )
                for run_label, tot_df in totals_list
            ],
            icon=kpi_icons.get(metric, ""),
        )

    kpi_row_1 = pn.Row(
        _card("population", "Population"),
        _card("households", "Households"),
        _card("vmt", "VMT"),
        sizing_mode="stretch_width",
    )
    kpi_row_2 = pn.Row(
        _card("tours", "Tours"),
        _card("trips", "Trips"),
        _card("stops", "Stops"),
        sizing_mode="stretch_width",
    )

    # Percent difference table vs first run (base)
    pct_rows = []
    base_label, base_df = totals_list[0]
    for met, lbl in zip(kpi_metrics, kpi_labels):
        base_val = (
            float(base_df[met][0])
            if met in base_df.columns and len(base_df) > 0
            else 0.0
        )
        row = {"Metric": lbl, base_label: "0.00%"}
        for run_label, tot_df in totals_list[1:]:
            val = (
                float(tot_df[met][0])
                if met in tot_df.columns and len(tot_df) > 0
                else 0.0
            )
            pct = ((val - base_val) / base_val * 100.0) if base_val != 0 else 0.0
            row[run_label] = f"{pct:.2f}%"
        pct_rows.append(row)
    pct_df = pl.DataFrame(pct_rows) if pct_rows else pl.DataFrame()

    # person_type returns ptype + ptype_name
    ptype_chart = bar_chart(
        [
            (label, df.with_columns(pl.col("ptype_name").cast(pl.Utf8)))
            for label, df in pertype_list
        ],
        x_col="ptype_name",
        y_col="freq",
        title="Person Type Distribution",
        xaxis_title="Person Type",
        yaxis_title="Persons",
        pct_col="pct",
    )

    hhsize_chart = bar_chart(
        [
            (label, df.with_columns(pl.col("HHSIZE").cast(pl.Utf8)))
            for label, df in hhsize_list
        ],
        x_col="HHSIZE",
        y_col="freq",
        title="Household Size Distribution",
        xaxis_title="HH Size",
        yaxis_title="Households",
        pct_col="pct",
    )

    return pn.Column(
        pn.pane.Markdown("## Overview"),
        pn.pane.Markdown("### Key Performance Indicators"),
        kpi_row_1,
        kpi_row_2,
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
        sizing_mode="stretch_width",
    )
