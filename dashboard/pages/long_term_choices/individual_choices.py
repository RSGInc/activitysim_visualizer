"""Individual choices page: license, bike comfort, transit pass, transit subsidy."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config

PERSON_TYPE_COL = "person_type"
ALL_PERSON_TYPES = "all_person_types"


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


def person_type_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    person_types = set()
    for _, df in _nonempty(data_list):
        if PERSON_TYPE_COL not in df.columns:
            continue
        person_types.update(
            df.select(PERSON_TYPE_COL).drop_nulls().to_series().cast(pl.Utf8).to_list()
        )
    return sorted(str(person_type) for person_type in person_types) or [
        ALL_PERSON_TYPES
    ]


def person_type_maps(
    person_type_opts: list[str],
    config: Config,
) -> tuple[list[str], dict[str, str | None]]:
    label_to_person_type: dict[str, str | None] = {}
    if ALL_PERSON_TYPES in person_type_opts:
        label_to_person_type["Total"] = ALL_PERSON_TYPES
    else:
        label_to_person_type["Total"] = None
    for person_type in person_type_opts:
        if person_type in {ALL_PERSON_TYPES, "Total"}:
            continue
        label_to_person_type[config.person_type_label(person_type)] = person_type
    return list(label_to_person_type), label_to_person_type


def _filter_person_type(df: pl.DataFrame, person_type: str | None) -> pl.DataFrame:
    person_type_col = pl.col(PERSON_TYPE_COL).cast(pl.Utf8)
    if person_type is None:
        return df.filter(~person_type_col.is_in([ALL_PERSON_TYPES, "Total"]))
    return df.filter(person_type_col == person_type)


def filter_person_type_counts(
    data_list: list[tuple[str, pl.DataFrame]],
    person_type: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if PERSON_TYPE_COL not in df.columns:
            out.append((label, df))
            continue
        out.append((label, _filter_person_type(df, person_type)))
    return out


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
        self._selector_to_summary = {
            "license_person_type": "license_holding_status_distribution",
            "bike_person_type": "bicycle_comfort_level_distribution",
            "pass_person_type": "transit_pass_ownership_by_person_type",
            "subsidy_person_type": "transit_subsidy_by_person_type",
        }
        self._selector_maps: dict[str, dict[str, str | None]] = {}

        self.license_person_type_sel = self._build_person_type_selector(
            "license_person_type"
        )
        self.bike_person_type_sel = self._build_person_type_selector("bike_person_type")
        self.pass_person_type_sel = self._build_person_type_selector("pass_person_type")
        self.subsidy_person_type_sel = self._build_person_type_selector(
            "subsidy_person_type"
        )

        self._license_section = self.section(
            "license_chart",
            selectors=("license_person_type",),
            render=self.render_license_chart,
        )
        self._bike_section = self.section(
            "bike_chart",
            selectors=("bike_person_type",),
            render=self.render_bike_chart,
        )
        self._pass_section = self.section(
            "pass_chart",
            selectors=("pass_person_type",),
            render=self.render_pass_chart,
        )
        self._subsidy_section = self.section(
            "subsidy_chart",
            selectors=("subsidy_person_type",),
            render=self.render_subsidy_chart,
        )

        return self.new_section(
            pn.pane.Markdown("## Individual Choices"),
            pn.Row(
                self._chart_card(self.license_person_type_sel, self._license_section),
                self._chart_card(self.bike_person_type_sel, self._bike_section),
                sizing_mode="stretch_width",
            ),
            pn.Row(
                self._chart_card(self.pass_person_type_sel, self._pass_section),
                self._chart_card(self.subsidy_person_type_sel, self._subsidy_section),
                sizing_mode="stretch_width",
            ),
        )

    def _build_person_type_selector(self, selector_id: str) -> pn.widgets.Select:
        options = self._person_type_options(self._selector_to_summary[selector_id])
        self._selector_maps[selector_id] = {"Total": ALL_PERSON_TYPES}
        return self.selector(
            selector_id,
            widget=pn.widgets.Select(
                name="Person Type",
                options=options,
                value=options[0],
            ),
            label="Person Type",
        )

    def _chart_card(
        self,
        selector: pn.widgets.Select,
        chart_section: pn.Column,
    ) -> pn.Column:
        return pn.Column(
            pn.Row(
                pn.pane.Markdown("**Person Type:**"),
                selector,
                sizing_mode="stretch_width",
            ),
            chart_section,
            sizing_mode="stretch_width",
        )

    def _person_type_options(self, summary_name: str) -> list[str]:
        data = self.state.get_summary_table_set(summary_name, self.weighting_key)
        if data is None:
            return ["Total"]
        raw_opts = person_type_options(data)
        opts, _ = person_type_maps(raw_opts, self.config)
        return opts or ["Total"]

    def sync_controls(self) -> None:
        for selector_id, summary_name in self._selector_to_summary.items():
            data = self.optional_summary(summary_name)
            if data is None:
                continue
            raw_opts = person_type_options(data)
            display_opts, mapping = person_type_maps(raw_opts, self.config)
            selector = self._registered_selectors[selector_id].widget
            self._selector_maps[selector_id] = mapping
            selector.options = display_opts
            if selector.value not in display_opts:
                selector.value = display_opts[0]

    def _selector_person_type(self, selector_id: str) -> tuple[str, str | None]:
        selector = self._registered_selectors[selector_id].widget
        display_value = str(selector.value)
        raw_value = self._selector_maps.get(selector_id, {}).get(
            display_value, ALL_PERSON_TYPES
        )
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

    def render_license_chart(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summary = self._summary_or_placeholder(
            "license_holding_status_distribution",
            detail="The license holding summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return [summary]

        display_person_type, raw_person_type = self._selector_person_type(
            "license_person_type"
        )
        license_list = self.get_filtered_view(
            "license_holding_status_distribution",
            raw_person_type,
            factory=lambda: _cast_category(
                filter_person_type_counts(summary, raw_person_type),
                "license_holding_status",
            ),
        )
        return [
            bar_chart(
                license_list,
                x_col="license_holding_status",
                y_col="person_count",
                title=f"License Holding Status - {display_person_type}",
                xaxis_title="License Status",
                yaxis_title="Persons Age 16+",
                pct_col="pct",
                as_percent=self.as_percent,
            )
        ]

    def render_bike_chart(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summary = self._summary_or_placeholder(
            "bicycle_comfort_level_distribution",
            detail="The bicycle comfort summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return [summary]

        display_person_type, raw_person_type = self._selector_person_type(
            "bike_person_type"
        )
        bike_list = self.get_filtered_view(
            "bicycle_comfort_level_distribution",
            raw_person_type,
            factory=lambda: _normalize_bicycle_comfort_levels(
                filter_person_type_counts(summary, raw_person_type)
            ),
        )
        return [
            bar_chart(
                bike_list,
                x_col="bicycle_comfort_level",
                y_col="person_count",
                title=f"Bicycle Comfort Level - {display_person_type}",
                xaxis_title="Bicycle Comfort Level",
                yaxis_title="Persons",
                pct_col="pct",
                as_percent=self.as_percent,
            )
        ]

    def render_pass_chart(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summary = self._summary_or_placeholder(
            "transit_pass_ownership_by_person_type",
            detail="The transit pass ownership summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return [summary]

        display_person_type, raw_person_type = self._selector_person_type(
            "pass_person_type"
        )
        pass_list = self.get_filtered_view(
            "transit_pass_ownership_by_person_type",
            raw_person_type,
            factory=lambda: _cast_category(
                filter_person_type_counts(summary, raw_person_type),
                "transit_pass_ownership_status",
            ),
        )
        return [
            bar_chart(
                pass_list,
                x_col="transit_pass_ownership_status",
                y_col="person_count",
                title=f"Transit Pass Ownership - {display_person_type}",
                xaxis_title="Transit Pass Ownership Status",
                yaxis_title="Persons",
                pct_col="pct",
                as_percent=self.as_percent,
            )
        ]

    def render_subsidy_chart(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summary = self._summary_or_placeholder(
            "transit_subsidy_by_person_type",
            detail="The transit subsidy summary is unavailable.",
        )
        if isinstance(summary, pn.Card):
            return [summary]

        display_person_type, raw_person_type = self._selector_person_type(
            "subsidy_person_type"
        )
        subsidy_list = self.get_filtered_view(
            "transit_subsidy_by_person_type",
            raw_person_type,
            factory=lambda: _cast_category(
                filter_person_type_counts(summary, raw_person_type),
                "transit_subsidy_status",
            ),
        )
        return [
            bar_chart(
                subsidy_list,
                x_col="transit_subsidy_status",
                y_col="person_count",
                title=f"Transit Subsidy - {display_person_type}",
                xaxis_title="Transit Subsidy Status",
                yaxis_title=(
                    "Workers and Students"
                    if display_person_type == "Total"
                    else f"{display_person_type}"
                ),
                pct_col="pct",
                as_percent=self.as_percent,
            )
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
