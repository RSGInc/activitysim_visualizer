"""Individual choices page: license, bike comfort, transit pass, transit subsidy."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, selector_row
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
    normalize_category_strings,
    ordered_category_values,
)
from dashboard.helpers.person_type_helpers import (
    ALL_PERSON_TYPES,
    PERSON_TYPE_COL,
    filter_person_type_counts,
    person_type_selector_options,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

_BICYCLE_COMFORT_DISPLAY = {
    "1": "Strong and Fearless",
    "2": "Enthused and Confident",
    "3": "Interested but Concerned",
    "4": "No Way No How",
    "StrongAndFearless": "Strong and Fearless",
    "EnthusedAndConfident": "Enthused and Confident",
    "InterestedButConcerned": "Interested but Concerned",
    "NoWayNoHow": "No Way No How",
    "Unspecified": "Unspecified",
}


def normalize_bicycle_comfort_levels(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Map legacy bicycle comfort codes to the dashboard's readable category labels."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in normalize_category_strings(data_list, "bicycle_comfort_level"):
        out.append(
            (
                label,
                df.with_columns(
                    pl.col("bicycle_comfort_level")
                    .replace(
                        _BICYCLE_COMFORT_DISPLAY,
                        default=pl.col("bicycle_comfort_level"),
                    )
                    .alias("bicycle_comfort_level")
                ),
            )
        )
    return out


class IndividualChoicesPage(DashboardPage):
    """Person-type page for four long-term choice distributions."""

    def build_page(self) -> pn.viewable.Viewable:
        person_type_opts = self._person_type_options()
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
            "individual_choices_body",
            selectors=("person_type",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Individual Choices"),
            selector_row(self.person_type_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _summary_names(self) -> tuple[str, ...]:
        return (
            "license_holding_status_distribution",
            "bicycle_comfort_level_distribution",
            "transit_pass_ownership_by_person_type",
            "transit_subsidy_by_person_type",
        )

    def _person_type_options(self) -> list[str]:
        """Build one person-type selector across every summary used on the page."""
        summary_lists = [
            self.state.get_summary_table_set(summary_name, self.weighting_key)
            for summary_name in self._summary_names()
        ]
        options, self._person_type_to_raw = person_type_selector_options(
            *summary_lists,
            config=self.config,
            state=self.state,
            cache_key=("individual_choices", PERSON_TYPE_COL, self.weighting_key),
        )
        return options or ["Total"]

    def sync_controls(self) -> None:
        options = self._person_type_options()
        self.person_type_sel.options = options
        if self.person_type_sel.value not in options:
            self.person_type_sel.value = options[0]

    def _selected_person_type(self) -> tuple[str, str | None]:
        display_value = str(self.person_type_sel.value)
        raw_value = self._person_type_to_raw.get(display_value, ALL_PERSON_TYPES)
        return display_value, raw_value

    def _summary_or_placeholder(
        self,
        summary_name: str,
        *,
        detail: str,
    ) -> list[tuple[str, pl.DataFrame]] | pn.Card:
        summary = self.optional_summary(summary_name)
        if summary is not None:
            return summary
        return self.data_not_available_card(detail=detail, missing_items=[summary_name])

    def _count_chart_data(
        self,
        summary_data: list[tuple[str, pl.DataFrame]],
        *,
        cache_key: str,
        raw_person_type: str | None,
        category_col: str,
        category_id: str | None = None,
        source_col_for_labels: str | None = None,
        target_col_for_labels: str | None = None,
    ):
        """Filter one summary to the selected person type and complete missing categories."""
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

    def render_license_chart(self, display_person_type: str, raw_person_type: str | None):
        """Render license holding status for the selected person type."""
        summary = self._summary_or_placeholder(
            "license_holding_status_distribution",
            detail="The license holding summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        normalized_summary = normalize_category_strings(summary, "license_holding_status")
        chart_data, _, label_values = self._count_chart_data(
            normalized_summary,
            cache_key="license_holding_status_distribution",
            raw_person_type=raw_person_type,
            category_col="license_holding_status",
            category_id="license_holding_status",
            source_col_for_labels="license_holding_status",
            target_col_for_labels="license_holding_status_label",
        )
        return bar_chart(
            chart_data,
            x_col="license_holding_status_label",
            y_col="person_count",
            title=f"License Holding Status Among Persons Aged 16+ - {display_person_type}",
            xaxis_title="License Status",
            yaxis_title="Persons Age 16+",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=label_values,
        )

    def render_bike_chart(self, display_person_type: str, raw_person_type: str | None):
        """Render normalized bicycle comfort levels for the selected person type."""
        summary = self._summary_or_placeholder(
            "bicycle_comfort_level_distribution",
            detail="The bicycle comfort summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        normalized_summary = normalize_bicycle_comfort_levels(summary)
        chart_data, x_values, _ = self._count_chart_data(
            normalized_summary,
            cache_key="bicycle_comfort_level_distribution",
            raw_person_type=raw_person_type,
            category_col="bicycle_comfort_level",
        )
        return bar_chart(
            chart_data,
            x_col="bicycle_comfort_level",
            y_col="person_count",
            title=f"Bicycle Comfort Level - {display_person_type}",
            xaxis_title="Bicycle Comfort Level",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=x_values,
        )

    def render_pass_chart(self, display_person_type: str, raw_person_type: str | None):
        """Render transit pass ownership for the selected person type."""
        summary = self._summary_or_placeholder(
            "transit_pass_ownership_by_person_type",
            detail="The transit pass ownership summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        normalized_summary = normalize_category_strings(
            summary, "transit_pass_ownership_status"
        )
        chart_data, _, label_values = self._count_chart_data(
            normalized_summary,
            cache_key="transit_pass_ownership_by_person_type",
            raw_person_type=raw_person_type,
            category_col="transit_pass_ownership_status",
            category_id="transit_pass_ownership_status",
            source_col_for_labels="transit_pass_ownership_status",
            target_col_for_labels="transit_pass_ownership_status_label",
        )
        return bar_chart(
            chart_data,
            x_col="transit_pass_ownership_status_label",
            y_col="person_count",
            title=f"Transit Pass Ownership - {display_person_type}",
            xaxis_title="Transit Pass Ownership Status",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=label_values,
        )

    def render_subsidy_chart(self, display_person_type: str, raw_person_type: str | None):
        """Render transit subsidy categories, handling both raw and pre-labeled summaries."""
        summary = self._summary_or_placeholder(
            "transit_subsidy_by_person_type",
            detail="The transit subsidy summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        subsidy_category_col = (
            "transit_subsidy_label"
            if any("transit_subsidy_label" in df.columns for _, df in summary)
            else "transit_subsidy_status"
        )
        normalized_summary = normalize_category_strings(summary, subsidy_category_col)
        raw_subsidy_values = ordered_category_values(
            summary
            if any("transit_subsidy_status" in df.columns for _, df in summary)
            else normalized_summary,
            "transit_subsidy_status"
            if any("transit_subsidy_status" in df.columns for _, df in summary)
            else subsidy_category_col,
            category_id="transit_subsidy",
            config=self.config,
        )
        display_values = (
            [self.config.label_value("transit_subsidy", value) for value in raw_subsidy_values]
            if subsidy_category_col == "transit_subsidy_label"
            else raw_subsidy_values
        )

        # Some summary variants already contain dashboard-ready labels, while others still need
        # config-driven relabeling from a raw status code.
        chart_data = self.get_filtered_view(
            "transit_subsidy_by_person_type",
            raw_person_type,
            factory=lambda: (
                label_category_data(
                    complete_category_counts(
                        filter_person_type_counts(normalized_summary, raw_person_type),
                        category_col=subsidy_category_col,
                        category_values=raw_subsidy_values,
                        value_cols=("person_count", "pct"),
                    ),
                    source_col=subsidy_category_col,
                    category_id="transit_subsidy",
                    config=self.config,
                    target_col="transit_subsidy_display",
                )
                if subsidy_category_col == "transit_subsidy_status"
                else complete_category_counts(
                    filter_person_type_counts(normalized_summary, raw_person_type),
                    category_col=subsidy_category_col,
                    category_values=display_values,
                    value_cols=("person_count", "pct"),
                )
            ),
        )
        return bar_chart(
            chart_data,
            x_col=(
                "transit_subsidy_display"
                if subsidy_category_col == "transit_subsidy_status"
                else subsidy_category_col
            ),
            y_col="person_count",
            title=(
                "Transit Subsidy Type Among Workers - "
                f"{'All Workers' if raw_person_type == ALL_PERSON_TYPES else display_person_type}"
            ),
            xaxis_title="Transit Subsidy Status",
            yaxis_title=(
                "All Workers"
                if raw_person_type == ALL_PERSON_TYPES
                else f"{display_person_type}"
            ),
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=(
                self.config.ordered_labels("transit_subsidy", raw_subsidy_values)
                if subsidy_category_col == "transit_subsidy_status"
                else display_values
            ),
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]

        display_person_type, raw_person_type = self._selected_person_type()
        return [
            pn.Row(
                self.render_license_chart(display_person_type, raw_person_type),
                self.render_bike_chart(display_person_type, raw_person_type),
                sizing_mode="stretch_width",
            ),
            pn.Row(
                self.render_pass_chart(display_person_type, raw_person_type),
                self.render_subsidy_chart(display_person_type, raw_person_type),
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="individual_choices",
    title="Individual Choices",
    group_id="long_term_choices",
    order=25,
    page_cls=IndividualChoicesPage,
    required_summary_ids=(
        "license_holding_status_distribution",
        "bicycle_comfort_level_distribution",
        "transit_pass_ownership_by_person_type",
        "transit_subsidy_by_person_type",
    ),
)

IndividualChoicesPage.definition = PAGE
