"""Tour distance page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


GEO_LEVEL_COL = "geography_level"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    total_label: str = "All",
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    return [total_label] + sorted(v for v in vals if v != total_label)


def tour_distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8))

        if purpose != "All":
            df = df.filter(pl.col("tour_purpose") == purpose)

        out.append(
            (
                label,
                df.select(
                    pl.col("distance_bin"),
                    pl.col("tour_count"),
                ).sort("distance_bin"),
            )
        )
    return out


def avg_distance_table_data(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
    purpose_col: str,
    purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in _nonempty(data_list):
        if GEO_LEVEL_COL in df.columns and geo_level != "All":
            df = df.with_columns(pl.col(GEO_LEVEL_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_LEVEL_COL) == geo_level
            )

        if purpose_col in df.columns and purpose != "All":
            df = df.with_columns(pl.col(purpose_col).cast(pl.Utf8)).filter(
                pl.col(purpose_col) == purpose
            )

        out.append((label, df))

    return out


class TourDistancePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Distance", state, config)

        dist_data = self.state.get_summary_table_set(
            "tour_distance_by_tour_purpose", "weighted"
        )
        mand_data = self.state.get_summary_table_set(
            "average_mandatory_tour_distance_by_purpose_and_geography", "weighted"
        )
        nonmand_data = self.state.get_summary_table_set(
            "average_nonmandatory_tour_distance_by_purpose_and_geography", "weighted"
        )

        self.tour_purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=_options(dist_data or [], "tour_purpose"),
            value=_options(dist_data or [], "tour_purpose")[0],
        )
        self._watch_widget(self.tour_purpose_sel)

        self.geo_level_sel = pn.widgets.Select(
            name="Geography Level",
            options=_options(mand_data or [], GEO_LEVEL_COL),
            value=_options(mand_data or [], GEO_LEVEL_COL)[0],
        )
        self._watch_widget(self.geo_level_sel)

        self.mand_purpose_sel = pn.widgets.Select(
            name="Mandatory Tour Purpose",
            options=_options(mand_data or [], "mandatory_tour_purpose"),
            value=_options(mand_data or [], "mandatory_tour_purpose")[0],
        )
        self._watch_widget(self.mand_purpose_sel)

        self.nonmand_purpose_sel = pn.widgets.Select(
            name="Non-Mandatory Tour Purpose",
            options=_options(nonmand_data or [], "nonmandatory_tour_purpose"),
            value=_options(nonmand_data or [], "nonmandatory_tour_purpose")[0],
        )
        self._watch_widget(self.nonmand_purpose_sel)

        self._distance_section = self.new_section()
        self._average_section = self.new_section()

        self.view = self.new_section(
            pn.pane.Markdown("## Tour Distance"),
            self._distance_section,
            self._average_section,
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._distance_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._average_section.objects = []
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._distance_section.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            self._average_section.objects = []
            return

        dist_list = summaries["tour_distance_by_tour_purpose"]
        mand_list = summaries[
            "average_mandatory_tour_distance_by_purpose_and_geography"
        ]
        nonmand_list = summaries[
            "average_nonmandatory_tour_distance_by_purpose_and_geography"
        ]

        tour_purpose_opts = _options(dist_list, "tour_purpose")
        self.tour_purpose_sel.options = tour_purpose_opts
        if self.tour_purpose_sel.value not in tour_purpose_opts:
            self.tour_purpose_sel.value = tour_purpose_opts[0]

        geo_opts = _options(mand_list, GEO_LEVEL_COL)
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

        mand_purpose_opts = _options(mand_list, "mandatory_tour_purpose")
        self.mand_purpose_sel.options = mand_purpose_opts
        if self.mand_purpose_sel.value not in mand_purpose_opts:
            self.mand_purpose_sel.value = mand_purpose_opts[0]

        nonmand_purpose_opts = _options(nonmand_list, "nonmandatory_tour_purpose")
        self.nonmand_purpose_sel.options = nonmand_purpose_opts
        if self.nonmand_purpose_sel.value not in nonmand_purpose_opts:
            self.nonmand_purpose_sel.value = nonmand_purpose_opts[0]

        tour_purpose = self.tour_purpose_sel.value
        geo_level = self.geo_level_sel.value
        mand_purpose = self.mand_purpose_sel.value
        nonmand_purpose = self.nonmand_purpose_sel.value

        distance_data = self.get_filtered_view(
            "tour_distance",
            tour_purpose,
            factory=lambda: tour_distance_chart_data(dist_list, tour_purpose),
        )

        mand_avg_data = self.get_filtered_view(
            "average_mandatory_tour_distance",
            (geo_level, mand_purpose),
            factory=lambda: avg_distance_table_data(
                mand_list,
                geo_level,
                "mandatory_tour_purpose",
                mand_purpose,
            ),
        )

        nonmand_avg_data = self.get_filtered_view(
            "average_nonmandatory_tour_distance",
            (geo_level, nonmand_purpose),
            factory=lambda: avg_distance_table_data(
                nonmand_list,
                geo_level,
                "nonmandatory_tour_purpose",
                nonmand_purpose,
            ),
        )

        distance_chart = density_chart(
            distance_data,
            x_col="distance_bin",
            y_col="tour_count",
            title=f"Tour Distance Distribution - {tour_purpose}",
            xaxis_title="Distance (miles)",
            normalize=False,
            as_percent=self.as_percent,
        )

        self._distance_section.objects = [
            pn.pane.Markdown("### Tour Distance Distribution"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.tour_purpose_sel,
            ),
            distance_chart,
            data_table(distance_data, "Tour Distance"),
        ]

        self._average_section.objects = [
            pn.pane.Markdown("### Average Tour Distance by Geography"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            pn.Row(
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Mandatory Tour Purpose:**"),
                        self.mand_purpose_sel,
                    ),
                    data_table(
                        mand_avg_data,
                        "Average Mandatory Tour Distance",
                    ),
                ),
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Non-Mandatory Tour Purpose:**"),
                        self.nonmand_purpose_sel,
                    ),
                    data_table(
                        nonmand_avg_data,
                        "Average Non-Mandatory Tour Distance",
                    ),
                ),
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_distance",
    title="Tour Distance",
    order=44,
    controller_cls=TourDistancePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="tour_purpose_sel",
            label="Tour Purpose",
        ),
        PageSelectorDefinition(
            selector_id="geography_level",
            widget_attr="geo_level_sel",
            label="Geography Level",
        ),
        PageSelectorDefinition(
            selector_id="mandatory_tour_purpose",
            widget_attr="mand_purpose_sel",
            label="Mandatory Tour Purpose",
        ),
        PageSelectorDefinition(
            selector_id="nonmandatory_tour_purpose",
            widget_attr="nonmand_purpose_sel",
            label="Non-Mandatory Tour Purpose",
        ),
    ),
    required_summary_ids=(
        "tour_distance_by_tour_purpose",
        "average_mandatory_tour_distance_by_purpose_and_geography",
        "average_nonmandatory_tour_distance_by_purpose_and_geography",
    ),
)

TourDistancePage.definition = PAGE
