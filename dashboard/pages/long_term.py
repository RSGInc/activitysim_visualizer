"""Long-term choices page: auto ownership, TLFD, telecommute, WFH, geography flows."""
from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart, density_chart, data_table
from summarize.reader import RunData, Config
from summarize import demographics, mandatory


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    auto_own_list = [(l, demographics.auto_ownership(rd).with_columns(pl.col("HHVEH").cast(pl.Utf8)))
                     for l, rd in runs]
    tlfd_list     = [(l, mandatory.tlfd(rd, config)) for l, rd in runs]
    wfh_list      = [(l, mandatory.wfh(rd, config)) for l, rd in runs]
    tc_list       = [(l, mandatory.telecommute(rd)) for l, rd in runs]
    mand_len_list = [(l, mandatory.mand_tour_lengths(rd, config)) for l, rd in runs]

    auto_chart = bar_chart(
        auto_own_list, x_col="HHVEH", y_col="freq",
        title="Auto Ownership", xaxis_title="Vehicles", yaxis_title="Households", pct_col="pct",
    )

    tc_chart = bar_chart(
        tc_list, x_col="telecommute_frequency", y_col="freq",
        title="Telecommute Frequency", xaxis_title="Frequency", yaxis_title="Workers",
    )

    wfh_chart = bar_chart(
        [(l, df.select(["Geography", "WFH"])) for l, df in wfh_list if len(df) > 0],
        x_col="Geography", y_col="WFH",
        title="Work From Home by Geography", xaxis_title="Geography", yaxis_title="Workers",
    )

    # TLFD section with optional geography breakdown
    if config.geography_enabled:
        # Collect available geo groups from first run
        first_tlfd = tlfd_list[0][1]["work"] if tlfd_list else None
        geo_groups = (["Total"] + [c for c in first_tlfd.columns if c not in ("distbin", "Total")]
                      if first_tlfd is not None else ["Total"])
        geo_sel = pn.widgets.Select(name="Geography", options=geo_groups, value="Total")

        @pn.depends(geo_sel)
        def tlfd_charts(geo):
            col = geo if geo != "Total" else "Total"
            work_data = [(l, tlfs["work"].select(["distbin", col]).rename({col: "freq"}))
                         for l, tlfs in tlfd_list if col in tlfs["work"].columns]
            univ_data = [(l, tlfs["univ"].select(["distbin", col]).rename({col: "freq"}))
                         for l, tlfs in tlfd_list if col in tlfs["univ"].columns]
            schl_data = [(l, tlfs["schl"].select(["distbin", col]).rename({col: "freq"}))
                         for l, tlfs in tlfd_list if col in tlfs["schl"].columns]
            return pn.Column(pn.Row(
                density_chart(work_data, "distbin", "freq", "Work TLFD", "Distance (miles)", normalize=True),
                density_chart(univ_data, "distbin", "freq", "University TLFD", "Distance (miles)", normalize=True),
                density_chart(schl_data, "distbin", "freq", "School TLFD", "Distance (miles)", normalize=True),
            ))

        flow_list = [(l, mandatory.geo_flows(rd, config)) for l, rd in runs]
        flow_widget = data_table(
            [(l, df) for l, df in flow_list if df is not None and len(df) > 0],
            "Home–Work Geography Flows"
        )

        tlfd_section = pn.Column(
            pn.pane.Markdown("### TLFD by geography:"),
            geo_sel,
            tlfd_charts,
        )
    else:
        def tlfd_charts_static():
            work_data = [(l, tlfs["work"].select(["distbin", "Total"]).rename({"Total": "freq"}))
                         for l, tlfs in tlfd_list]
            univ_data = [(l, tlfs["univ"].select(["distbin", "Total"]).rename({"Total": "freq"}))
                         for l, tlfs in tlfd_list]
            schl_data = [(l, tlfs["schl"].select(["distbin", "Total"]).rename({"Total": "freq"}))
                         for l, tlfs in tlfd_list]
            return pn.Row(
                density_chart(work_data, "distbin", "freq", "Work TLFD", "Distance (miles)", normalize=True),
                density_chart(univ_data, "distbin", "freq", "University TLFD", "Distance (miles)", normalize=True),
                density_chart(schl_data, "distbin", "freq", "School TLFD", "Distance (miles)", normalize=True),
            )

        tlfd_section = pn.Column(
            pn.pane.Markdown("### Trip Length Frequency Distributions"),
            tlfd_charts_static(),
        )
        flow_widget = pn.pane.Markdown("*(Geography not enabled — no flow table)*")

    return pn.Column(
        pn.pane.Markdown("## Long-Term Choices"),
        pn.Row(auto_chart),
        tlfd_section,
        pn.Row(tc_chart, wfh_chart),
        flow_widget,
        data_table(mand_len_list, "Average Mandatory Tour Lengths (miles)"),
        sizing_mode="stretch_width",
    )

