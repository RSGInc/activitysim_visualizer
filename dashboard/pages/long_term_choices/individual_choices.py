"""Individual choices page: license, bike comfort, transit pass, transit subsidy."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _cast_category(
    data_list: list[tuple[str, pl.DataFrame]],
    category_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, df.with_columns(pl.col(category_col).cast(pl.Utf8)))
        for label, df in _nonempty(data_list)
    ]


class IndividualChoicesPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Individual Choices", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Individual Choices"),
            self._body,
            sizing_mode="stretch_width",
        )

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

        license_list = _cast_category(
            summaries["license_holding_status_distribution"],
            "person_type_label",
        )
        bike_list = _cast_category(
            summaries["bicycle_comfort_level_distribution"],
            "bicycle_comfort_level",
        )
        pass_list = _cast_category(
            summaries["transit_pass_ownership_by_person_type"],
            "person_type_label",
        )
        subsidy_list = _cast_category(
            summaries["transit_subsidy_by_person_type"],
            "person_type_label",
        )

        license_chart = bar_chart(
            license_list,
            x_col="person_type_label",
            y_col="person_count",
            title="License Holding Status",
            xaxis_title="Person Type",
            yaxis_title="Persons Age 16+",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        bike_chart = bar_chart(
            bike_list,
            x_col="bicycle_comfort_level",
            y_col="person_count",
            title="Bicycle Comfort Level",
            xaxis_title="Bicycle Comfort Level",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        pass_chart = bar_chart(
            pass_list,
            x_col="person_type_label",
            y_col="person_count",
            title="Transit Pass Ownership",
            xaxis_title="Person Type",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        subsidy_chart = bar_chart(
            subsidy_list,
            x_col="person_type_label",
            y_col="person_count",
            title="Transit Subsidy",
            xaxis_title="Person Type",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            pn.Row(license_chart, bike_chart, sizing_mode="stretch_width"),
            pn.Row(pass_chart, subsidy_chart, sizing_mode="stretch_width"),
        ]


PAGE = DashboardPageDefinition(
    page_id="individual_choices",
    title="Individual Choices",
    group_id="long_term_choices",
    child_id="individual_choices",
    order=25,
    controller_cls=IndividualChoicesPage,
    required_summary_ids=(
        "license_holding_status_distribution",
        "bicycle_comfort_level_distribution",
        "transit_pass_ownership_by_person_type",
        "transit_subsidy_by_person_type",
    ),
)

IndividualChoicesPage.definition = PAGE
