"""Long-term choices page: auto ownership, TLFD, telecommute, WFH, geography flows."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
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


class LongTermPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Long-Term", state, config)
        self.geo_sel: pn.widgets.Select | None = None
        if config.geography_enabled:
            geo_groups = self._geo_options(state.weighted_runs)
            self.geo_sel = pn.widgets.Select(
                name="Geography", options=geo_groups, value=geo_groups[0]
            )
            self._watch_widget(self.geo_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        header = [pn.pane.Markdown("## Long-Term Choices")]
        if self.geo_sel is not None:
            header.append(pn.Row(pn.pane.Markdown("**Geography:**"), self.geo_sel))
        self.view = pn.Column(*header, self._body, sizing_mode="stretch_width")

    def _geo_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        tlfd_list = self.state.get_precomputed_summary("tlfd_work", "weighted")
        if tlfd_list is None:
            tlfd_list = [
                (label, mandatory.tlfd(rd, self.config)["work"]) for label, rd in runs
            ]
        return geo_options(tlfd_list)

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        auto_own_list = self.get_summary(
            "auto_ownership",
            lambda: [
                (
                    label,
                    demographics.auto_ownership(rd).with_columns(
                        pl.col("HHVEH").cast(pl.Utf8)
                    ),
                )
                for label, rd in runs
            ],
        )
        work_tlfd_list = self.get_summary(
            "tlfd_work",
            lambda: [
                (label, mandatory.tlfd(rd, self.config)["work"]) for label, rd in runs
            ],
        )
        univ_tlfd_list = self.get_summary(
            "tlfd_univ",
            lambda: [
                (label, mandatory.tlfd(rd, self.config)["univ"]) for label, rd in runs
            ],
        )
        schl_tlfd_list = self.get_summary(
            "tlfd_schl",
            lambda: [
                (label, mandatory.tlfd(rd, self.config)["schl"]) for label, rd in runs
            ],
        )
        wfh_list = self.get_summary(
            "wfh",
            lambda: [(label, mandatory.wfh(rd, self.config)) for label, rd in runs],
        )
        tc_list = self.get_summary(
            "telecommute",
            lambda: [(label, mandatory.telecommute(rd)) for label, rd in runs],
        )
        mand_len_list = self.get_summary(
            "mand_tour_lengths",
            lambda: [
                (label, mandatory.mand_tour_lengths(rd, self.config))
                for label, rd in runs
            ],
        )

        auto_chart = bar_chart(
            auto_ownership_chart_data(auto_own_list),
            x_col="HHVEH",
            y_col="freq",
            title="Auto Ownership",
            xaxis_title="Vehicles",
            yaxis_title="Households",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        tc_chart = bar_chart(
            tc_list,
            x_col="telecommute_frequency",
            y_col="freq",
            title="Telecommute Frequency",
            xaxis_title="Frequency",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )
        wfh_chart = bar_chart(
            wfh_chart_data(wfh_list),
            x_col="Geography",
            y_col="WFH",
            title="Work From Home by Geography",
            xaxis_title="Geography",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )

        if self.config.geography_enabled and self.geo_sel is not None:
            geo_values = geo_options(work_tlfd_list)
            self.geo_sel.options = geo_values
            if self.geo_sel.value not in geo_values:
                self.geo_sel.value = geo_values[0]
            geo = self.geo_sel.value
            work_data, univ_data, schl_data = self.get_filtered_view(
                "long_term_tlfd",
                geo,
                factory=lambda: tlfd_chart_data(
                    work_tlfd_list, univ_tlfd_list, schl_tlfd_list, geo
                ),
            )
            tlfd_section = pn.Column(
                pn.pane.Markdown("### TLFD by geography:"),
                pn.Row(
                    density_chart(
                        work_data,
                        "distbin",
                        "freq",
                        "Work TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        univ_data,
                        "distbin",
                        "freq",
                        "University TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        schl_data,
                        "distbin",
                        "freq",
                        "School TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                ),
            )
            flow_list = self.get_summary(
                "geo_flows",
                lambda: [
                    (label, mandatory.geo_flows(rd, self.config)) for label, rd in runs
                ],
            )
            flow_widget = data_table(
                [
                    (label, df)
                    for label, df in flow_list
                    if df is not None and len(df) > 0
                ],
                "Home-Work Geography Flows",
            )
        else:
            work_data, univ_data, schl_data = self.get_filtered_view(
                "long_term_tlfd",
                "Total",
                factory=lambda: tlfd_chart_data(
                    work_tlfd_list, univ_tlfd_list, schl_tlfd_list, "Total"
                ),
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
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        univ_data,
                        "distbin",
                        "freq",
                        "University TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        schl_data,
                        "distbin",
                        "freq",
                        "School TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                ),
            )
            flow_widget = pn.pane.Markdown("*(Geography not enabled - no flow table)*")

        self._body.objects = [
            pn.Row(auto_chart),
            tlfd_section,
            pn.Row(tc_chart, wfh_chart),
            flow_widget,
            data_table(mand_len_list, "Average Mandatory Tour Lengths (miles)"),
        ]


PAGE = DashboardPageDefinition(
    page_id="long_term",
    title="Long-Term",
    order=20,
    controller_cls=LongTermPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="geography",
            widget_attr="geo_sel",
            label="Geography",
            enabled_when=lambda page, config: config.geography_enabled,
        ),
    ),
)
