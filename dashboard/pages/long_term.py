"""Long-term choices page: auto ownership, TLFD, telecommute, WFH, geography flows."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, density_chart
from summarize import demographics, mandatory
from summarize.reader import Config, RunData


def auto_ownership_chart_data(
    auto_own_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Cast HH vehicle ownership values for chart display."""
    return [
        (label, df.with_columns(pl.col("HHVEH").cast(pl.Utf8)))
        for label, df in auto_own_list
    ]


def wfh_chart_data(
    wfh_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Select WFH chart columns for non-empty summaries."""
    return [
        (label, df.select(["Geography", "WFH"]))
        for label, df in wfh_list
        if len(df) > 0
    ]


def geo_options(work_tlfd_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect geography selector options from work TLFD data."""
    first_tlfd = work_tlfd_list[0][1] if work_tlfd_list else None
    if first_tlfd is None:
        return ["Total"]
    return ["Total"] + [c for c in first_tlfd.columns if c not in ("distbin", "Total")]


def tlfd_chart_data(
    work_tlfd_list: list[tuple[str, pl.DataFrame]],
    univ_tlfd_list: list[tuple[str, pl.DataFrame]],
    schl_tlfd_list: list[tuple[str, pl.DataFrame]],
    geo: str,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build TLFD datasets for one geography selection."""
    col = geo if geo != "Total" else "Total"
    work_data = [
        (label, df.select(["distbin", col]).rename({col: "freq"}))
        for label, df in work_tlfd_list
        if col in df.columns
    ]
    univ_data = [
        (label, df.select(["distbin", col]).rename({col: "freq"}))
        for label, df in univ_tlfd_list
        if col in df.columns
    ]
    schl_data = [
        (label, df.select(["distbin", col]).rename({col: "freq"}))
        for label, df in schl_tlfd_list
        if col in df.columns
    ]
    return work_data, univ_data, schl_data


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    auto_own_list = [(label, demographics.auto_ownership(rd)) for label, rd in runs]
    tlfd_list = [(label, mandatory.tlfd(rd, config)) for label, rd in runs]
    work_tlfd_list = [(label, tlfs["work"]) for label, tlfs in tlfd_list]
    univ_tlfd_list = [(label, tlfs["univ"]) for label, tlfs in tlfd_list]
    schl_tlfd_list = [(label, tlfs["schl"]) for label, tlfs in tlfd_list]
    wfh_list = [(label, mandatory.wfh(rd, config)) for label, rd in runs]
    tc_list = [(label, mandatory.telecommute(rd)) for label, rd in runs]
    mand_len_list = [
        (label, mandatory.mand_tour_lengths(rd, config)) for label, rd in runs
    ]

    auto_chart = bar_chart(
        auto_ownership_chart_data(auto_own_list),
        x_col="HHVEH",
        y_col="freq",
        title="Auto Ownership",
        xaxis_title="Vehicles",
        yaxis_title="Households",
        pct_col="pct",
    )
    tc_chart = bar_chart(
        tc_list,
        x_col="telecommute_frequency",
        y_col="freq",
        title="Telecommute Frequency",
        xaxis_title="Frequency",
        yaxis_title="Workers",
    )
    wfh_chart = bar_chart(
        wfh_chart_data(wfh_list),
        x_col="Geography",
        y_col="WFH",
        title="Work From Home by Geography",
        xaxis_title="Geography",
        yaxis_title="Workers",
    )

    if config.geography_enabled:
        geo_groups = geo_options(work_tlfd_list)
        geo_sel = pn.widgets.Select(name="Geography", options=geo_groups, value="Total")

        @pn.depends(geo_sel)
        def tlfd_charts(geo):
            work_data, univ_data, schl_data = tlfd_chart_data(
                work_tlfd_list, univ_tlfd_list, schl_tlfd_list, geo
            )
            return pn.Column(
                pn.Row(
                    density_chart(
                        work_data,
                        "distbin",
                        "freq",
                        "Work TLFD",
                        "Distance (miles)",
                        normalize=False,
                    ),
                    density_chart(
                        univ_data,
                        "distbin",
                        "freq",
                        "University TLFD",
                        "Distance (miles)",
                        normalize=False,
                    ),
                    density_chart(
                        schl_data,
                        "distbin",
                        "freq",
                        "School TLFD",
                        "Distance (miles)",
                        normalize=False,
                    ),
                )
            )

        flow_list = [(label, mandatory.geo_flows(rd, config)) for label, rd in runs]
        flow_widget = data_table(
            [(label, df) for label, df in flow_list if df is not None and len(df) > 0],
            "Home-Work Geography Flows",
        )
        tlfd_section = pn.Column(
            pn.pane.Markdown("### TLFD by geography:"),
            geo_sel,
            tlfd_charts,
        )
    else:
        work_data, univ_data, schl_data = tlfd_chart_data(
            work_tlfd_list, univ_tlfd_list, schl_tlfd_list, "Total"
        )
        tlfd_section = pn.Column(
            pn.pane.Markdown("### Trip Length Frequency Distributions"),
            pn.Row(
                density_chart(
                    work_data,
                    "distbin",
                    "freq",
                    "Work TLFD",
                    "Distance (miles)",
                    normalize=False,
                ),
                density_chart(
                    univ_data,
                    "distbin",
                    "freq",
                    "University TLFD",
                    "Distance (miles)",
                    normalize=False,
                ),
                density_chart(
                    schl_data,
                    "distbin",
                    "freq",
                    "School TLFD",
                    "Distance (miles)",
                    normalize=False,
                ),
            ),
        )
        flow_widget = pn.pane.Markdown("*(Geography not enabled - no flow table)*")

    return pn.Column(
        pn.pane.Markdown("## Long-Term Choices"),
        pn.Row(auto_chart),
        tlfd_section,
        pn.Row(tc_chart, wfh_chart),
        flow_widget,
        data_table(mand_len_list, "Average Mandatory Tour Lengths (miles)"),
        sizing_mode="stretch_width",
    )
