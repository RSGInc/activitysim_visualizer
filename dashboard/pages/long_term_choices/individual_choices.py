"""Individual choices page: license, bike comfort, transit pass, transit subsidy."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import (
    category_order,
    complete_category_counts,
    nonempty_runs,
)
from dashboard.pages._shared.person_types import (
    filter_person_type_runs,
    person_type_display_mapping,
    person_type_options,
)

PERSON_TYPE_COL = "person_type"
ALL_PERSON_TYPES = "all_person_types"


def _cast_category(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (
            label,
            df.with_columns(
                pl.when(pl.col(category_col).cast(pl.Utf8).str.strip_chars() == "")
                .then(pl.lit("Unspecified"))
                .otherwise(pl.col(category_col).cast(pl.Utf8))
                .alias(category_col)
            ),
        )
        for label, df in nonempty_runs(data_list)
    ]


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


def _normalize_bicycle_comfort_levels(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _cast_category(data_list, "bicycle_comfort_level"):
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
    def build_page(self) -> pn.viewable.Viewable:
        person_type_opts = self._person_type_options()
        self._person_type_to_raw = {"Total": ALL_PERSON_TYPES}
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
            pn.Row(
                pn.pane.Markdown("**Person Type:**"),
                self.person_type_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def _person_type_options(self) -> list[str]:
        summary_names = (
            "license_holding_status_distribution",
            "bicycle_comfort_level_distribution",
            "transit_pass_ownership_by_person_type",
            "transit_subsidy_by_person_type",
        )
        raw_opts: set[str] = set()
        for summary_name in summary_names:
            data = self.state.get_summary_table_set(summary_name, self.weighting_key)
            if data is None:
                continue
            raw_opts.update(person_type_options(data))
        if not raw_opts:
            return ["Total"]
        opts, self._person_type_to_raw = person_type_display_mapping(
            sorted(raw_opts),
            self.config,
            all_value=ALL_PERSON_TYPES,
        )
        return opts or ["Total"]

    def sync_controls(self) -> None:
        display_opts = self._person_type_options()
        self.person_type_sel.options = display_opts
        if self.person_type_sel.value not in display_opts:
            self.person_type_sel.value = display_opts[0]

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
        return self.data_not_available_card(
            detail=detail,
            missing_items=[summary_name],
        )

    def render_license_chart(
        self,
        display_person_type: str,
        raw_person_type: str | None,
    ):
        summary = self._summary_or_placeholder(
            "license_holding_status_distribution",
            detail="The license holding summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        normalized_summary = _cast_category(summary, "license_holding_status")
        x_values = category_order(normalized_summary, "license_holding_status")
        license_list = self.get_filtered_view(
            "license_holding_status_distribution",
            raw_person_type,
            factory=lambda: complete_category_counts(
                filter_person_type_runs(
                    normalized_summary,
                    raw_person_type,
                    all_values=(ALL_PERSON_TYPES, "Total"),
                ),
                category_col="license_holding_status",
                category_values=x_values,
            ),
        )
        return bar_chart(
            license_list,
            x_col="license_holding_status",
            y_col="person_count",
            title=f"License Holding Status - {display_person_type}",
            xaxis_title="License Status",
            yaxis_title="Persons Age 16+",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=x_values,
        )

    def render_bike_chart(
        self,
        display_person_type: str,
        raw_person_type: str | None,
    ):
        summary = self._summary_or_placeholder(
            "bicycle_comfort_level_distribution",
            detail="The bicycle comfort summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        normalized_summary = _normalize_bicycle_comfort_levels(summary)
        x_values = category_order(normalized_summary, "bicycle_comfort_level")
        bike_list = self.get_filtered_view(
            "bicycle_comfort_level_distribution",
            raw_person_type,
            factory=lambda: complete_category_counts(
                filter_person_type_runs(
                    normalized_summary,
                    raw_person_type,
                    all_values=(ALL_PERSON_TYPES, "Total"),
                ),
                category_col="bicycle_comfort_level",
                category_values=x_values,
            ),
        )
        return bar_chart(
            bike_list,
            x_col="bicycle_comfort_level",
            y_col="person_count",
            title=f"Bicycle Comfort Level - {display_person_type}",
            xaxis_title="Bicycle Comfort Level",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=x_values,
        )

    def render_pass_chart(
        self,
        display_person_type: str,
        raw_person_type: str | None,
    ):
        summary = self._summary_or_placeholder(
            "transit_pass_ownership_by_person_type",
            detail="The transit pass ownership summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return summary

        normalized_summary = _cast_category(summary, "transit_pass_ownership_status")
        x_values = category_order(normalized_summary, "transit_pass_ownership_status")
        pass_list = self.get_filtered_view(
            "transit_pass_ownership_by_person_type",
            raw_person_type,
            factory=lambda: complete_category_counts(
                filter_person_type_runs(
                    normalized_summary,
                    raw_person_type,
                    all_values=(ALL_PERSON_TYPES, "Total"),
                ),
                category_col="transit_pass_ownership_status",
                category_values=x_values,
            ),
        )
        return bar_chart(
            pass_list,
            x_col="transit_pass_ownership_status",
            y_col="person_count",
            title=f"Transit Pass Ownership - {display_person_type}",
            xaxis_title="Transit Pass Ownership Status",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=x_values,
        )

    def render_subsidy_chart(
        self,
        display_person_type: str,
        raw_person_type: str | None,
    ):
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
        normalized_summary = _cast_category(summary, subsidy_category_col)
        x_values = category_order(normalized_summary, subsidy_category_col)
        subsidy_list = self.get_filtered_view(
            "transit_subsidy_by_person_type",
            raw_person_type,
            factory=lambda: complete_category_counts(
                filter_person_type_runs(
                    normalized_summary,
                    raw_person_type,
                    all_values=(ALL_PERSON_TYPES, "Total"),
                ),
                category_col=subsidy_category_col,
                category_values=x_values,
            ),
        )
        return bar_chart(
            subsidy_list,
            x_col=subsidy_category_col,
            y_col="person_count",
            title=f"Transit Subsidy - {display_person_type}",
            xaxis_title="Transit Subsidy Status",
            yaxis_title=(
                "All Workers"
                if display_person_type == "Total"
                else f"{display_person_type}"
            ),
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=x_values,
        )

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

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
