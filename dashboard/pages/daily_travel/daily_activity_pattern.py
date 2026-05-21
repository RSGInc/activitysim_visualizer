"""Daily activity pattern page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.helpers.category_helpers import (
    column_options,
    complete_category_counts,
    nonempty,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

PERSON_TYPE_COL = "person_type"
TOUR_PURPOSE_LABEL_COL = "tour_purpose_label"
PERSON_TYPE_SUMMARY_IDS = (
    "daily_activity_pattern_by_person_type",
    "mandatory_tour_frequency_by_person_type",
    "nonmandatory_tour_frequency_by_person_type",
    "tour_rates_by_person_type_and_tour_purpose",
    "trip_rates_by_person_type_and_trip_purpose",
)


def _person_type_filter(df: pl.DataFrame, person_type: str | None) -> pl.DataFrame:
    person_type_col = pl.col(PERSON_TYPE_COL).cast(pl.Utf8)
    if person_type is None:
        return df.filter(~person_type_col.is_in(["all_person_types", "Total"]))
    return df.filter(person_type_col == person_type)


def filter_person_type_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in nonempty(data_list):
        if PERSON_TYPE_COL not in df.columns:
            out.append((label, df))
            continue
        out.append((label, _person_type_filter(df, person_type)))
    return out


def _person_weights_by_run(
    dap_data_list: list[tuple[str, pl.DataFrame]],
) -> dict[str, pl.DataFrame]:
    weights: dict[str, pl.DataFrame] = {}
    for label, df in nonempty(dap_data_list):
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
    for label, df in nonempty(data_list):
        if PERSON_TYPE_COL not in df.columns:
            out.append((label, df))
            continue
        d = df.with_columns(pl.col(PERSON_TYPE_COL).cast(pl.Utf8))
        if person_type not in {None, "all_person_types", "Total"}:
            out.append((label, d.filter(pl.col(PERSON_TYPE_COL) == person_type)))
            continue

        existing_total = d.filter(pl.col(PERSON_TYPE_COL) == "all_person_types")
        if len(existing_total) > 0:
            out.append((label, existing_total.drop(PERSON_TYPE_COL)))
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


def label_tour_purpose_rates(
    data_list: list[tuple[str, pl.DataFrame]],
    config,
    *,
    source_col: str = "tour_purpose",
    target_col: str = TOUR_PURPOSE_LABEL_COL,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in nonempty(data_list):
        if source_col not in df.columns:
            out.append((label, df))
            continue
        out.append(
            (
                label,
                df.with_columns(
                    pl.col(source_col)
                    .cast(pl.Utf8)
                    .map_elements(
                        lambda value: config.label_value("tour_purpose", value),
                        return_dtype=pl.Utf8,
                    )
                    .alias(target_col)
                ),
            )
        )
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
        data = self._person_type_source_data("weighted")
        if data is None:
            return ["Total"]
        opts, self._person_type_to_raw = column_options(
            data,
            PERSON_TYPE_COL,
            category_id="person_type",
            config=self.config,
            state=self.state,
            cache_key=(
                "daily_activity_pattern",
                "daily_activity_pattern_by_person_type",
                PERSON_TYPE_COL,
                "weighted",
            ),
            total_raw="all_person_types",
            total_label="Total",
        )
        return opts or ["Total"]

    def _person_type_source_data(
        self,
        weighting_key: str,
    ) -> list[tuple[str, pl.DataFrame]] | None:
        for summary_id in PERSON_TYPE_SUMMARY_IDS:
            data = self.state.get_summary_table_set(summary_id, weighting_key)
            if data is not None:
                return data
        return None

    def _missing_chart_card(self, summary_id: str) -> pn.Card:
        return self.data_not_available_card(
            detail="This chart requires a precomputed summary table.",
            missing_items=[summary_id],
        )

    def sync_controls(self) -> None:
        data = self._person_type_source_data(self.weighting_key)
        if data is None:
            self.person_type_sel.options = ["Total"]
            self.person_type_sel.value = "Total"
            return
        display_opts, self._person_type_to_raw = column_options(
            data,
            PERSON_TYPE_COL,
            category_id="person_type",
            config=self.config,
            state=self.state,
            cache_key=(
                "daily_activity_pattern",
                "daily_activity_pattern_by_person_type",
                PERSON_TYPE_COL,
                self.weighting_key,
            ),
            total_raw="all_person_types",
            total_label="Total",
        )
        self.person_type_sel.options = display_opts
        if self.person_type_sel.value not in display_opts:
            self.person_type_sel.value = display_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summaries = {
            summary_id: self.optional_summary(summary_id)
            for summary_id in self.required_summary_ids
        }
        if not any(data is not None for data in summaries.values()):
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]

        person_type = self.person_type_sel.value
        raw_person_type = self._person_type_to_raw.get(person_type)
        person_weights = _person_weights_by_run(
            summaries["daily_activity_pattern_by_person_type"] or []
        )
        content: list[pn.viewable.Viewable] = []

        if summaries["daily_activity_pattern_by_person_type"] is None:
            content.append(
                self._missing_chart_card("daily_activity_pattern_by_person_type")
            )
        else:
            dap_x_values = ordered_category_values(
                summaries["daily_activity_pattern_by_person_type"],
                "daily_activity_pattern",
                category_id="daily_activity_pattern",
                config=self.config,
            )
            dap_data = self.get_filtered_view(
                "daily_activity_pattern",
                raw_person_type,
                factory=lambda: complete_category_counts(
                    filter_person_type_counts(
                        summaries["daily_activity_pattern_by_person_type"],
                        raw_person_type,
                    ),
                    category_col="daily_activity_pattern",
                    category_values=dap_x_values,
                    value_cols=("person_count", "pct"),
                ),
            )
            content.append(
                bar_chart(
                    dap_data,
                    x_col="daily_activity_pattern",
                    y_col="person_count",
                    title=f"Daily Activity Pattern - {person_type}",
                    xaxis_title="Daily Activity Pattern",
                    yaxis_title="Persons",
                    pct_col="pct",
                    as_percent=self.as_percent,
                    xaxis_categoryarray=dap_x_values,
                )
            )

        mandatory_view: pn.viewable.Viewable
        if summaries["mandatory_tour_frequency_by_person_type"] is None:
            mandatory_view = self._missing_chart_card(
                "mandatory_tour_frequency_by_person_type"
            )
        else:
            mandatory_x_values = ordered_category_values(
                summaries["mandatory_tour_frequency_by_person_type"],
                "mandatory_tour_frequency",
                category_id="mandatory_tour_frequency",
                config=self.config,
            )
            mand_tour_freq_data = self.get_filtered_view(
                "mandatory_tour_frequency",
                raw_person_type,
                factory=lambda: complete_category_counts(
                    filter_person_type_counts(
                        summaries["mandatory_tour_frequency_by_person_type"],
                        raw_person_type,
                    ),
                    category_col="mandatory_tour_frequency",
                    category_values=mandatory_x_values,
                    value_cols=("person_count", "pct"),
                ),
            )
            mandatory_view = bar_chart(
                mand_tour_freq_data,
                x_col="mandatory_tour_frequency",
                y_col="person_count",
                title=f"Mandatory Tour Frequency - {person_type}",
                xaxis_title="Mandatory Tour Frequency",
                yaxis_title="Persons",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=mandatory_x_values,
            )

        nonmandatory_view: pn.viewable.Viewable
        if summaries["nonmandatory_tour_frequency_by_person_type"] is None:
            nonmandatory_view = self._missing_chart_card(
                "nonmandatory_tour_frequency_by_person_type"
            )
        else:
            nonmandatory_x_values = ordered_category_values(
                summaries["nonmandatory_tour_frequency_by_person_type"],
                "nonmandatory_tour_frequency",
            )
            nonmand_tour_freq_data = self.get_filtered_view(
                "nonmandatory_tour_frequency",
                raw_person_type,
                factory=lambda: complete_category_counts(
                    filter_person_type_counts(
                        summaries["nonmandatory_tour_frequency_by_person_type"],
                        raw_person_type,
                    ),
                    category_col="nonmandatory_tour_frequency",
                    category_values=nonmandatory_x_values,
                    value_cols=("person_count", "pct"),
                ),
            )
            nonmandatory_view = bar_chart(
                nonmand_tour_freq_data,
                x_col="nonmandatory_tour_frequency",
                y_col="person_count",
                title=f"Non-Mandatory Tour Frequency - {person_type}",
                xaxis_title="Non-Mandatory Tour Frequency",
                yaxis_title="Persons",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=nonmandatory_x_values,
            )
        content.append(pn.Row(mandatory_view, nonmandatory_view))

        tour_rate_view: pn.viewable.Viewable
        if summaries["tour_rates_by_person_type_and_tour_purpose"] is None:
            tour_rate_view = self._missing_chart_card(
                "tour_rates_by_person_type_and_tour_purpose"
            )
        else:
            tour_purpose_x_values = ordered_category_values(
                summaries["tour_rates_by_person_type_and_tour_purpose"],
                "tour_purpose",
                category_id="tour_purpose",
                config=self.config,
            )
            tour_purpose_label_values = self.config.ordered_labels(
                "tour_purpose",
                tour_purpose_x_values,
            )
            tour_rate_data = self.get_filtered_view(
                "tour_rate_per_person",
                raw_person_type,
                factory=lambda: label_tour_purpose_rates(
                    complete_category_counts(
                        filter_person_type_rates(
                            summaries["tour_rates_by_person_type_and_tour_purpose"],
                            raw_person_type,
                            purpose_col="tour_purpose",
                            rate_col="tour_rate",
                            person_weights=person_weights,
                        ),
                        category_col="tour_purpose",
                        category_values=tour_purpose_x_values,
                        value_cols=("tour_rate",),
                    ),
                    self.config,
                ),
            )
            tour_rate_view = bar_chart(
                tour_rate_data,
                x_col=TOUR_PURPOSE_LABEL_COL,
                y_col="tour_rate",
                title=f"Daily Tour Rate per Person by Tour Purpose - {person_type}",
                xaxis_title="Tour Purpose",
                yaxis_title="Tours per Person-Day",
                as_percent=False,
                xaxis_categoryarray=tour_purpose_label_values,
            )

        trip_rate_view: pn.viewable.Viewable
        if summaries["trip_rates_by_person_type_and_trip_purpose"] is None:
            trip_rate_view = self._missing_chart_card(
                "trip_rates_by_person_type_and_trip_purpose"
            )
        else:
            trip_purpose_x_values = ordered_category_values(
                summaries["trip_rates_by_person_type_and_trip_purpose"],
                "trip_purpose",
            )
            trip_rate_data = self.get_filtered_view(
                "trip_rate_per_person",
                raw_person_type,
                factory=lambda: complete_category_counts(
                    filter_person_type_rates(
                        summaries["trip_rates_by_person_type_and_trip_purpose"],
                        raw_person_type,
                        purpose_col="trip_purpose",
                        rate_col="trip_rate",
                        person_weights=person_weights,
                    ),
                    category_col="trip_purpose",
                    category_values=trip_purpose_x_values,
                    value_cols=("trip_rate",),
                ),
            )
            trip_rate_view = bar_chart(
                trip_rate_data,
                x_col="trip_purpose",
                y_col="trip_rate",
                title=f"Daily Trip Rate per Person by Trip Purpose - {person_type}",
                xaxis_title="Trip Purpose",
                yaxis_title="Trips per Person-Day",
                as_percent=False,
                xaxis_categoryarray=trip_purpose_x_values,
            )
        content.append(pn.Row(tour_rate_view, trip_rate_view))

        return content


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
