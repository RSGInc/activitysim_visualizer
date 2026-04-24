"""Daily activity pattern page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


PERSON_TYPE_COL = "person_type_label"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def person_type_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or PERSON_TYPE_COL not in first_df.columns:
        return ["Total"]

    vals = (
        first_df.select(PERSON_TYPE_COL)
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return ["Total"] + sorted(v for v in vals if v != "Total")


def filter_person_type(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        if PERSON_TYPE_COL in df.columns and person_type != "Total":
            df = df.with_columns(pl.col(PERSON_TYPE_COL).cast(pl.Utf8)).filter(
                pl.col(PERSON_TYPE_COL) == person_type
            )
        out.append((label, df))
    return out


class DailyActivityPatternPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Daily Activity Pattern", state, config)

        person_type_opts = self._person_type_options()
        self.person_type_sel = pn.widgets.Select(
            name="Person Type",
            options=person_type_opts,
            value=person_type_opts[0],
        )
        self._watch_widget(self.person_type_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
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
        return person_type_options(data)

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        opts = person_type_options(summaries["daily_activity_pattern_by_person_type"])
        self.person_type_sel.options = opts
        if self.person_type_sel.value not in opts:
            self.person_type_sel.value = opts[0]
        person_type = self.person_type_sel.value

        dap_data = self.get_filtered_view(
            "daily_activity_pattern",
            person_type,
            factory=lambda: filter_person_type(
                summaries["daily_activity_pattern_by_person_type"], person_type
            ),
        )

        mand_tour_freq_data = self.get_filtered_view(
            "mandatory_tour_frequency",
            person_type,
            factory=lambda: filter_person_type(
                summaries["mandatory_tour_frequency_by_person_type"], person_type
            ),
        )

        nonmand_tour_freq_data = self.get_filtered_view(
            "nonmandatory_tour_frequency",
            person_type,
            factory=lambda: filter_person_type(
                summaries["nonmandatory_tour_frequency_by_person_type"], person_type
            ),
        )

        tour_rate_data = self.get_filtered_view(
            "tour_rate_per_person",
            person_type,
            factory=lambda: filter_person_type(
                summaries["tour_rates_by_person_type_and_tour_purpose"], person_type
            ),
        )

        trip_rate_data = self.get_filtered_view(
            "trip_rate_per_person",
            person_type,
            factory=lambda: filter_person_type(
                summaries["trip_rates_by_person_type_and_trip_purpose"], person_type
            ),
        )

        dap_chart = bar_chart(
            dap_data,
            x_col="daily_activity_pattern",
            y_col="person_count",
            title=f"Daily Activity Pattern - {person_type}",
            xaxis_title="Daily Activity Pattern",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        mand_tour_freq_chart = bar_chart(
            mand_tour_freq_data,
            x_col="mandatory_tour_frequency",
            y_col="person_count",
            title="Mandatory Tour Frequency",
            xaxis_title="Mandatory Tour Frequency",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        nonmand_tour_freq_chart = bar_chart(
            nonmand_tour_freq_data,
            x_col="nonmandatory_tour_frequency",
            y_col="person_count",
            title="Non-Mandatory Tour Frequency",
            xaxis_title="Non-Mandatory Tour Frequency",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        tour_rate_chart = bar_chart(
            tour_rate_data,
            x_col="tour_purpose",
            y_col="tour_rate",
            title="Daily Tour Rate per Person by Tour Purpose",
            xaxis_title="Tour Purpose",
            yaxis_title="Tours per Person-Day",
            as_percent=False,
        )

        trip_rate_chart = bar_chart(
            trip_rate_data,
            x_col="trip_purpose",
            y_col="trip_rate",
            title="Daily Trip Rate per Person by Trip Purpose",
            xaxis_title="Trip Purpose",
            yaxis_title="Trips per Person-Day",
            as_percent=False,
        )

        self._body.objects = [
            dap_chart,
            pn.Row(mand_tour_freq_chart, nonmand_tour_freq_chart),
            pn.Row(tour_rate_chart, trip_rate_chart),
        ]


PAGE = DashboardPageDefinition(
    page_id="daily_activity_pattern",
    title="Daily Activity Pattern",
    order=28,
    controller_cls=DailyActivityPatternPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="person_type",
            widget_attr="person_type_sel",
            label="Person Type",
        ),
    ),
    required_summary_ids=(
        "daily_activity_pattern_by_person_type",
        "mandatory_tour_frequency_by_person_type",
        "nonmandatory_tour_frequency_by_person_type",
        "tour_rates_by_person_type_and_tour_purpose",
        "trip_rates_by_person_type_and_trip_purpose",
    ),
)

DailyActivityPatternPage.definition = PAGE
