"""Mandatory location choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import (
    bar_chart,
    control_row,
    control_row_spacer,
    data_table,
    density_chart,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


GEO_LEVEL_COL = "geography_level"
GEO_COL = "geography"
GEO_TYPE_COL = "geography_type"
GEO_ID_COL = "geography_id"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _rename_present(df: pl.DataFrame, mapping: dict[str, str]) -> pl.DataFrame:
    rename_map = {
        source: target
        for source, target in mapping.items()
        if source in df.columns and target not in df.columns
    }
    return df.rename(rename_map) if rename_map else df


def _normalize_geography_columns(df: pl.DataFrame) -> pl.DataFrame:
    rename_map: dict[str, str] = {}
    if GEO_TYPE_COL in df.columns and GEO_LEVEL_COL not in df.columns:
        rename_map[GEO_TYPE_COL] = GEO_LEVEL_COL
    if GEO_ID_COL in df.columns and GEO_COL not in df.columns:
        rename_map[GEO_ID_COL] = GEO_COL
    return df.rename(rename_map) if rename_map else df


def _adapt_internal_external(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, _normalize_geography_columns(df)) for label, df in _nonempty(data_list)
    ]


def _adapt_external_workplace(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        normalized = _normalize_geography_columns(df)
        normalized = _rename_present(
            normalized,
            {
                GEO_COL: "workplace_location",
                "external_worker_count": "person_count",
            },
        )
        out.append((label, normalized))
    return out


def _adapt_workplace_lu(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, _normalize_geography_columns(df)) for label, df in _nonempty(data_list)
    ]


def _adapt_school_lu(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, _normalize_geography_columns(df)) for label, df in _nonempty(data_list)
    ]


def _adapt_commuting_flows(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        normalized = _rename_present(
            df,
            {
                "origin_geography_type": "origin_geography_level",
                "destination_geography_type": "destination_geography_level",
            },
        )
        out.append((label, normalized))
    return out


def geo_level_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None:
        return ["Total"]

    if GEO_LEVEL_COL in first_df.columns:
        vals = (
            first_df.select(GEO_LEVEL_COL)
            .drop_nulls()
            .unique()
            .to_series()
            .cast(pl.Utf8)
            .to_list()
        )
    elif {
        "origin_geography_level",
        "destination_geography_level",
    }.issubset(first_df.columns):
        vals = (
            pl.concat(
                [
                    first_df["origin_geography_level"].cast(pl.Utf8),
                    first_df["destination_geography_level"].cast(pl.Utf8),
                ]
            )
            .drop_nulls()
            .unique()
            .to_list()
        )
    else:
        return ["Total"]
    return sorted(vals) if vals else ["Total"]


def filter_geo_level(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        if GEO_LEVEL_COL in df.columns and geo_level not in {"Total", "All"}:
            df = df.with_columns(pl.col(GEO_LEVEL_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_LEVEL_COL) == geo_level
            )
        elif {
            "origin_geography_level",
            "destination_geography_level",
        }.issubset(df.columns) and geo_level not in {"Total", "All"}:
            df = df.with_columns(
                pl.col("origin_geography_level").cast(pl.Utf8),
                pl.col("destination_geography_level").cast(pl.Utf8),
            ).filter(
                (pl.col("origin_geography_level") == geo_level)
                & (pl.col("destination_geography_level") == geo_level)
            )
        out.append((label, df))
    return out


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (
            label,
            df.select(
                pl.col("distance_bin"),
                pl.col("person_count"),
            ).sort("distance_bin"),
        )
        for label, df in _nonempty(data_list)
    ]


class MandatoryLocationChoicePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Mandatory Location Choice", state, config)

        geo_opts = self._geo_level_options()
        self.geo_level_sel = pn.widgets.Select(
            name="Geography Level",
            options=geo_opts,
            value=geo_opts[0],
        )
        self._watch_widget(self.geo_level_sel)

        self.location_type_sel = pn.widgets.Select(
            name="Distance Location Type",
            options=["Workplace", "School", "University"],
            value="Workplace",
        )
        self._watch_widget(self.location_type_sel)

        self._worker_section = self.new_section()
        self._commuting_flows_section = self.new_section()
        self._distance_section = self.new_section()
        self._remote_work_section = self.new_section()
        self._flows_distance_row = pn.Row(
            pn.Column(control_row_spacer(), self._commuting_flows_section),
            pn.Column(
                control_row(
                    pn.pane.Markdown("**Distance Location Type:**"),
                    self.location_type_sel,
                ),
                self._distance_section,
            ),
            sizing_mode="stretch_width",
        )

        self.view = self.new_section(
            pn.pane.Markdown("## Mandatory Location Choice"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            self._worker_section,
            pn.pane.Markdown("### Commuting Flows and Location Distance"),
            self._flows_distance_row,
            self._remote_work_section,
        )

    def _geo_level_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "internal_external_worker_by_geography", "weighted"
        )
        if data is not None:
            return geo_level_options(_adapt_internal_external(data))
        commuting = self.state.get_summary_table_set("commuting_flows", "weighted")
        if commuting is not None:
            return geo_level_options(_adapt_commuting_flows(commuting))
        return ["Total"]

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._worker_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._commuting_flows_section.objects = []
            self._distance_section.objects = []
            self._remote_work_section.objects = []
            return

        internal_external = self.state.get_summary_table_set(
            "internal_external_worker_by_geography",
            self.weighting_key,
        )
        external_workplace = self.state.get_summary_table_set(
            "external_worker_workplace_locations",
            self.weighting_key,
        )
        commuting_flows = self.state.get_summary_table_set(
            "commuting_flows",
            self.weighting_key,
        )
        wfh_summary = self.state.get_summary_table_set(
            "work_from_home_rate_by_geography",
            self.weighting_key,
        )
        telecommute = self.state.get_summary_table_set(
            "telecommute_frequency_distribution",
            self.weighting_key,
        )

        dist_summary_id = {
            "Workplace": "work_location_distance_distribution_by_geography",
            "School": "school_location_distance_distribution_by_geography",
            "University": "university_location_distance_distribution_by_geography",
        }[self.location_type_sel.value]
        distance_summary = self.state.get_summary_table_set(
            dist_summary_id,
            self.weighting_key,
        )

        if not any(
            summary is not None
            for summary in (
                internal_external,
                external_workplace,
                # workplace_lu,
                # school_lu,
                commuting_flows,
                wfh_summary,
                telecommute,
                distance_summary,
            )
        ):
            self._worker_section.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            self._commuting_flows_section.objects = []
            self._distance_section.objects = []
            self._remote_work_section.objects = []
            return

        internal_external = (
            _adapt_internal_external(internal_external) if internal_external else None
        )
        external_workplace = (
            _adapt_external_workplace(external_workplace)
            if external_workplace
            else None
        )
        # workplace_lu = _adapt_workplace_lu(workplace_lu) if workplace_lu else None
        # school_lu = _adapt_school_lu(school_lu) if school_lu else None
        commuting_flows = (
            _adapt_commuting_flows(commuting_flows) if commuting_flows else None
        )

        geo_opts = geo_level_options(internal_external or commuting_flows or [])
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]
        geo_level = self.geo_level_sel.value

        worker_views: list[pn.viewable.Viewable] = [
            pn.pane.Markdown("### Worker Geography")
        ]
        if internal_external is not None:
            internal_external_table = self.get_filtered_view(
                "mandatory_internal_external",
                geo_level,
                factory=lambda: filter_geo_level(internal_external, geo_level),
            )
            worker_views.append(
                data_table(internal_external_table, "Internal vs. External Workers")
            )
        else:
            worker_views.append(
                self.data_not_available_card(
                    detail="The internal/external worker summary is unavailable.",
                    missing_items=["internal_external_worker_by_geography"],
                )
            )

        if external_workplace is not None:
            external_workplace_chart = bar_chart(
                _nonempty(external_workplace),
                x_col="workplace_location",
                y_col="person_count",
                title="External Worker Workplace Location",
                xaxis_title="Workplace Location",
                yaxis_title="External Workers",
                pct_col="pct",
                as_percent=self.as_percent,
            )
            worker_views.append(external_workplace_chart)
        else:
            worker_views.append(
                self.data_not_available_card(
                    detail="The external workplace summary is unavailable.",
                    missing_items=["external_worker_workplace_locations"],
                )
            )
        self._worker_section.objects = worker_views

        commuting_widget: pn.viewable.Viewable
        if commuting_flows is not None:
            commuting_flows_table = self.get_filtered_view(
                "mandatory_commuting_flows",
                geo_level,
                factory=lambda: filter_geo_level(commuting_flows, geo_level),
            )
            commuting_widget = data_table(commuting_flows_table, "Commuting Flows")
        else:
            commuting_widget = self.data_not_available_card(
                detail="The commuting flows summary is unavailable.",
                missing_items=["commuting_flows"],
            )
        self._commuting_flows_section.objects = [commuting_widget]

        distance_widget: pn.viewable.Viewable
        if distance_summary is not None:
            distance_data = self.get_filtered_view(
                "mandatory_distance_distribution",
                self.location_type_sel.value,
                factory=lambda: distance_chart_data(distance_summary),
            )
            distance_widget = density_chart(
                distance_data,
                x_col="distance_bin",
                y_col="person_count",
                title=f"{self.location_type_sel.value} Location Distance Distribution",
                xaxis_title="Distance (miles)",
                normalize=False,
                as_percent=self.as_percent,
            )
        else:
            distance_widget = self.data_not_available_card(
                detail="The selected distance distribution summary is unavailable.",
                missing_items=[dist_summary_id],
            )
        self._distance_section.objects = [distance_widget]

        remote_views: list[pn.viewable.Viewable] = [pn.pane.Markdown("### Remote Work")]
        remote_row: list[pn.viewable.Viewable] = []
        if wfh_summary is not None:
            wfh_data = self.get_filtered_view(
                "mandatory_wfh",
                geo_level,
                factory=lambda: filter_geo_level(wfh_summary, geo_level),
            )
            remote_row.append(
                bar_chart(
                    wfh_data,
                    x_col=GEO_COL,
                    y_col="work_from_home_worker_count",
                    title="Work From Home Rate by Geography",
                    xaxis_title="Geography",
                    yaxis_title="Workers",
                    as_percent=self.as_percent,
                )
            )
        else:
            remote_row.append(
                self.data_not_available_card(
                    detail="The work-from-home summary is unavailable.",
                    missing_items=["work_from_home_rate_by_geography"],
                )
            )

        if telecommute is not None:
            remote_row.append(
                bar_chart(
                    _nonempty(telecommute),
                    x_col="telecommute_frequency",
                    y_col="person_count",
                    title="Telecommute Rate",
                    xaxis_title="Telecommute Frequency",
                    yaxis_title="Workers",
                    as_percent=self.as_percent,
                )
            )
        else:
            remote_row.append(
                self.data_not_available_card(
                    detail="The telecommute summary is unavailable.",
                    missing_items=["telecommute_frequency_distribution"],
                )
            )
        remote_views.append(pn.Row(*remote_row))
        self._remote_work_section.objects = remote_views


PAGE = DashboardPageDefinition(
    page_id="mandatory_location_choice",
    title="Mandatory Location Choice",
    group_id="long_term_choices",
    child_id="mandatory_location_choice",
    order=27,
    controller_cls=MandatoryLocationChoicePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="geography_level",
            widget_attr="geo_level_sel",
            label="Geography Level",
        ),
        PageSelectorDefinition(
            selector_id="distance_location_type",
            widget_attr="location_type_sel",
            label="Distance Location Type",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="worker_geography",
            view_attr="_worker_section",
            selector_ids=("geography_level",),
        ),
        PageExportRegionDefinition(
            region_id="commuting_flows",
            view_attr="_commuting_flows_section",
            selector_ids=("geography_level",),
        ),
        PageExportRegionDefinition(
            region_id="distance_distribution",
            view_attr="_distance_section",
            selector_ids=("distance_location_type",),
        ),
        PageExportRegionDefinition(
            region_id="remote_work",
            view_attr="_remote_work_section",
            selector_ids=("geography_level",),
        ),
    ),
    required_summary_ids=(
        "internal_external_worker_by_geography",
        "external_worker_workplace_locations",
        "commuting_flows",
        "work_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        "work_from_home_rate_by_geography",
        "telecommute_frequency_distribution",
    ),
)

MandatoryLocationChoicePage.definition = PAGE
