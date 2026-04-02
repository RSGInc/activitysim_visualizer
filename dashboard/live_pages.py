"""Persistent live-session page objects for the Panel dashboard."""
from __future__ import annotations

import panel as pn
import polars as pl

from dashboard import DashboardState
from dashboard.components import _to_pandas, bar_chart, data_table, density_chart, kpi_box
from dashboard.page_base import DashboardPage
from dashboard.pages import (
    stop_timing,
    tour_tod,
)
from summarize import demographics, destination as destination_sums, mandatory, stops, totals, tour_mode as tm, tour_tod as tod_sums, tours as tour_sums, trips
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
            lambda: [(label, totals.system_totals(rd, self.config)) for label, rd in runs],
        )
        pertype_list = self.get_summary(
            "person_type",
            lambda: [(label, demographics.person_type(rd, self.config)) for label, rd in runs],
        )
        hhsize_list = self.get_summary(
            "hh_size",
            lambda: [(label, demographics.hh_size(rd)) for label, rd in runs],
        )

        kpi_metrics = ["population", "households", "employment", "tours", "trips", "stops", "pmt", "vmt", "vehicle_trips"]
        kpi_labels = ["Population", "Households", "Employment", "Tours", "Trips", "Stops", "PMT", "VMT", "Vehicle Trips"]
        def _card(metric: str, label: str):
            return kpi_box(
                label=label,
                values=[
                    (run_label, float(tot_df[metric][0]) if metric in tot_df.columns and len(tot_df) > 0 else 0.0)
                    for run_label, tot_df in totals_list
                ],
            )

        pct_rows = []
        base_label, base_df = totals_list[0]
        for met, lbl in zip(kpi_metrics, kpi_labels):
            base_val = float(base_df[met][0]) if met in base_df.columns and len(base_df) > 0 else 0.0
            row = {"Metric": lbl, base_label: "0.00%"}
            for run_label, tot_df in totals_list[1:]:
                val = float(tot_df[met][0]) if met in tot_df.columns and len(tot_df) > 0 else 0.0
                pct = ((val - base_val) / base_val * 100.0) if base_val != 0 else 0.0
                row[run_label] = f"{pct:.2f}%"
            pct_rows.append(row)
        pct_df = pl.DataFrame(pct_rows) if pct_rows else pl.DataFrame()

        ptype_chart = bar_chart(
            [(label, df.with_columns(pl.col("ptype_name").cast(pl.Utf8))) for label, df in pertype_list],
            x_col="ptype_name",
            y_col="freq",
            title="Person Type Distribution",
            xaxis_title="Person Type",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        hhsize_chart = bar_chart(
            [(label, df.with_columns(pl.col("HHSIZE").cast(pl.Utf8))) for label, df in hhsize_list],
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
            pn.widgets.Tabulator(_to_pandas(pct_df), sizing_mode="stretch_width", height=260)
            if len(pct_df) > 0
            else pn.pane.Markdown(""),
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
        first_df = next((df for _, df in loc_list if len(df) > 0), pl.DataFrame())
        if len(first_df) > 0 and "primary_purpose" in first_df.columns:
            purp_opts = sorted(first_df["primary_purpose"].drop_nulls().unique().to_list())
        else:
            purp_opts = []

        charts = []
        all_data = [
            (label, df.group_by("distbin").agg(pl.col("freq").sum()).sort("distbin"))
            for label, df in loc_list
        ]
        charts.append(
            density_chart(
                all_data,
                "distbin",
                "freq",
                "Stop Out-of-Direction Distance - All Purposes",
                "Miles",
                normalize=False,
                as_percent=self.as_percent,
            )
        )
        for purp in purp_opts:
            data = [
                (label, df.filter(pl.col("primary_purpose") == purp).select(["distbin", "freq"]))
                for label, df in loc_list
            ]
            charts.append(
                density_chart(
                    data,
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
            dap_list = [(label, tour_sums.dap_summary(rd, self.config)) for label, rd in runs]
        if not dap_list:
            return ["Total"]
        first_dap = next((df for _, df in dap_list if len(df) > 0), pl.DataFrame())
        if len(first_dap) == 0 or "ptype" not in first_dap.columns:
            return ["Total"]
        return sorted(first_dap["ptype"].unique().to_list())

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        ptype_label = self.ptype_sel.value
        ptype = self._label_to_ptype.get(ptype_label, ptype_label)

        dap_list = self.get_summary(
            "dap_summary",
            lambda: [(label, tour_sums.dap_summary(rd, self.config)) for label, rd in runs],
        )
        mtf_list = self.get_summary(
            "mandatory_tour_freq",
            lambda: [(label, tour_sums.mandatory_tour_freq(rd, self.config)) for label, rd in runs],
        )
        inm_list = self.get_summary(
            "indiv_nm_summary",
            lambda: [(label, tour_sums.indiv_nm_summary(rd, self.config)) for label, rd in runs],
        )

        def _ordered_dap(df: pl.DataFrame) -> pl.DataFrame:
            d = df.filter(pl.col("ptype") == ptype)
            base = pl.DataFrame({"DAP": ["M", "N", "H"]})
            return (
                base.join(
                    d.select([pl.col("DAP").cast(pl.Utf8).alias("DAP"), "freq"]),
                    on="DAP",
                    how="left",
                )
                .with_columns(pl.col("freq").fill_null(0.0))
                .with_columns(
                    pl.when(pl.col("DAP") == "M").then(0)
                    .when(pl.col("DAP") == "N").then(1)
                    .otherwise(2)
                    .alias("_ord")
                )
                .sort("_ord")
                .drop("_ord")
            )

        def _ordered_mtf(df: pl.DataFrame) -> pl.DataFrame:
            d = df.filter(pl.col("ptype") == ptype).with_columns(pl.col("MTF").cast(pl.Int64).alias("MTF"))
            base = pl.DataFrame({"MTF": [1, 2, 3, 4, 5]})
            labels = pl.DataFrame(
                {
                    "MTF": [1, 2, 3, 4, 5],
                    "MTF_label": ["work1", "work2", "school1", "school2", "work and school"],
                }
            )
            return (
                base.join(d.select(["MTF", "freq"]), on="MTF", how="left")
                .with_columns(pl.col("freq").fill_null(0.0))
                .join(labels, on="MTF", how="left")
                .select(["MTF_label", "freq"])
            )

        def _ordered_inm(df: pl.DataFrame) -> pl.DataFrame:
            d = df.filter(pl.col("ptype") == ptype).with_columns(pl.col("nmtours").cast(pl.Utf8).alias("nmtours"))
            base = pl.DataFrame({"nmtours": ["0", "1", "2", "3pl"]})
            return (
                base.join(d.select(["nmtours", "freq"]), on="nmtours", how="left")
                .with_columns(pl.col("freq").fill_null(0.0))
            )

        dap_data, mtf_data, inm_data = self.get_filtered_view(
            "tour_summary",
            ptype,
            factory=lambda: (
                [(label, _ordered_dap(df)) for label, df in dap_list],
                [(label, _ordered_mtf(df)) for label, df in mtf_list],
                [(label, _ordered_inm(df)) for label, df in inm_list],
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
            self.geo_sel = pn.widgets.Select(name="Geography", options=geo_groups, value=geo_groups[0])
            self._watch_widget(self.geo_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        header = [pn.pane.Markdown("## Long-Term Choices")]
        if self.geo_sel is not None:
            header.append(pn.Row(pn.pane.Markdown("**Geography:**"), self.geo_sel))
        self.view = pn.Column(*header, self._body, sizing_mode="stretch_width")

    def _geo_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        tlfd_list = self.state.get_precomputed_summary("tlfd_work", "weighted")
        if tlfd_list is None:
            tlfd_list = [(label, mandatory.tlfd(rd, self.config)["work"]) for label, rd in runs]
        first_tlfd = tlfd_list[0][1] if tlfd_list else None
        if first_tlfd is None:
            return ["Total"]
        return ["Total"] + [c for c in first_tlfd.columns if c not in ("distbin", "Total")]

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        auto_own_list = self.get_summary(
            "auto_ownership",
            lambda: [
                (label, demographics.auto_ownership(rd).with_columns(pl.col("HHVEH").cast(pl.Utf8)))
                for label, rd in runs
            ],
        )
        work_tlfd_list = self.get_summary(
            "tlfd_work",
            lambda: [(label, mandatory.tlfd(rd, self.config)["work"]) for label, rd in runs],
        )
        univ_tlfd_list = self.get_summary(
            "tlfd_univ",
            lambda: [(label, mandatory.tlfd(rd, self.config)["univ"]) for label, rd in runs],
        )
        schl_tlfd_list = self.get_summary(
            "tlfd_schl",
            lambda: [(label, mandatory.tlfd(rd, self.config)["schl"]) for label, rd in runs],
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
            lambda: [(label, mandatory.mand_tour_lengths(rd, self.config)) for label, rd in runs],
        )

        auto_chart = bar_chart(
            auto_own_list,
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
            [(label, df.select(["Geography", "WFH"])) for label, df in wfh_list if len(df) > 0],
            x_col="Geography",
            y_col="WFH",
            title="Work From Home by Geography",
            xaxis_title="Geography",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )

        if self.config.geography_enabled and self.geo_sel is not None:
            geo = self.geo_sel.value
            col = geo if geo != "Total" else "Total"
            work_data, univ_data, schl_data = self.get_filtered_view(
                "long_term_tlfd",
                geo,
                factory=lambda: (
                    [
                        (label, df.select(["distbin", col]).rename({col: "freq"}))
                        for label, df in work_tlfd_list
                        if col in df.columns
                    ],
                    [
                        (label, df.select(["distbin", col]).rename({col: "freq"}))
                        for label, df in univ_tlfd_list
                        if col in df.columns
                    ],
                    [
                        (label, df.select(["distbin", col]).rename({col: "freq"}))
                        for label, df in schl_tlfd_list
                        if col in df.columns
                    ],
                ),
            )
            tlfd_section = pn.Column(
                pn.pane.Markdown("### TLFD by geography:"),
                pn.Row(
                    density_chart(work_data, "distbin", "freq", "Work TLFD", "Distance (miles)", normalize=False, as_percent=self.as_percent),
                    density_chart(univ_data, "distbin", "freq", "University TLFD", "Distance (miles)", normalize=False, as_percent=self.as_percent),
                    density_chart(schl_data, "distbin", "freq", "School TLFD", "Distance (miles)", normalize=False, as_percent=self.as_percent),
                ),
            )
            flow_list = self.get_summary(
                "geo_flows",
                lambda: [(label, mandatory.geo_flows(rd, self.config)) for label, rd in runs],
            )
            flow_widget = data_table(
                [(label, df) for label, df in flow_list if df is not None and len(df) > 0],
                "Home-Work Geography Flows",
            )
        else:
            work_data = [
                (label, df.select(["distbin", "Total"]).rename({"Total": "freq"}))
                for label, df in work_tlfd_list
            ]
            univ_data = [
                (label, df.select(["distbin", "Total"]).rename({"Total": "freq"}))
                for label, df in univ_tlfd_list
            ]
            schl_data = [
                (label, df.select(["distbin", "Total"]).rename({"Total": "freq"}))
                for label, df in schl_tlfd_list
            ]
            tlfd_section = pn.Column(
                pn.pane.Markdown("### Trip Length Frequency Distributions"),
                pn.Row(
                    density_chart(work_data, "distbin", "freq", "Work TLFD", "Distance (miles)", normalize=False, as_percent=self.as_percent),
                    density_chart(univ_data, "distbin", "freq", "University TLFD", "Distance (miles)", normalize=False, as_percent=self.as_percent),
                    density_chart(schl_data, "distbin", "freq", "School TLFD", "Distance (miles)", normalize=False, as_percent=self.as_percent),
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
        self.hhsize_sel = pn.widgets.Select(name="HH Size", options=["Total", "2", "3", "4", "5"], value="Total")
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
                    pl.col("tour_composition").cast(pl.Utf8).str.to_lowercase().alias("tour_composition")
                )
                .with_columns(
                    pl.when(pl.col("tour_composition") == "adults").then(0)
                    .when(pl.col("tour_composition") == "mixed").then(1)
                    .when(pl.col("tour_composition") == "children").then(2)
                    .otherwise(99)
                    .alias("_ord")
                )
                .sort("_ord")
                .drop("_ord")
            )

        comp_list = self.get_summary(
            "joint_composition",
            lambda: [(label, _ordered_comp(tour_sums.joint_composition(rd))) for label, rd in runs],
        )
        party_list = self.get_summary(
            "joint_party_size",
            lambda: [
                (label, tour_sums.joint_party_size(rd).with_columns(pl.col("NUMBER_HH").cast(pl.Utf8)))
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
            return base.join(d, on="jointTours", how="left").with_columns(pl.col("freq").fill_null(0.0))

        def _presence_for_hhsize(label: str, df: pl.DataFrame) -> tuple[str, pl.DataFrame]:
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
            factory=lambda: [_presence_for_hhsize(label, df) for label, df in hhsize_list],
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
        self.purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value=purp_opts[0])
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Destination Choice (NM Tour Distances)"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        dist_list = self.state.get_precomputed_summary("destination_distance", "weighted")
        if dist_list is not None:
            first_df = next((df for _, df in dist_list if len(df) > 0), pl.DataFrame())
            purposes = (
                sorted(
                    [
                        purpose
                        for purpose in first_df["purpose"].drop_nulls().unique().to_list()
                        if purpose != "All NM"
                    ]
                )
                if len(first_df) > 0 and "purpose" in first_df.columns
                else []
            )
            return ["All NM"] + purposes
        if not runs:
            return ["All NM"]
        first_rd = runs[0][1]
        if "tour_category" in first_rd.tours.columns and "primary_purpose" in first_rd.tours.columns:
            nm_tours = first_rd.tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"]))
            purposes = sorted(nm_tours["primary_purpose"].drop_nulls().unique().to_list())
        else:
            purposes = []
        return ["All NM"] + purposes

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purpose = self.purp_sel.value
        dist_list = self.get_summary(
            "destination_distance",
            lambda: [(label, destination_sums.distance_distribution(rd)) for label, rd in runs],
        )
        data = self.get_filtered_view(
            "destination_dist",
            purpose,
            factory=lambda: [
                (
                    label,
                    df.filter(pl.col("purpose") == purpose).select(["distbin", "freq"]),
                )
                for label, df in dist_list
            ],
        )
        avg_list = self.get_summary(
            "destination_average_distance",
            lambda: [(label, destination_sums.average_distance(rd)) for label, rd in runs],
        )
        rows = []
        for purp in self.purp_sel.options[1:]:
            row = {"Purpose": purp}
            for run_label, df in avg_list:
                value = None
                if len(df) > 0 and {"purpose", "avg_distance"}.issubset(df.columns):
                    match = df.filter(pl.col("purpose") == purp)
                    if len(match) > 0:
                        value = match["avg_distance"][0]
                row[run_label] = round(float(value), 2) if value is not None else None
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
            pn.widgets.Tabulator(_to_pandas(avg_df), sizing_mode="stretch_width")
            if len(avg_df) > 0
            else pn.pane.Markdown("*(No distance data available)*"),
        ]


class TourTODPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Tour TOD", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value=purp_opts[0])
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
        first_df = next((df for _, df in tod_list if len(df) > 0), pl.DataFrame())
        if len(first_df) > 0 and "purpose" in first_df.columns:
            purposes = sorted(first_df["purpose"].drop_nulls().unique().to_list())
            return ["Total"] + [p for p in purposes if p != "Total"]
        return ["work"]

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        tod_list = self.get_summary(
            "tour_tod_profiles",
            lambda: [(label, tod_sums.tod_profiles(rd)) for label, rd in runs],
        )
        maxbin = 48
        for _, df in tod_list:
            if len(df) > 0 and "timebin" in df.columns:
                maxbin = int(df["timebin"].max())
                break

        def _prep(df: pl.DataFrame, val_col: str) -> pl.DataFrame:
            return (
                df.filter(pl.col("purpose") == purp)
                .select(["timebin", val_col])
                .rename({val_col: "freq"})
                .with_columns(
                    pl.col("timebin").map_elements(
                        lambda tb: tour_tod._time_label(int(tb), maxbin),
                        return_dtype=pl.Utf8,
                    ).alias("clock_time")
                )
            )

        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_tod",
            purp,
            factory=lambda: (
                [(label, _prep(df, "freq_dep")) for label, df in tod_list],
                [(label, _prep(df, "freq_arr")) for label, df in tod_list],
                [
                    (
                        label,
                        _prep(df, "freq_dur").with_columns(
                            pl.col("timebin").map_elements(
                                lambda tb: tour_tod._duration_hours(int(tb), maxbin),
                                return_dtype=pl.Float64,
                            ).alias("duration_hours")
                        ),
                    )
                    for label, df in tod_list
                ],
            ),
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
            density_chart(dep_data, "clock_time", "freq", f"Departure - {purp}", x_label, as_percent=self.as_percent),
            density_chart(arr_data, "clock_time", "freq", f"Arrival - {purp}", x_label, as_percent=self.as_percent),
            dur_plot,
        ]


class TourModePage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Tour Mode", state, config)
        total_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(name="Purpose", options=total_opts, value=total_opts[0])
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
            mode_list = [(label, tm.tour_mode_profile(rd, self.config)) for label, rd in runs]
        purpose_set = set()
        for _, df in mode_list:
            if len(df) > 0 and "purpose" in df.columns:
                purpose_set.update(df["purpose"].drop_nulls().to_list())
        purposes = sorted(list(purpose_set))
        return (["Total"] + [p for p in purposes if p != "Total"]) if purposes else ["Total"]

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        mode_list = self.get_summary(
            "tour_mode_profile",
            lambda: [(label, tm.tour_mode_profile(rd, self.config)) for label, rd in runs],
        )

        charts_by_col = self.get_filtered_view(
            "tour_mode",
            purp,
            factory=lambda: {
                col: [
                    (label, df.filter(pl.col("purpose") == purp).select(["tour_mode", col]))
                    for label, df in mode_list
                    if col in df.columns
                ]
                for col in ["freq_all", "freq_as0", "freq_as1", "freq_as2"]
            },
        )

        def make_chart(col: str, title: str):
            data = charts_by_col[col]
            return bar_chart(data, x_col="tour_mode", y_col=col, title=title, xaxis_title="Mode", as_percent=self.as_percent)

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
                lambda: [(label, tm.grouped_tour_mode_profile(rd, self.config)) for label, rd in runs],
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
        self.purp_sel = pn.widgets.Select(name="Tour Purpose", options=purp_opts, value=purp_opts[0])
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
        first_sf = next((df for _, df in stop_list if len(df) > 0), pl.DataFrame())
        if len(first_sf) > 0 and "primary_purpose" in first_sf.columns:
            return ["Total"] + sorted(first_sf["primary_purpose"].drop_nulls().unique().to_list())
        return ["Total"]

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
            lambda: [(label, stops.stop_purpose_by_tour_purpose(rd)) for label, rd in runs],
        )

        ob_data, ib_data, tot_data, purp_chart_data = self.get_filtered_view(
            "stop_freq",
            purp,
            factory=lambda: (
                [
                    (
                        label,
                        (
                            df if purp == "Total" else df.filter(pl.col("primary_purpose") == purp)
                        )
                        .group_by("ob_stops")
                        .agg(pl.col("freq").sum())
                        .sort("ob_stops")
                        .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
                    )
                    for label, df in stop_list
                ],
                [
                    (
                        label,
                        (
                            df if purp == "Total" else df.filter(pl.col("primary_purpose") == purp)
                        )
                        .group_by("ib_stops")
                        .agg(pl.col("freq").sum())
                        .sort("ib_stops")
                        .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
                    )
                    for label, df in stop_list
                ],
                [
                    (
                        label,
                        (
                            df if purp == "Total" else df.filter(pl.col("primary_purpose") == purp)
                        )
                        .group_by("tot_stops")
                        .agg(pl.col("freq").sum())
                        .sort("tot_stops")
                        .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
                    )
                    for label, df in stop_list
                ],
                [
                    (
                        label,
                        df.group_by("purpose").agg(pl.col("freq").sum())
                        if purp == "Total"
                        else df.filter(pl.col("primary_purpose") == purp),
                    )
                    for label, df in purp_by_tp
                ],
            ),
        )

        self._body.objects = [
            pn.Row(
                bar_chart(ob_data, "stops", "freq", f"Outbound Stops - {purp}", "Stops", as_percent=self.as_percent),
                bar_chart(ib_data, "stops", "freq", f"Inbound Stops - {purp}", "Stops", as_percent=self.as_percent),
                bar_chart(tot_data, "stops", "freq", f"Total Stops - {purp}", "Stops", as_percent=self.as_percent),
            ),
            bar_chart(purp_chart_data, "purpose", "freq", f"Stop Purpose - tour={purp}", "Stop Purpose", as_percent=self.as_percent),
        ]


class StopTimingPage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Stop Timing", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value=purp_opts[0])
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
        first_df = next((df for _, df in timing_list if len(df) > 0), pl.DataFrame())
        if len(first_df) > 0 and "primary_purpose" in first_df.columns:
            return sorted(first_df["primary_purpose"].drop_nulls().unique().to_list())
        return ["work"]

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
        maxbin = 48
        for _, df in timing_list:
            if len(df) > 0 and "timebin" in df.columns:
                maxbin = int(df["timebin"].max())
                break

        def _prep(df: pl.DataFrame, val_col: str) -> pl.DataFrame:
            return (
                df.filter(pl.col("primary_purpose") == purp)
                .select(["timebin", val_col])
                .rename({val_col: "freq"})
                .with_columns(
                    pl.col("timebin").map_elements(
                        lambda tb: stop_timing._time_label(int(tb), maxbin),
                        return_dtype=pl.Utf8,
                    ).alias("clock_time")
                )
            )

        stop_dep, trip_dep = self.get_filtered_view(
            "stop_timing",
            purp,
            factory=lambda: (
                [(label, _prep(df, "freq_stop_dep")) for label, df in timing_list],
                [(label, _prep(df, "freq_trip_dep")) for label, df in timing_list],
            ),
        )
        x_label = "Clock time (start at 03:00)"

        self._body.objects = [
            density_chart(trip_dep, "clock_time", "freq", f"Trip Departure - {purp}", x_label, as_percent=self.as_percent),
            density_chart(stop_dep, "clock_time", "freq", f"Stop Departure - {purp}", x_label, as_percent=self.as_percent),
        ]


class TripModePage(DashboardPage):
    def __init__(self, state: DashboardState, config: Config) -> None:
        super().__init__("Trip Mode", state, config)
        purp_opts, tmode_opts = self._options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(name="Tour Purpose", options=purp_opts, value="Total")
        self.tmode_sel = pn.widgets.Select(name="Tour Mode", options=["All"] + tmode_opts, value="All")
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
            trip_list = [(label, trips.trip_mode_profile(rd, self.config)) for label, rd in runs]
        first_df = next((df for _, df in trip_list if len(df) > 0), pl.DataFrame())
        if len(first_df) > 0:
            purp_opts = (
                sorted(first_df["primary_purpose"].drop_nulls().unique().to_list())
                if "primary_purpose" in first_df.columns
                else ["work"]
            )
            tmode_opts = (
                sorted(first_df["tour_mode"].drop_nulls().unique().to_list())
                if "tour_mode" in first_df.columns
                else []
            )
        else:
            purp_opts = ["work"]
            tmode_opts = []
        return ["Total"] + [p for p in purp_opts if p != "Total"], tmode_opts

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        tmode = self.tmode_sel.value
        trip_list = self.get_summary(
            "trip_mode_profile",
            lambda: [(label, trips.trip_mode_profile(rd, self.config)) for label, rd in runs],
        )

        def apply_filter(df: pl.DataFrame) -> pl.DataFrame:
            if purp != "Total" and "primary_purpose" in df.columns:
                df = df.filter(pl.col("primary_purpose") == purp)
            if tmode != "All" and "tour_mode" in df.columns:
                df = df.filter(pl.col("tour_mode") == tmode)
            return df.group_by("trip_mode").agg(pl.col("freq").sum()).sort("trip_mode")

        filtered_trip_mode = self.get_filtered_view(
            "trip_mode",
            purp,
            tmode,
            factory=lambda: [(label, apply_filter(df)) for label, df in trip_list],
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
