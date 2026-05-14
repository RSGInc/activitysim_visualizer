"""Daily activity pattern page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import nonempty_runs
from dashboard.pages._shared.person_types import (
    filter_person_type_runs,
    person_type_display_mapping,
    person_type_options,
)

PERSON_TYPE_COL = "person_type"


def _person_weights_by_run(
    dap_data_list: list[tuple[str, pl.DataFrame]],
) -> dict[str, pl.DataFrame]:
    weights: dict[str, pl.DataFrame] = {}
    for label, df in nonempty_runs(dap_data_list):
        if PERSON_TYPE_COL not in df.columns or "person_count" not in df.columns:
            continue
        weights[label] = (
            df.with_columns(pl.col(PERSON_TYPE_COL).cast(pl.Utf8))
            .filter(~pl.col(PERSON_TYPE_COL).is_in(["all_person_types", "Total"]))
            .group_by(PERSON_TYPE_COL)
            .agg(person_count=pl.col("person_count").sum())
        )
    return weights


def filter_person_type_rates(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str | None,
    *,
    purpose_col: str,
    rate_col: str,
    person_weights: dict[str, pl.DataFrame],
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in nonempty_runs(data_list):
        if PERSON_TYPE_COL not in df.columns:
            out.append((label, df))
            continue
        d = df.with_columns(pl.col(PERSON_TYPE_COL).cast(pl.Utf8))
        if person_type not in {None, "all_person_types", "Total"}:
            out.append((label, d.filter(pl.col(PERSON_TYPE_COL) == person_type)))
            continue

        weights = person_weights.get(label)
        if weights is None or len(weights) == 0:
            aggregated = (
                d.filter(~pl.col(PERSON_TYPE_COL).is_in(["all_person_types", "Total"]))
                .group_by(purpose_col)
                .agg(pl.col(rate_col).mean().alias(rate_col))
                .sort(purpose_col)
            )
            out.append((label, aggregated))
            continue

        total_person_count = float(weights["person_count"].sum())
        aggregated = (
            d.filter(~pl.col(PERSON_TYPE_COL).is_in(["all_person_types", "Total"]))
            .join(weights, on=PERSON_TYPE_COL, how="left")
            .with_columns(
                pl.col("person_count").fill_null(0.0),
                (pl.col(rate_col) * pl.col("person_count")).alias("_weighted_rate"),
            )
            .group_by(purpose_col)
            .agg(
                pl.col("_weighted_rate").sum().alias("_weighted_rate_sum"),
            )
            .with_columns(
                pl.when(pl.lit(total_person_count) > 0)
                .then(pl.col("_weighted_rate_sum") / pl.lit(total_person_count))
                .otherwise(None)
                .alias(rate_col)
            )
            .select(purpose_col, rate_col)
            .sort(purpose_col)
        )
        out.append((label, aggregated))
    return out


class DailyActivityPatternPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        person_type_opts = self._person_type_options()
        self._person_type_to_raw = {"Total": "all_person_types"}
        self.person_type_sel = self.selector(
            "person_type",
            widget=pn.widgets.Select(
                name="Person Type",
                options=person_type_opts,
                value=person_type_opts[0],
            ),
            label="Person Type",
        )
        self._body = self.section(
            "activity_pattern_body",
            selectors=("person_type",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Daily Activity Pattern"),
            pn.Row(
                pn.pane.Markdown("**Person Type:**"),
                self.person_type_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def _person_type_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "daily_activity_pattern_by_person_type", "weighted"
        )
        if data is None:
            return ["Total"]
        raw_opts = person_type_options(data)
        opts, self._person_type_to_raw = person_type_display_mapping(
            raw_opts, self.config
        )
        return opts or ["Total"]

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        raw_opts = person_type_options(
            summaries["daily_activity_pattern_by_person_type"]
        )
        display_opts, self._person_type_to_raw = person_type_display_mapping(
            raw_opts, self.config
        )
        self.person_type_sel.options = display_opts
        if self.person_type_sel.value not in display_opts:
            self.person_type_sel.value = display_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]

        person_type = self.person_type_sel.value
        raw_person_type = self._person_type_to_raw.get(person_type)
        person_weights = _person_weights_by_run(
            summaries["daily_activity_pattern_by_person_type"]
        )

        dap_data = self.get_filtered_view(
            "daily_activity_pattern",
            raw_person_type,
            factory=lambda: filter_person_type_runs(
                summaries["daily_activity_pattern_by_person_type"], raw_person_type
            ),
        )
        mand_tour_freq_data = self.get_filtered_view(
            "mandatory_tour_frequency",
            raw_person_type,
            factory=lambda: filter_person_type_runs(
                summaries["mandatory_tour_frequency_by_person_type"], raw_person_type
            ),
        )
        nonmand_tour_freq_data = self.get_filtered_view(
            "nonmandatory_tour_frequency",
            raw_person_type,
            factory=lambda: filter_person_type_runs(
                summaries["nonmandatory_tour_frequency_by_person_type"],
                raw_person_type,
            ),
        )
        tour_rate_data = self.get_filtered_view(
            "tour_rate_per_person",
            raw_person_type,
            factory=lambda: filter_person_type_rates(
                summaries["tour_rates_by_person_type_and_tour_purpose"],
                raw_person_type,
                purpose_col="tour_purpose",
                rate_col="tour_rate",
                person_weights=person_weights,
            ),
        )
        trip_rate_data = self.get_filtered_view(
            "trip_rate_per_person",
            raw_person_type,
            factory=lambda: filter_person_type_rates(
                summaries["trip_rates_by_person_type_and_trip_purpose"],
                raw_person_type,
                purpose_col="trip_purpose",
                rate_col="trip_rate",
                person_weights=person_weights,
            ),
        )

        return [
            bar_chart(
                dap_data,
                x_col="daily_activity_pattern",
                y_col="person_count",
                title=f"Daily Activity Pattern - {person_type}",
                xaxis_title="Daily Activity Pattern",
                yaxis_title="Persons",
                pct_col="pct",
                as_percent=self.as_percent,
            ),
            pn.Row(
                bar_chart(
                    mand_tour_freq_data,
                    x_col="mandatory_tour_frequency",
                    y_col="person_count",
                    title=f"Mandatory Tour Frequency - {person_type}",
                    xaxis_title="Mandatory Tour Frequency",
                    yaxis_title="Persons",
                    pct_col="pct",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    nonmand_tour_freq_data,
                    x_col="nonmandatory_tour_frequency",
                    y_col="person_count",
                    title=f"Non-Mandatory Tour Frequency - {person_type}",
                    xaxis_title="Non-Mandatory Tour Frequency",
                    yaxis_title="Persons",
                    pct_col="pct",
                    as_percent=self.as_percent,
                ),
            ),
            pn.Row(
                bar_chart(
                    tour_rate_data,
                    x_col="tour_purpose",
                    y_col="tour_rate",
                    title=f"Daily Tour Rate per Person by Tour Purpose - {person_type}",
                    xaxis_title="Tour Purpose",
                    yaxis_title="Tours per Person-Day",
                    as_percent=False,
                ),
                bar_chart(
                    trip_rate_data,
                    x_col="trip_purpose",
                    y_col="trip_rate",
                    title=f"Daily Trip Rate per Person by Trip Purpose - {person_type}",
                    xaxis_title="Trip Purpose",
                    yaxis_title="Trips per Person-Day",
                    as_percent=False,
                ),
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="daily_activity_pattern",
    title="Daily Activity Pattern",
    group_id="daily_travel",
    order=28,
    page_cls=DailyActivityPatternPage,
    required_summary_ids=(
        "daily_activity_pattern_by_person_type",
        "mandatory_tour_frequency_by_person_type",
        "nonmandatory_tour_frequency_by_person_type",
        "tour_rates_by_person_type_and_tour_purpose",
        "trip_rates_by_person_type_and_trip_purpose",
    ),
)

DailyActivityPatternPage.definition = PAGE
