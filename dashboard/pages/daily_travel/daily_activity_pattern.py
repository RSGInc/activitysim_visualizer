"""Daily activity pattern page with person-type distributions and rate charts."""

from __future__ import annotations

import panel as pn

from dashboard.components import bar_chart, selector_row
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
    ordered_category_values,
)
from dashboard.helpers.person_type_helpers import (
    ALL_PERSON_TYPES,
    PERSON_TYPE_COL,
    filter_person_type_counts,
    filter_person_type_rates,
    person_type_selector_options,
    person_type_weights_by_run,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

TOUR_PURPOSE_LABEL_COL = "tour_purpose_label"
PERSON_TYPE_SUMMARY_IDS = (
    "daily_activity_pattern_by_person_type",
    "mandatory_tour_frequency_by_person_type",
    "nonmandatory_tour_frequency_by_person_type",
    "tour_rates_by_person_type_and_tour_purpose",
    "trip_rates_by_person_type_and_trip_purpose",
)


class DailyActivityPatternPage(DashboardPage):
    """Reference page for person-type filtering and weighted total-rate rollups."""

    def build_page(self) -> pn.viewable.Viewable:
        person_type_opts = self._person_type_options("weighted")
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
            selector_row(self.person_type_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _person_type_source_data(self, weighting_key: str):
        """Use the first available person-type summary to seed the selector domain."""
        for summary_id in PERSON_TYPE_SUMMARY_IDS:
            data = self.state.get_summary_table_set(summary_id, weighting_key)
            if data is not None:
                return data
        return None

    def _person_type_options(self, weighting_key: str) -> list[str]:
        """Return display labels plus the page-local raw-value mapping."""
        data = self._person_type_source_data(weighting_key)
        if data is None:
            self._person_type_to_raw = {"All Person Types": ALL_PERSON_TYPES}
            return ["All Person Types"]
        options, self._person_type_to_raw = person_type_selector_options(
            data,
            config=self.config,
            state=self.state,
            cache_key=("daily_activity_pattern", PERSON_TYPE_COL, weighting_key),
        )
        return options or ["All Person Types"]

    def sync_controls(self) -> None:
        options = self._person_type_options(self.weighting_key)
        self.person_type_sel.options = options
        if self.person_type_sel.value not in options:
            self.person_type_sel.value = options[0]

    def _selected_person_type(self) -> tuple[str, str | None]:
        display_value = str(self.person_type_sel.value)
        return display_value, self._person_type_to_raw.get(display_value)

    def _optional_summaries(self):
        """Load each chart's summary independently so partial pages still render."""
        return self.optional_summaries_dict(*self.required_summary_ids)

    def _missing_chart_card(self, summary_id: str) -> pn.Card:
        return self.data_not_available_card(
            detail="This chart requires a precomputed summary table.",
            missing_items=[summary_id],
        )

    def _count_chart(
        self,
        summary_data,
        *,
        cache_key: str,
        raw_person_type: str | None,
        category_col: str,
        category_id: str | None,
        source_col_for_labels: str | None = None,
        target_col_for_labels: str | None = None,
    ):
        """Build one count-style chart dataset after person-type filtering and completion."""
        category_values = ordered_category_values(
            summary_data,
            category_col,
            category_id=category_id,
            config=self.config,
        )
        chart_data = self.get_filtered_view(
            cache_key,
            raw_person_type,
            factory=lambda: complete_category_counts(
                filter_person_type_counts(summary_data, raw_person_type),
                category_col=category_col,
                category_values=category_values,
                value_cols=("person_count", "pct"),
            ),
        )
        if source_col_for_labels is None or category_id is None:
            return chart_data, category_values, category_values

        labeled_data = label_category_data(
            chart_data,
            source_col=source_col_for_labels,
            category_id=category_id,
            config=self.config,
            target_col=target_col_for_labels,
        )
        label_values = self.config.ordered_labels(category_id, category_values)
        return labeled_data, category_values, label_values

    def _rate_chart(
        self,
        summary_data,
        *,
        cache_key: str,
        raw_person_type: str | None,
        category_col: str,
        category_id: str,
        rate_col: str,
        target_col: str,
        person_weights,
    ):
        """Build one rate chart dataset, including weighted total-person-type rollups."""
        category_values = ordered_category_values(
            summary_data,
            category_col,
            category_id=category_id,
            config=self.config,
        )
        chart_data = self.get_filtered_view(
            cache_key,
            raw_person_type,
            factory=lambda: label_category_data(
                complete_category_counts(
                    filter_person_type_rates(
                        summary_data,
                        raw_person_type,
                        purpose_col=category_col,
                        rate_col=rate_col,
                        person_weights=person_weights,
                    ),
                    category_col=category_col,
                    category_values=category_values,
                    value_cols=(rate_col,),
                ),
                category_id=category_id,
                config=self.config,
                source_col=category_col,
                target_col=target_col,
            ),
        )
        return chart_data, self.config.ordered_labels(category_id, category_values)

    def render_daily_activity_pattern_chart(
        self,
        summaries,
        *,
        display_person_type,
        raw_person_type,
    ):
        summary_data = summaries["daily_activity_pattern_by_person_type"]
        if summary_data is None:
            return self._missing_chart_card("daily_activity_pattern_by_person_type")
        chart_data, _, label_values = self._count_chart(
            summary_data,
            cache_key="daily_activity_pattern",
            raw_person_type=raw_person_type,
            category_col="daily_activity_pattern",
            category_id="daily_activity_pattern",
            source_col_for_labels="daily_activity_pattern",
            target_col_for_labels="daily_activity_pattern_label",
        )
        return bar_chart(
            chart_data,
            x_col="daily_activity_pattern_label",
            y_col="person_count",
            title=f"Daily Activity Pattern - {display_person_type}",
            xaxis_title="Daily Activity Pattern",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=label_values,
        )

    def render_mandatory_tour_frequency_chart(
        self,
        summaries,
        *,
        display_person_type,
        raw_person_type,
    ):
        summary_data = summaries["mandatory_tour_frequency_by_person_type"]
        if summary_data is None:
            return self._missing_chart_card("mandatory_tour_frequency_by_person_type")
        chart_data, _, label_values = self._count_chart(
            summary_data,
            cache_key="mandatory_tour_frequency",
            raw_person_type=raw_person_type,
            category_col="mandatory_tour_frequency",
            category_id="mandatory_tour_frequency",
            source_col_for_labels="mandatory_tour_frequency",
            target_col_for_labels="mandatory_tour_frequency_label",
        )
        return bar_chart(
            chart_data,
            x_col="mandatory_tour_frequency_label",
            y_col="person_count",
            title=f"Mandatory Tour Frequency - {display_person_type}",
            xaxis_title="Mandatory Tour Frequency",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=label_values,
        )

    def render_nonmandatory_tour_frequency_chart(
        self,
        summaries,
        *,
        display_person_type,
        raw_person_type,
    ):
        summary_data = summaries["nonmandatory_tour_frequency_by_person_type"]
        if summary_data is None:
            return self._missing_chart_card("nonmandatory_tour_frequency_by_person_type")
        chart_data, x_values, _ = self._count_chart(
            summary_data,
            cache_key="nonmandatory_tour_frequency",
            raw_person_type=raw_person_type,
            category_col="nonmandatory_tour_frequency",
            category_id=None,
        )
        return bar_chart(
            chart_data,
            x_col="nonmandatory_tour_frequency",
            y_col="person_count",
            title=f"Non-Mandatory Tour Frequency - {display_person_type}",
            xaxis_title="Non-Mandatory Tour Frequency",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=x_values,
        )

    def render_tour_rate_chart(
        self,
        summaries,
        *,
        display_person_type,
        raw_person_type,
        person_weights,
    ):
        summary_data = summaries["tour_rates_by_person_type_and_tour_purpose"]
        if summary_data is None:
            return self._missing_chart_card("tour_rates_by_person_type_and_tour_purpose")
        chart_data, label_values = self._rate_chart(
            summary_data,
            cache_key="tour_rate_per_person",
            raw_person_type=raw_person_type,
            category_col="tour_purpose",
            category_id="tour_purpose",
            rate_col="tour_rate",
            target_col=TOUR_PURPOSE_LABEL_COL,
            person_weights=person_weights,
        )
        return bar_chart(
            chart_data,
            x_col=TOUR_PURPOSE_LABEL_COL,
            y_col="tour_rate",
            title=f"Daily Tour Rate per Person by Tour Purpose - {display_person_type}",
            xaxis_title="Tour Purpose",
            yaxis_title="Tours per Person-Day",
            as_percent=False,
            xaxis_categoryarray=label_values,
        )

    def render_trip_rate_chart(
        self,
        summaries,
        *,
        display_person_type,
        raw_person_type,
        person_weights,
    ):
        summary_data = summaries["trip_rates_by_person_type_and_trip_purpose"]
        if summary_data is None:
            return self._missing_chart_card("trip_rates_by_person_type_and_trip_purpose")
        chart_data, label_values = self._rate_chart(
            summary_data,
            cache_key="trip_rate_per_person",
            raw_person_type=raw_person_type,
            category_col="trip_purpose",
            category_id="trip_purpose",
            rate_col="trip_rate",
            target_col="trip_purpose",
            person_weights=person_weights,
        )
        return bar_chart(
            chart_data,
            x_col="trip_purpose",
            y_col="trip_rate",
            title=f"Daily Trip Rate per Person by Trip Purpose - {display_person_type}",
            xaxis_title="Trip Purpose",
            yaxis_title="Trips per Person-Day",
            as_percent=False,
            xaxis_categoryarray=label_values,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._optional_summaries()
        if not any(data is not None for data in summaries.values()):
            return [self.summary_only_unavailable_card()]

        display_person_type, raw_person_type = self._selected_person_type()
        # The total-rate view uses the daily activity pattern summary's person counts as weights
        # so that "Total" reflects the modeled person mix instead of a simple mean of types.
        person_weights = person_type_weights_by_run(
            summaries["daily_activity_pattern_by_person_type"] or []
        )
        return [
                self.render_daily_activity_pattern_chart(
                    summaries,
                    display_person_type=display_person_type,
                    raw_person_type=raw_person_type,
            ),
            pn.Row(
                self.render_mandatory_tour_frequency_chart(
                    summaries,
                    display_person_type=display_person_type,
                    raw_person_type=raw_person_type,
                ),
                self.render_nonmandatory_tour_frequency_chart(
                    summaries,
                    display_person_type=display_person_type,
                    raw_person_type=raw_person_type,
                ),
            ),
            pn.Row(
                self.render_tour_rate_chart(
                    summaries,
                    display_person_type=display_person_type,
                    raw_person_type=raw_person_type,
                    person_weights=person_weights,
                ),
                self.render_trip_rate_chart(
                    summaries,
                    display_person_type=display_person_type,
                    raw_person_type=raw_person_type,
                    person_weights=person_weights,
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
