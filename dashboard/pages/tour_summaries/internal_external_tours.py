"""Internal vs. external tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


GEO_LEVEL_COL = "geography_level"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def geo_level_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or GEO_LEVEL_COL not in first_df.columns:
        return ["All"]

    vals = (
        first_df.select(GEO_LEVEL_COL)
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return ["All"] + sorted(v for v in vals if v != "All")


def filter_geo_level(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        if GEO_LEVEL_COL in df.columns and geo_level != "All":
            df = df.with_columns(pl.col(GEO_LEVEL_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_LEVEL_COL) == geo_level
            )
        out.append((label, df))
    return out


class InternalExternalToursPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Internal vs. External Tours", state, config)

        geo_data = self.state.get_summary_table_set(
            "internal_external_nonmandatory_tour_frequency_by_home_geography",
            "weighted",
        )
        geo_opts = geo_level_options(geo_data or [])

        self.geo_level_sel = pn.widgets.Select(
            name="Geography Level",
            options=geo_opts,
            value=geo_opts[0],
        )
        self._watch_widget(self.geo_level_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Internal vs. External Tours"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
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

        int_ext_list = summaries[
            "internal_external_nonmandatory_tour_frequency_by_home_geography"
        ]
        external_loc_list = summaries["external_nonmandatory_tour_locations"]

        geo_opts = geo_level_options(int_ext_list)
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

        geo_level = self.geo_level_sel.value

        int_ext_data = self.get_filtered_view(
            "internal_external_nonmandatory_tours",
            geo_level,
            factory=lambda: filter_geo_level(int_ext_list, geo_level),
        )

        external_loc_data = self.get_filtered_view(
            "external_nonmandatory_tour_locations",
            geo_level,
            factory=lambda: filter_geo_level(external_loc_list, geo_level),
        )

        self._body.objects = [
            pn.Row(
                data_table(
                    int_ext_data,
                    "Internal vs. External Non-Mandatory Tour Frequency",
                ),
                data_table(
                    external_loc_data,
                    "External Non-Mandatory Tour Location",
                ),
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="internal_external_tours",
    title="Internal vs. External Tours",
    group_id="tour_summaries",
    child_id="internal_external_tours",
    order=46,
    controller_cls=InternalExternalToursPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="geography_level",
            widget_attr="geo_level_sel",
            label="Geography Level",
        ),
    ),
    required_summary_ids=(
        "internal_external_nonmandatory_tour_frequency_by_home_geography",
        "external_nonmandatory_tour_locations",
    ),
)

InternalExternalToursPage.definition = PAGE
