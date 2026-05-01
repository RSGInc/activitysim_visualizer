"""Internal vs. external tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


GEO_LEVEL_COL = "geography_level"
GEO_TYPE_COL = "geography_type"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _normalize_geography_columns(df: pl.DataFrame) -> pl.DataFrame:
    if GEO_TYPE_COL in df.columns and GEO_LEVEL_COL not in df.columns:
        return df.rename({GEO_TYPE_COL: GEO_LEVEL_COL})
    return df


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

        int_ext_list = self.optional_summary(
            "internal_external_nonmandatory_tour_frequency_by_home_geography"
        )
        external_loc_list = self.optional_summary("external_nonmandatory_tour_locations")

        normalized_int_ext = (
            [(label, _normalize_geography_columns(df)) for label, df in int_ext_list]
            if int_ext_list is not None
            else []
        )
        normalized_external_loc = (
            [(label, _normalize_geography_columns(df)) for label, df in external_loc_list]
            if external_loc_list is not None
            else []
        )

        geo_opts = geo_level_options(normalized_int_ext or normalized_external_loc)
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

        geo_level = self.geo_level_sel.value

        if normalized_int_ext:
            int_ext_data = self.get_filtered_view(
                "internal_external_nonmandatory_tours",
                geo_level,
                factory=lambda: filter_geo_level(normalized_int_ext, geo_level),
            )
            int_ext_widget: pn.viewable.Viewable = data_table(
                int_ext_data,
                "Internal vs. External Non-Mandatory Tour Frequency",
            )
        else:
            int_ext_widget = self.data_not_available_card(
                detail="The internal/external non-mandatory tour summary is unavailable.",
                missing_items=[
                    "internal_external_nonmandatory_tour_frequency_by_home_geography"
                ],
            )

        if normalized_external_loc:
            external_loc_data = self.get_filtered_view(
                "external_nonmandatory_tour_locations",
                geo_level,
                factory=lambda: filter_geo_level(normalized_external_loc, geo_level),
            )
            external_loc_widget: pn.viewable.Viewable = data_table(
                external_loc_data,
                "External Non-Mandatory Tour Location",
            )
        else:
            external_loc_widget = self.data_not_available_card(
                detail="The external non-mandatory tour location summary is unavailable.",
                missing_items=["external_nonmandatory_tour_locations"],
            )

        self._body.objects = [
            pn.Row(
                int_ext_widget,
                external_loc_widget,
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="internal_external_tours",
    title="Internal vs. External Tours",
    group_id="tour_summaries",
    order=46,
    page_cls=InternalExternalToursPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="geography_level",
            widget_attr="geo_level_sel",
            label="Geography Level",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="internal_external_tours_body",
            view_attr="_body",
            selector_ids=("geography_level",),
        ),
    ),
    required_summary_ids=(
        "internal_external_nonmandatory_tour_frequency_by_home_geography",
        "external_nonmandatory_tour_locations",
    ),
)

InternalExternalToursPage.definition = PAGE

