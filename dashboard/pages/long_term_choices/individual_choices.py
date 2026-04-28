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
        (
            label,
            df.with_columns(
                pl.when(pl.col(category_col).cast(pl.Utf8).str.strip_chars() == "")
                .then(pl.lit("Unspecified"))
                .otherwise(pl.col(category_col).cast(pl.Utf8))
                .alias(category_col)
            ),
        )
        for label, df in _nonempty(data_list)
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
                    .replace(_BICYCLE_COMFORT_DISPLAY, default=pl.col("bicycle_comfort_level"))
                    .alias("bicycle_comfort_level")
                ),
            )
        )
    return out


def _filter_all_person_types(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if "person_type" in df.columns:
            df = df.with_columns(pl.col("person_type").cast(pl.Utf8)).filter(
                pl.col("person_type") == "all_person_types"
            )
        out.append((label, df))
    return out


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
            _filter_all_person_types(
                summaries["license_holding_status_distribution"]
            ),
            "license_holding_status",
        )
        bike_list = _normalize_bicycle_comfort_levels(
            _filter_all_person_types(
                summaries["bicycle_comfort_level_distribution"]
            )
        )
        pass_list = _cast_category(
            _filter_all_person_types(
                summaries["transit_pass_ownership_by_person_type"]
            ),
            "transit_pass_ownership_status",
        )
        subsidy_list = _cast_category(
            _filter_all_person_types(
                summaries["transit_subsidy_by_person_type"]
            ),
            "transit_subsidy_status",
        )

        license_chart = bar_chart(
            license_list,
            x_col="license_holding_status",
            y_col="person_count",
            title="License Holding Status",
            xaxis_title="License Status",
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
            x_col="transit_pass_ownership_status",
            y_col="person_count",
            title="Transit Pass Ownership",
            xaxis_title="Transit Pass Ownership Status",
            yaxis_title="Persons",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        subsidy_chart = bar_chart(
            subsidy_list,
            x_col="transit_subsidy_status",
            y_col="person_count",
            title="Transit Subsidy",
            xaxis_title="Transit Subsidy Status",
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
