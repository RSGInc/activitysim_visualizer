"""Long-term choices page: auto ownership, TLFD, telecommute, WFH, geography flows."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


def auto_ownership_chart_data(
    auto_own_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Cast HH vehicle ownership values for chart display."""
    return [
        (label, df.with_columns(pl.col("household_vehicle_count").cast(pl.Utf8)))
        for label, df in auto_own_list
    ]


def wfh_chart_data(
    wfh_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Select WFH chart columns for non-empty summaries."""
    return [
        (
            label,
            df.select(
                pl.col("geography"),
                pl.col("work_from_home_worker_count"),
            ),
        )
        for label, df in wfh_list
        if df is not None and len(df) > 0
    ]


def geo_options(work_tlfd_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect geography selector options from work TLFD data."""
    first_tlfd = work_tlfd_list[0][1] if work_tlfd_list else None
    if first_tlfd is None or len(first_tlfd) == 0:
        return ["Total"]
    geos = first_tlfd.select("geography").drop_nulls().unique().to_series().to_list()

    return ["Total"] + sorted(g for g in geos if g != "all_geographies")


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
    """Build TLFD datasets for one geography selection from long-form summaries."""
    geography = "all_geographies" if geo == "Total" else geo
    work_data = [
        (
            label,
            df.filter(pl.col("geography") == geography)
            .select(
                pl.col("distance_bin"),
                pl.col("person_count"),
            )
            .sort("distance_bin"),
        )
        for label, df in work_tlfd_list
        if df is not None and len(df) > 0
    ]
    univ_data = [
        (
            label,
            df.filter(pl.col("geography") == geography)
            .select(
                pl.col("distance_bin"),
                pl.col("person_count"),
            )
            .sort("distance_bin"),
        )
        for label, df in univ_tlfd_list
        if df is not None and len(df) > 0
    ]
    schl_data = [
        (
            label,
            df.filter(pl.col("geography") == geography)
            .select(
                pl.col("distance_bin"),
                pl.col("person_count"),
            )
            .sort("distance_bin"),
        )
        for label, df in schl_tlfd_list
        if df is not None and len(df) > 0
    ]
    return work_data, univ_data, schl_data


def avg_mand_tour_len_table_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Convert long mandatory tour length summaries into pivoted table format."""
    out = []

    for label, df in data_list:
        if df is None or len(df) == 0:
            continue

        table_df = df.with_columns(
            pl.when(pl.col("geography") == "all_geographies")
            .then(pl.lit("Total"))
            .otherwise(pl.col("geography"))
            .alias("geography")
        ).pivot(
            values="average_tour_distance",
            index="geography",
            on="mandatory_tour_purpose",
        )

        # Keep geography first, then purpose columns sorted
        cols = table_df.columns
        purpose_cols = sorted(c for c in cols if c != "geography")
        table_df = table_df.select(["geography", *purpose_cols])

        out.append((label, table_df))

    return out


class LongTermPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Long-Term", state, config)
        self.geo_sel: pn.widgets.Select | None = None
        if config.geography_enabled:
            geo_groups = self._geo_options()
            self.geo_sel = pn.widgets.Select(
                name="Geography", options=geo_groups, value=geo_groups[0]
            )
            self._watch_widget(self.geo_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        header = [pn.pane.Markdown("## Long-Term Choices")]
        if self.geo_sel is not None:
            header.append(pn.Row(pn.pane.Markdown("**Geography:**"), self.geo_sel))
        self.view = pn.Column(*header, self._body, sizing_mode="stretch_width")

    def _geo_options(self) -> list[str]:
        tlfd_result = self.state.inspect_summary_table(
            "work_location_distance_distribution_by_geography",
            weighting_key="weighted",
            required_columns=("distance_bin", "geography", "person_count"),
        )
        if not tlfd_result.has_usable_runs:
            return ["Total"]
        return geo_options([(label, table) for label, table in tlfd_result.usable_runs])

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summary_result = self.resolve_summary_visualization(
            "long_term_core",
            summary_requirements={
                "auto_ownership_distribution": (
                    "household_vehicle_count",
                    "household_count",
                ),
                "work_location_distance_distribution_by_geography": (
                    "distance_bin",
                    "geography",
                    "person_count",
                ),
                "university_location_distance_distribution_by_geography": (
                    "distance_bin",
                    "geography",
                    "person_count",
                ),
                "school_location_distance_distribution_by_geography": (
                    "distance_bin",
                    "geography",
                    "person_count",
                ),
                "work_from_home_rate_by_geography": (
                    "geography",
                    "worker_count",
                    "work_from_home_worker_count",
                ),
                "telecommute_frequency_distribution": (
                    "telecommute_frequency",
                    "person_count",
                ),
                "average_mandatory_tour_distance_by_purpose_and_geography": (
                    "mandatory_tour_purpose",
                    "geography",
                    "average_tour_distance",
                ),
            },
        )
        if not summary_result.has_usable_runs:
            self._body.objects = [
                self.unavailable_visualization(
                    summary_result,
                    detail="Long-term summary tables are unavailable.",
                )
            ]
            return

        auto_own_list = auto_ownership_chart_data(
            summary_result.usable_by_input["auto_ownership_distribution"]
        )
        work_tlfd_list = summary_result.usable_by_input[
            "work_location_distance_distribution_by_geography"
        ]
        univ_tlfd_list = summary_result.usable_by_input[
            "university_location_distance_distribution_by_geography"
        ]
        schl_tlfd_list = summary_result.usable_by_input[
            "school_location_distance_distribution_by_geography"
        ]
        wfh_list = summary_result.usable_by_input["work_from_home_rate_by_geography"]
        tc_list = summary_result.usable_by_input[
            "telecommute_frequency_distribution"
        ]
        mand_len_list = summary_result.usable_by_input[
            "average_mandatory_tour_distance_by_purpose_and_geography"
        ]
        auto_chart = bar_chart(
            auto_own_list,
            x_col="household_vehicle_count",
            y_col="household_count",
            title="Auto Ownership",
            xaxis_title="Vehicles",
            yaxis_title="Households",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        tc_chart = bar_chart(
            tc_list,
            x_col="telecommute_frequency",
            y_col="person_count",
            title="Telecommute Frequency",
            xaxis_title="Frequency",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )
        wfh_chart = bar_chart(
            wfh_chart_data(wfh_list),
            x_col="geography",
            y_col="work_from_home_worker_count",
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
                tuple(label for label, _ in work_tlfd_list),
                factory=lambda: tlfd_chart_data(
                    work_tlfd_list, univ_tlfd_list, schl_tlfd_list, geo
                ),
            )
            tlfd_section = pn.Column(
                pn.pane.Markdown("### TLFD by geography:"),
                pn.Row(
                    density_chart(
                        work_data,
                        "distance_bin",
                        "person_count",
                        "Work TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        univ_data,
                        "distance_bin",
                        "person_count",
                        "University TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        schl_data,
                        "distance_bin",
                        "person_count",
                        "School TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                ),
            )
            flow_result = self.resolve_summary_visualization(
                "long_term_geo_flows",
                summary_requirements={
                    "geo_flows": ("Home Geography", "Work Geography", "Workers")
                },
            )
            flow_widget = (
                data_table(
                    [
                        (label, df)
                        for label, df in flow_result.usable_by_input["geo_flows"]
                        if df is not None and len(df) > 0
                    ],
                    "Home-Work Geography Flows",
                )
                if flow_result.has_usable_runs
                else self.unavailable_visualization(
                    flow_result,
                    detail=(
                        "This page requires the geography flow summary when geography is enabled."
                    ),
                )
            )
        else:
            work_data, univ_data, schl_data = self.get_filtered_view(
                "long_term_tlfd",
                "Total",
                tuple(label for label, _ in work_tlfd_list),
                factory=lambda: tlfd_chart_data(
                    work_tlfd_list, univ_tlfd_list, schl_tlfd_list, "Total"
                ),
            )
            tlfd_section = pn.Column(
                pn.pane.Markdown("### Trip Length Frequency Distributions (TLFD)"),
                pn.Row(
                    density_chart(
                        work_data,
                        "distance_bin",
                        "person_count",
                        "Work TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        univ_data,
                        "distance_bin",
                        "person_count",
                        "University TLFD",
                        "Distance (miles)",
                        normalize=False,
                        as_percent=self.as_percent,
                    ),
                    density_chart(
                        schl_data,
                        "distance_bin",
                        "person_count",
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
            data_table(
                avg_mand_tour_len_table_data(mand_len_list),
                "Average Mandatory Tour Lengths (miles)",
            ),
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
    export_regions=(
        PageExportRegionDefinition(
            region_id="long_term_body",
            view_attr="_body",
            selector_ids=("geography",),
        ),
    ),
    required_summary_ids=(
        "auto_ownership_distribution",
        "work_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        "work_from_home_rate_by_geography",
        "telecommute_frequency_distribution",
        "average_mandatory_tour_distance_by_purpose_and_geography",
    ),
)

LongTermPage.definition = PAGE
