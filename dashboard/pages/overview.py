"""Overview page: KPI boxes, person type distribution, HH size distribution."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import (
    to_pandas,
    drop_index_columns,
    format_numeric_frame,
)
from dashboard.rendering.tables import column_title_metadata
from dashboard.helpers.comparison_helpers import (
    build_base_run_percent_difference_table,
)
from dashboard.helpers.category_helpers import cap_numeric_category_data
from dashboard import DashboardPage, dashboard_page
from dashboard.page_base import SectionContent

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
    base_label, base_df = totals_list[0]
    _, base_vmt_df = vmt_list[0]
    row_values: dict[str, dict[str, float | None]] = {}
    for metric, label in KPI_METRICS:
        source_list = vmt_list if metric == "auto_vmt" else totals_list
        source_base = base_vmt_df if metric == "auto_vmt" else base_df
        row_values[label] = {
            run_label: metric_value(source_df, metric)
            for run_label, source_df in source_list
        }
        row_values[label][base_label] = metric_value(source_base, metric)
    return build_base_run_percent_difference_table(
        run_labels=[run_label for run_label, _ in totals_list],
        base_run_label=base_label,
        row_header="Metric",
        row_values=row_values,
    )


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
    """Cap household size labels at 5+ for chart display."""
    return cap_numeric_category_data(
        hhsize_list,
        category="household_size",
        cap_value=5,
        value_cols=("household_count",),
    )


@dashboard_page(
    page_id="overview",
    title="Overview",
    order=10,
    required_summary_ids=(
        "population_totals",
        "person_type_distribution",
        "household_size_distribution",
        "auto_vmt_totals",
    ),
)
class OverviewPage(DashboardPage):
    """Render top-line KPIs plus two demographic distributions."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the overview page from separate KPI and demographic sections."""
        self._kpi_section = self.section("overview_kpis", render=self.render_kpis)
        self._demographics_section = self.section(
            "overview_demographics",
            render=self.render_demographics,
        )
        return self.new_section(
            pn.pane.Markdown("## Overview"),
            pn.pane.Markdown("### Key Performance Indicators"),
            self._kpi_section,
            pn.pane.Markdown("### Demographic Distributions"),
            self._demographics_section,
        )

    def _kpi_result(self):
        """Resolve the summary inputs required for the KPI cards and comparison table."""
        return self.data.summaries(
            "population_totals",
            "auto_vmt_totals",
            columns={
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

    def _demographic_results(self):
        """Resolve the two demographic charts independently for better fallbacks."""
        return (
            self.data.summary(
                "person_type_distribution",
                columns=("person_type_label", "person_count"),
            ),
            self.data.summary(
                "household_size_distribution",
                columns=(
                    "household_size",
                    "household_count",
                ),
            ),
        )

    def _kpi_card(
        self,
        totals_list: list[tuple[str, pl.DataFrame]],
        *,
        metric: str,
        label: str,
    ) -> pn.viewable.Viewable:
        """Render one KPI card from the run-indexed totals table."""
        return self.plot.kpi(
            label=label,
            values=[
                (run_label, metric_value(tot_df, metric))
                for run_label, tot_df in totals_list
            ],
        )

    def render_percent_difference_table(
        self,
        pct_df: pl.DataFrame,
    ) -> pn.viewable.Viewable:
        """Render the KPI percent-difference table when comparison rows exist."""
        if len(pct_df) == 0:
            return pn.pane.Markdown("")
        display_df = format_numeric_frame(
            drop_index_columns(pct_df),
            numeric_precision=2,
        )
        titles, header_tooltips = column_title_metadata(display_df.columns)
        return pn.widgets.Tabulator(
            to_pandas(display_df),
            sizing_mode="stretch_width",
            height=260,
            titles=titles,
            header_tooltips=header_tooltips,
            show_index=False,
        )

    def render_person_type_chart(self, ptype_result) -> pn.viewable.Viewable:
        """Render the person type distribution chart when its summary is available."""
        return (
            self.plot.bar(
                person_type_chart_data(ptype_result),
                x="person_type_label",
                y="person_count",
                title="Person Type Distribution",
                x_title="Person Type",
                y_title="Persons",
            )
            if ptype_result
            else self.data_not_available_card(
                detail="Person type distribution is unavailable.",
                missing_items=["person_type_distribution"],
            )
        )

    def render_household_size_chart(self, hhsize_result) -> pn.viewable.Viewable:
        """Render the household size distribution chart when its summary is available."""
        return (
            self.plot.bar(
                hh_size_chart_data(hhsize_result),
                x="household_size",
                y="household_count",
                title="Household Size Distribution",
                x_title="Household Size",
                y_title="Households",
            )
            if hhsize_result
            else self.data_not_available_card(
                detail="Household size distribution is unavailable.",
                missing_items=["household_size_distribution"],
            )
        )

    def render_kpis(self) -> SectionContent:
        """Render KPI cards plus the base-run percent difference table."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        objects: list[pn.viewable.Viewable] = []
        kpi_result = self._kpi_result()
        if all(kpi_result.values()):
            totals_list = kpi_result["population_totals"]
            vmt_list = kpi_result["auto_vmt_totals"]
            pct_df = self.query(lambda: percent_difference_table(totals_list, vmt_list))
            vmt_box = self.plot.kpi(
                label="VMT",
                values=[
                    (run_label, metric_value(tot_df, "auto_vmt"))
                    for run_label, tot_df in vmt_list
                ],
            )
            kpi_cards = pn.Column(
                pn.Row(
                    self._kpi_card(
                        totals_list,
                        metric="person_count",
                        label="Population",
                    ),
                    self._kpi_card(
                        totals_list,
                        metric="household_count",
                        label="Households",
                    ),
                    vmt_box,
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    self._kpi_card(
                        totals_list,
                        metric="tour_count",
                        label="Tours",
                    ),
                    self._kpi_card(
                        totals_list,
                        metric="trip_count",
                        label="Trips",
                    ),
                    self._kpi_card(
                        totals_list,
                        metric="stop_count",
                        label="Stops",
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            )
            objects.extend(
                [
                    self.noted_view("overview.kpis", kpi_cards),
                    pn.pane.Markdown("### Percent Difference vs Base Run"),
                    self.noted_view(
                        "overview.percent_difference",
                        self.render_percent_difference_table(pct_df),
                    ),
                ]
            )
        else:
            objects.append(
                self.data_not_available_card(
                    detail="Overview KPIs require the population totals and auto VMT summary tables.",
                    missing_items=[
                        key for key, value in kpi_result.items() if not value
                    ],
                )
            )
        return objects

    def render_demographics(self) -> SectionContent:
        """Render the demographic distribution charts."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        ptype_result, hhsize_result = self._demographic_results()
        return [
            pn.Row(
                self.noted_view(
                    "overview.person_type",
                    self.render_person_type_chart(ptype_result),
                ),
                self.noted_view(
                    "overview.household_size",
                    self.render_household_size_chart(hhsize_result),
                ),
            ),
        ]
