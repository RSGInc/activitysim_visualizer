"""Internal vs. external tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table
from dashboard.helpers.geography_helpers import detail_geography_levels
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

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


def geo_level_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    config,
) -> list[str]:
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
    vals = detail_geography_levels(vals, config=config)
    return vals or ["All"]


def common_geo_level_options(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
    config,
) -> list[str]:
    available_sets: list[set[str]] = []
    for data_list in data_lists:
        if data_list is None:
            continue
        per_run_sets: list[set[str]] = []
        for _, df in _nonempty(data_list):
            if GEO_LEVEL_COL not in df.columns:
                continue
            vals = (
                df.select(GEO_LEVEL_COL)
                .drop_nulls()
                .unique()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            )
            per_run_sets.append(set(vals))
        if per_run_sets:
            available_sets.append(set.intersection(*per_run_sets))
    if not available_sets:
        return ["All"]
    common = set.intersection(*available_sets)
    ordered = detail_geography_levels(list(common), config=config)
    return ordered or ["All"]


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
    def build_page(self) -> pn.viewable.Viewable:
        geo_data = self.state.get_summary_table_set(
            "internal_external_nonmandatory_tour_frequency_by_home_geography",
            "weighted",
        )
        geo_opts = geo_level_options(geo_data or [], config=self.config)
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=geo_opts,
                value=geo_opts[0],
            ),
            label="Geography Level",
        )
        self._body = self.section(
            "internal_external_tours_body",
            selectors=("geography_level",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Internal vs. External Tours"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        int_ext_list = self.optional_summary(
            "internal_external_nonmandatory_tour_frequency_by_home_geography"
        )
        external_loc_list = self.optional_summary(
            "external_nonmandatory_tour_locations"
        )
        normalized_int_ext = (
            [(label, _normalize_geography_columns(df)) for label, df in int_ext_list]
            if int_ext_list is not None
            else []
        )
        normalized_external_loc = (
            [
                (label, _normalize_geography_columns(df))
                for label, df in external_loc_list
            ]
            if external_loc_list is not None
            else []
        )
        geo_opts = common_geo_level_options(
            normalized_int_ext or None,
            normalized_external_loc or None,
            config=self.config,
        )
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        int_ext_list = self.optional_summary(
            "internal_external_nonmandatory_tour_frequency_by_home_geography"
        )
        external_loc_list = self.optional_summary(
            "external_nonmandatory_tour_locations"
        )

        normalized_int_ext = (
            [(label, _normalize_geography_columns(df)) for label, df in int_ext_list]
            if int_ext_list is not None
            else []
        )
        normalized_external_loc = (
            [
                (label, _normalize_geography_columns(df))
                for label, df in external_loc_list
            ]
            if external_loc_list is not None
            else []
        )
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

        return [
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
    required_summary_ids=(
        "internal_external_nonmandatory_tour_frequency_by_home_geography",
        "external_nonmandatory_tour_locations",
    ),
)

InternalExternalToursPage.definition = PAGE
