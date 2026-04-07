"""Persistent live-session page objects for the Panel dashboard."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard import DashboardState
from dashboard.components import (
    _to_pandas,
    bar_chart,
    data_table,
    density_chart,
    kpi_box,
)
from dashboard.page_base import DashboardPage
from dashboard.pages import (
    destination as destination_page,
    long_term as long_term_page,
    overview as overview_page,
    stop_freq as stop_freq_page,
    stop_location as stop_location_page,
    stop_timing,
    tour_summary as tour_summary_page,
    tour_mode as tour_mode_page,
    tour_tod as tour_tod_page,
    trip_mode as trip_mode_page,
)
from summarize import (
    demographics,
    destination as destination_sums,
    mandatory,
    stops,
    totals,
    tour_mode as tm,
    tour_tod as tod_sums,
    tours as tour_sums,
    trips,
)
from summarize.reader import Config, RunData


class OverviewPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Overview", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = self._body

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        totals_list = self.get_summary(
            "totals",
            lambda: [
                (label, totals.system_totals(rd, self.config)) for label, rd in runs
            ],
        )
        pertype_list = self.get_summary(
            "person_type",
            lambda: [
                (label, demographics.person_type(rd, self.config)) for label, rd in runs
            ],
        )
        hhsize_list = self.get_summary(
            "hh_size",
            lambda: [(label, demographics.hh_size(rd)) for label, rd in runs],
        )

        def _card(metric: str, label: str):
            return kpi_box(
                label=label,
                values=[
                    (
                        run_label,
                        overview_page.metric_value(tot_df, metric),
                    )
                    for run_label, tot_df in totals_list
                ],
            )

        pct_df = self.get_filtered_view(
            "overview_pct",
            factory=lambda: overview_page.percent_difference_table(totals_list),
        )

        ptype_chart = bar_chart(
            overview_page.person_type_chart_data(pertype_list),
            x_col="ptype_name",
            y_col="freq",
            title="Person Type Distribution",
            xaxis_title="Person Type",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        hhsize_chart = bar_chart(
            overview_page.hh_size_chart_data(hhsize_list),
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


class StopLocationPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Stop Location", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = self._body

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        loc_list = self.get_summary(
            "stop_location",
            lambda: [(label, stops.stop_location(rd)) for label, rd in runs],
        )
        purp_opts, run_to_purpose_col = stop_location_page.discover_purpose_columns(
            loc_list
        )

        charts = [
            density_chart(
                self.get_filtered_view(
                    "stop_location_all",
                    factory=lambda: stop_location_page.all_purpose_chart_data(loc_list),
                ),
                "distbin",
                "freq",
                "Stop Out-of-Direction Distance - All Purposes",
                "Miles",
                normalize=False,
                as_percent=self.as_percent,
            )
        ]
        for purp in purp_opts:
            charts.append(
                density_chart(
                    self.get_filtered_view(
                        "stop_location",
                        purp,
                        factory=lambda purp=purp: stop_location_page.purpose_chart_data(
                            loc_list, purp, run_to_purpose_col
                        ),
                    ),
                    "distbin",
                    "freq",
                    f"Stop Out-of-Direction Distance - {purp}",
                    "Miles",
                    normalize=False,
                    as_percent=self.as_percent,
                )
            )

        self._body.objects = [pn.pane.Markdown("## Stop Location"), *charts]


class TourSummaryPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Tour Summary", state, config)
        ptype_opts = self._ptype_options(state.weighted_runs)
        ptype_label_map = {
            p: ("Total" if str(p) == "Total" else config.ptype_label(p))
            for p in ptype_opts
        }
        self._label_to_ptype = {lbl: p for p, lbl in ptype_label_map.items()}
        display_opts = [ptype_label_map[p] for p in ptype_opts] or ["Total"]
        default_value = "Total" if "Total" in display_opts else display_opts[0]
        self.ptype_sel = pn.widgets.Select(
            name="Person Type",
            options=display_opts,
            value=default_value,
        )
        self._watch_widget(self.ptype_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Summary"),
            pn.Row(pn.pane.Markdown("**Person Type:**"), self.ptype_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _ptype_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        dap_list = self.state.get_precomputed_summary("dap_summary", "weighted")
        if dap_list is None:
            if not runs:
                return ["Total"]
            dap_list = [
                (label, tour_sums.dap_summary(rd, self.config)) for label, rd in runs
            ]
        if not dap_list:
            return ["Total"]
        return tour_summary_page.ptype_options(dap_list)

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        dap_list = self.get_summary(
            "dap_summary",
            lambda: [
                (label, tour_sums.dap_summary(rd, self.config)) for label, rd in runs
            ],
        )
        mtf_list = self.get_summary(
            "mandatory_tour_freq",
            lambda: [
                (label, tour_sums.mandatory_tour_freq(rd, self.config))
                for label, rd in runs
            ],
        )
        inm_list = self.get_summary(
            "indiv_nm_summary",
            lambda: [
                (label, tour_sums.indiv_nm_summary(rd, self.config))
                for label, rd in runs
            ],
        )
        ptype_opts = tour_summary_page.ptype_options(dap_list)
        ptype_label_map, self._label_to_ptype = tour_summary_page.ptype_maps(
            ptype_opts, self.config
        )
        display_opts = [ptype_label_map[p] for p in ptype_opts] or ["Total"]
        self.ptype_sel.options = display_opts
        if self.ptype_sel.value not in display_opts:
            self.ptype_sel.value = (
                "Total" if "Total" in display_opts else display_opts[0]
            )
        ptype_label = self.ptype_sel.value
        ptype = self._label_to_ptype.get(ptype_label, ptype_label)

        dap_data, mtf_data, inm_data = self.get_filtered_view(
            "tour_summary",
            ptype,
            factory=lambda: tour_summary_page.chart_data(
                dap_list, mtf_list, inm_list, ptype
            ),
        )

        dap_chart = bar_chart(
            dap_data,
            "DAP",
            "freq",
            f"Daily Activity Pattern - {ptype_label}",
            "Pattern",
            as_percent=self.as_percent,
        )
        mtf_chart = bar_chart(
            mtf_data,
            "MTF_label",
            "freq",
            f"Mandatory Tour Frequency - {ptype_label}",
            "Alternative",
            as_percent=self.as_percent,
        )
        inm_chart = bar_chart(
            inm_data,
            "nmtours",
            "freq",
            f"Individual NM Tours - {ptype_label}",
            "# Tours",
            as_percent=self.as_percent,
        )

        self._body.objects = [pn.Row(dap_chart, mtf_chart), inm_chart]


class LongTermPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
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
        return long_term_page.geo_options(tlfd_list)

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
            long_term_page.auto_ownership_chart_data(auto_own_list),
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
            long_term_page.wfh_chart_data(wfh_list),
            x_col="Geography",
            y_col="WFH",
            title="Work From Home by Geography",
            xaxis_title="Geography",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )

        if self.config.geography_enabled and self.geo_sel is not None:
            geo_options = long_term_page.geo_options(work_tlfd_list)
            self.geo_sel.options = geo_options
            if self.geo_sel.value not in geo_options:
                self.geo_sel.value = geo_options[0]
            geo = self.geo_sel.value
            work_data, univ_data, schl_data = self.get_filtered_view(
                "long_term_tlfd",
                geo,
                factory=lambda: long_term_page.tlfd_chart_data(
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
                factory=lambda: long_term_page.tlfd_chart_data(
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


class JointToursPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Joint Tours", state, config)
        self.hhsize_sel = pn.widgets.Select(
            name="HH Size", options=["Total", "2", "3", "4", "5"], value="Total"
        )
        self._watch_widget(self.hhsize_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Joint Tours"),
            pn.Row(pn.pane.Markdown("**HH Size:**"), self.hhsize_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        jtf_list = self.get_summary(
            "joint_tour_freq",
            lambda: [(label, tour_sums.joint_tour_freq(rd)) for label, rd in runs],
        )

        def _ordered_comp(df: pl.DataFrame) -> pl.DataFrame:
            if len(df) == 0:
                return df
            return (
                df.with_columns(
                    pl.col("tour_composition")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .alias("tour_composition")
                )
                .with_columns(
                    pl.when(pl.col("tour_composition") == "adults")
                    .then(0)
                    .when(pl.col("tour_composition") == "mixed")
                    .then(1)
                    .when(pl.col("tour_composition") == "children")
                    .then(2)
                    .otherwise(99)
                    .alias("_ord")
                )
                .sort("_ord")
                .drop("_ord")
            )

        comp_list = self.get_summary(
            "joint_composition",
            lambda: [
                (label, _ordered_comp(tour_sums.joint_composition(rd)))
                for label, rd in runs
            ],
        )
        party_list = self.get_summary(
            "joint_party_size",
            lambda: [
                (
                    label,
                    tour_sums.joint_party_size(rd).with_columns(
                        pl.col("NUMBER_HH").cast(pl.Utf8)
                    ),
                )
                for label, rd in runs
            ],
        )
        hhsize_list = self.get_summary(
            "joint_tours_hhsize",
            lambda: [(label, tour_sums.joint_tours_hhsize(rd)) for label, rd in runs],
        )

        def _ordered_presence(df: pl.DataFrame) -> pl.DataFrame:
            base = pl.DataFrame({"jointTours": ["0", "1", "2+"]})
            if len(df) == 0:
                return base.with_columns(pl.lit(0.0).alias("freq"))
            d = (
                df.with_columns(pl.col("jointTours").cast(pl.Utf8).alias("jointTours"))
                .group_by("jointTours")
                .agg(pl.col("freq").sum().alias("freq"))
            )
            return base.join(d, on="jointTours", how="left").with_columns(
                pl.col("freq").fill_null(0.0)
            )

        def _presence_for_hhsize(
            label: str, df: pl.DataFrame
        ) -> tuple[str, pl.DataFrame]:
            if hhsize == "Total":
                agg = _ordered_presence(df)
                total = float(agg["freq"].sum()) if len(agg) > 0 else 0.0
                if total > 0:
                    agg = agg.with_columns((pl.col("freq") / total * 100).alias("freq"))
                return (label, agg)
            return (
                label,
                _ordered_presence(df.filter(pl.col("hhsize").cast(pl.Utf8) == hhsize)),
            )

        hhsize = self.hhsize_sel.value
        hhsize_data = self.get_filtered_view(
            "joint_tours_hhsize",
            hhsize,
            factory=lambda: [
                _presence_for_hhsize(label, df) for label, df in hhsize_list
            ],
        )

        self._body.objects = [
            bar_chart(
                jtf_list,
                x_col="alt_name",
                y_col="freq",
                title="Joint Tour Frequency (21 alternatives)",
                xaxis_title="Alternative",
                yaxis_title="Households",
                height=450,
                as_percent=self.as_percent,
            ),
            pn.Row(
                bar_chart(
                    comp_list,
                    x_col="tour_composition",
                    y_col="freq",
                    title="Joint Tour Composition",
                    xaxis_title="Composition",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    party_list,
                    x_col="NUMBER_HH",
                    y_col="freq",
                    title="Joint Tour Party Size",
                    xaxis_title="Party Size",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                ),
            ),
            bar_chart(
                hhsize_data,
                "jointTours",
                "freq",
                f"Joint Tour Presence by HH Size ({hhsize})",
                "Joint Tours",
                "% HH",
                as_percent=self.as_percent,
            ),
        ]


class DestinationPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Destination", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Destination Choice (NM Tour Distances)"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        if runs:
            purp_opts, _ = destination_page.discover_purpose_columns(runs)
            return purp_opts
        dist_list = self.state.get_precomputed_summary(
            "destination_distance", "weighted"
        )
        if dist_list is not None:
            first_df = next((df for _, df in dist_list if len(df) > 0), pl.DataFrame())
            purposes = (
                sorted(
                    [
                        purpose
                        for purpose in first_df["purpose"]
                        .drop_nulls()
                        .unique()
                        .to_list()
                        if purpose != "All NM"
                    ]
                )
                if len(first_df) > 0 and "purpose" in first_df.columns
                else []
            )
            return ["All NM"] + purposes
        return ["All NM"]

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp_opts = self._purpose_options(runs)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purpose = self.purp_sel.value
        if runs:
            _, run_to_purpose_col = destination_page.discover_purpose_columns(runs)
            data = self.get_filtered_view(
                "destination_dist",
                purpose,
                factory=lambda: destination_page.distance_chart_data(
                    runs, purpose, run_to_purpose_col
                ),
            )
            avg_df = self.get_filtered_view(
                "destination_avg",
                tuple(self.purp_sel.options[1:]),
                factory=lambda: destination_page.average_distance_table(
                    runs, list(self.purp_sel.options[1:]), run_to_purpose_col
                ),
            )
        else:
            dist_list = self.get_summary(
                "destination_distance",
                lambda: [
                    (label, destination_sums.distance_distribution(rd))
                    for label, rd in runs
                ],
            )
            data = self.get_filtered_view(
                "destination_dist",
                purpose,
                factory=lambda: [
                    (
                        label,
                        df.with_columns(pl.col("purpose").cast(pl.Utf8))
                        .filter(pl.col("purpose") == purpose)
                        .select(["distbin", "freq"]),
                    )
                    for label, df in dist_list
                ],
            )
            avg_list = self.get_summary(
                "destination_average_distance",
                lambda: [
                    (label, destination_sums.average_distance(rd)) for label, rd in runs
                ],
            )
            rows = []
            for purp in self.purp_sel.options[1:]:
                row = {"Purpose": purp}
                for run_label, df in avg_list:
                    value = None
                    if len(df) > 0 and {"purpose", "avg_distance"}.issubset(df.columns):
                        match = df.with_columns(pl.col("purpose").cast(pl.Utf8)).filter(
                            pl.col("purpose") == purp
                        )
                        if len(match) > 0:
                            value = match["avg_distance"][0]
                    row[run_label] = (
                        round(float(value), 2) if value is not None else None
                    )
                rows.append(row)
            avg_df = pl.DataFrame(rows) if rows else pl.DataFrame()

        self._body.objects = [
            density_chart(
                data,
                "distbin",
                "freq",
                f"NM Tour Distance Distribution - {purpose}",
                "Distance (miles)",
                normalize=False,
                as_percent=self.as_percent,
            ),
            pn.pane.Markdown("### Average Tour Distances (miles)"),
            (
                pn.widgets.Tabulator(_to_pandas(avg_df), sizing_mode="stretch_width")
                if len(avg_df) > 0
                else pn.pane.Markdown("*(No distance data available)*")
            ),
        ]


class TourTODPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Tour TOD", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Time of Day"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        tod_list = self.state.get_precomputed_summary("tour_tod_profiles", "weighted")
        if tod_list is None:
            if not runs:
                return ["work"]
            tod_list = [(label, tod_sums.tod_profiles(rd)) for label, rd in runs]
        return tour_tod_page.purpose_options(tod_list)

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        tod_list = self.get_summary(
            "tour_tod_profiles",
            lambda: [(label, tod_sums.tod_profiles(rd)) for label, rd in runs],
        )
        purp_opts = tour_tod_page.purpose_options(tod_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purp = self.purp_sel.value

        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_tod",
            purp,
            factory=lambda: tour_tod_page.chart_data(tod_list, purp),
        )
        x_label = "Clock time (start at 03:00)"
        dur_plot = density_chart(
            dur_data,
            "duration_hours",
            "freq",
            f"Duration - {purp}",
            "Duration (hours)",
            as_percent=self.as_percent,
        )
        dur_plot.object.update_xaxes(dtick=1, tick0=0, showgrid=True)

        self._body.objects = [
            density_chart(
                dep_data,
                "clock_time",
                "freq",
                f"Departure - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            density_chart(
                arr_data,
                "clock_time",
                "freq",
                f"Arrival - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            dur_plot,
        ]


class TourModePage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Tour Mode", state, config)
        total_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=total_opts, value=total_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Mode Choice"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        mode_list = self.state.get_precomputed_summary("tour_mode_profile", "weighted")
        if mode_list is None:
            mode_list = [
                (label, tm.tour_mode_profile(rd, self.config)) for label, rd in runs
            ]
        return tour_mode_page.purpose_options(mode_list)

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        mode_list = self.get_summary(
            "tour_mode_profile",
            lambda: [
                (label, tm.tour_mode_profile(rd, self.config)) for label, rd in runs
            ],
        )
        purp_opts = tour_mode_page.purpose_options(mode_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purp = self.purp_sel.value

        charts_by_col = self.get_filtered_view(
            "tour_mode",
            purp,
            factory=lambda: tour_mode_page.charts_by_column(mode_list, purp),
        )

        def make_chart(col: str, title: str):
            data = charts_by_col[col]
            return bar_chart(
                data,
                x_col="tour_mode",
                y_col=col,
                title=title,
                xaxis_title="Mode",
                as_percent=self.as_percent,
            )

        body = [
            pn.Row(
                make_chart("freq_all", "All Households"),
                make_chart("freq_as0", "Zero Autos"),
            ),
            pn.Row(
                make_chart("freq_as1", "Autos < Workers"),
                make_chart("freq_as2", "Autos >= Workers"),
            ),
        ]

        if self.config.mode_groups:
            grouped_list = self.get_summary(
                "grouped_tour_mode_profile",
                lambda: [
                    (label, tm.grouped_tour_mode_profile(rd, self.config))
                    for label, rd in runs
                ],
            )
            body.extend(
                [
                    pn.pane.Markdown("### Grouped Mode Summary"),
                    bar_chart(
                        grouped_list,
                        x_col="mode_group",
                        y_col="freq_all",
                        title="Tour Mode (Grouped)",
                        xaxis_title="Mode Group",
                        as_percent=self.as_percent,
                    ),
                ]
            )

        self._body.objects = body


class StopFreqPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Stop Frequency", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Stop Frequency"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        stop_list = self.state.get_precomputed_summary("stop_freq", "weighted")
        if stop_list is None:
            stop_list = [(label, stops.stop_freq(rd)) for label, rd in runs]
        purp_opts, _ = stop_freq_page.discover_purpose_columns(stop_list)
        return purp_opts

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        stop_list = self.get_summary(
            "stop_freq",
            lambda: [(label, stops.stop_freq(rd)) for label, rd in runs],
        )
        purp_by_tp = self.get_summary(
            "stop_purpose_by_tour_purpose",
            lambda: [
                (label, stops.stop_purpose_by_tour_purpose(rd)) for label, rd in runs
            ],
        )
        purp_opts, purpose_col = stop_freq_page.discover_purpose_columns(stop_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value

        ob_data, ib_data, tot_data, purp_chart_data = self.get_filtered_view(
            "stop_freq",
            purp,
            factory=lambda: (
                *stop_freq_page.frequency_chart_data(stop_list, purp, purpose_col),
                stop_freq_page.purpose_chart_data(purp_by_tp, purp, purpose_col),
            ),
        )

        self._body.objects = [
            pn.Row(
                bar_chart(
                    ob_data,
                    "stops",
                    "freq",
                    f"Outbound Stops - {purp}",
                    "Stops",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    ib_data,
                    "stops",
                    "freq",
                    f"Inbound Stops - {purp}",
                    "Stops",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    tot_data,
                    "stops",
                    "freq",
                    f"Total Stops - {purp}",
                    "Stops",
                    as_percent=self.as_percent,
                ),
            ),
            bar_chart(
                purp_chart_data,
                "purpose",
                "freq",
                f"Stop Purpose - tour={purp}",
                "Stop Purpose",
                as_percent=self.as_percent,
            ),
        ]


class StopTimingPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Stop Timing", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Stop Timing"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        timing_list = self.state.get_precomputed_summary("stop_timing", "weighted")
        if timing_list is None:
            timing_list = [(label, stops.stop_timing(rd)) for label, rd in runs]
        purp_opts, _ = stop_timing.discover_purpose_columns(timing_list)
        return purp_opts

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        timing_list = self.get_summary(
            "stop_timing",
            lambda: [(label, stops.stop_timing(rd)) for label, rd in runs],
        )
        purp_opts, run_to_purpose_col = stop_timing.discover_purpose_columns(
            timing_list
        )
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value

        stop_dep, trip_dep = self.get_filtered_view(
            "stop_timing",
            purp,
            factory=lambda: stop_timing.chart_data(
                timing_list, purp, run_to_purpose_col
            ),
        )
        x_label = "Clock time (start at 03:00)"

        self._body.objects = [
            density_chart(
                trip_dep,
                "clock_time",
                "freq",
                f"Trip Departure - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            density_chart(
                stop_dep,
                "clock_time",
                "freq",
                f"Stop Departure - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
        ]


class TripModePage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Trip Mode", state, config)
        purp_opts, tmode_opts = self._options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value="Total"
        )
        self.tmode_sel = pn.widgets.Select(
            name="Tour Mode", options=["All"] + tmode_opts, value="All"
        )
        self._watch_widget(self.purp_sel)
        self._watch_widget(self.tmode_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Trip Mode Choice"),
            pn.Row(self.purp_sel, self.tmode_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _options(self, runs: list[tuple[str, RunData]]) -> tuple[list[str], list[str]]:
        trip_list = self.state.get_precomputed_summary("trip_mode_profile", "weighted")
        if trip_list is None:
            trip_list = [
                (label, trips.trip_mode_profile(rd, self.config)) for label, rd in runs
            ]
        purp_opts, tmode_opts, _ = trip_mode_page.discover_options(trip_list)
        return purp_opts, tmode_opts

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        tmode = self.tmode_sel.value
        trip_list = self.get_summary(
            "trip_mode_profile",
            lambda: [
                (label, trips.trip_mode_profile(rd, self.config)) for label, rd in runs
            ],
        )
        purp_opts, tmode_opts, run_to_purpose_col = trip_mode_page.discover_options(
            trip_list
        )
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value
        self.tmode_sel.options = ["All"] + tmode_opts
        if self.tmode_sel.value not in self.tmode_sel.options:
            self.tmode_sel.value = "All"
            tmode = self.tmode_sel.value

        filtered_trip_mode = self.get_filtered_view(
            "trip_mode",
            purp,
            tmode,
            factory=lambda: trip_mode_page.chart_data(
                trip_list, purp, tmode, run_to_purpose_col
            ),
        )

        self._body.objects = [
            bar_chart(
                filtered_trip_mode,
                "trip_mode",
                "freq",
                f"Trip Mode - {purp} / Tour Mode: {tmode}",
                "Trip Mode",
                as_percent=self.as_percent,
            )
        ]


def build_live_pages(state: DashboardState, config: Config) -> list[DashboardPage]:
    """Create the persistent page objects used by the live dashboard."""
    return [
        OverviewPage(state, config),
        LongTermPage(state, config),
        TourSummaryPage(state, config),
        JointToursPage(state, config),
        DestinationPage(state, config),
        TourTODPage(state, config),
        TourModePage(state, config),
        StopFreqPage(state, config),
        StopLocationPage(state, config),
        StopTimingPage(state, config),
        TripModePage(state, config),
    ]
