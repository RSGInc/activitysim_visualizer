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
from dashboard.page_base import SectionContent
from dashboard.page_definitions import DashboardPageDefinition
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


PREFERRED_GEO_ORDER = [
    "all_geographies",
    "district",
    "taz",
    "maz",
]


def _ordered_geo_options(values: set[str]) -> list[str]:
    ordered = [v for v in PREFERRED_GEO_ORDER if v in values]
    extras = sorted(v for v in values if v not in PREFERRED_GEO_ORDER)
    return ordered + extras


def geo_level_option_set(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> set[str]:
    """Return geography levels available in every non-empty run in this summary."""
    if data_list is None:
        return set()

    per_run: list[set[str]] = []

    for _, df in _nonempty(data_list):
        if GEO_LEVEL_COL in df.columns:
            vals = (
                df.select(GEO_LEVEL_COL)
                .drop_nulls()
                .unique()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            )
            per_run.append(set(vals))

        elif {
            "origin_geography_level",
            "destination_geography_level",
        }.issubset(df.columns):
            origin_vals = set(
                df["origin_geography_level"]
                .cast(pl.Utf8)
                .drop_nulls()
                .unique()
                .to_list()
            )
            dest_vals = set(
                df["destination_geography_level"]
                .cast(pl.Utf8)
                .drop_nulls()
                .unique()
                .to_list()
            )

            # For the current flow filter, origin and destination must both
            # support the selected level.
            per_run.append(origin_vals & dest_vals)

    if not per_run:
        return set()

    return set.intersection(*per_run)


def core_geo_level_options(
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    """Use only geography levels available in all provided core summaries."""
    available_sets = [
        geo_level_option_set(summary)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [s for s in available_sets if s]

    if not available_sets:
        return ["Total"]

    common = set.intersection(*available_sets)
    return _ordered_geo_options(common) or ["Total"]


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


def wfh_geo_level_options(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or GEO_TYPE_COL not in first_df.columns:
        return []

    vals = (
        first_df.select(GEO_TYPE_COL)
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )

    preferred_order = ["all_geographies", "district", "taz", "maz"]
    ordered = [v for v in preferred_order if v in vals]
    extras = sorted(v for v in vals if v not in preferred_order)

    return ordered + extras


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


def wfh_chart_data(
    wfh_list: list[tuple[str, pl.DataFrame]],
    geography_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in wfh_list:
        if df is None or len(df) == 0:
            continue

        chart_df = (
            df.with_columns(
                pl.col(GEO_TYPE_COL).cast(pl.Utf8),
                pl.col(GEO_ID_COL).cast(pl.Utf8),
            )
            .filter(pl.col(GEO_TYPE_COL) == geography_type)
            .with_columns(
                pl.when(pl.col("worker_count") > 0)
                .then(
                    pl.col("work_from_home_worker_count")
                    / pl.col("worker_count")
                    * 100.0
                )
                .otherwise(0.0)
                .alias("work_from_home_rate")
            )
            .with_columns(
                pl.when(pl.col(GEO_ID_COL) == "all_geographies")
                .then(pl.lit("All Geographies"))
                .otherwise(pl.col(GEO_ID_COL))
                .alias("geography_label")
            )
            .sort("geography_label")
        )

        out.append((label, chart_df))

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
    def build_page(self) -> pn.viewable.Viewable:
        self._current_data: dict[str, object] = {}
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=["Total"],
                value="Total",
            ),
            label="Geography Level",
        )
        self.location_type_sel = self.selector(
            "distance_location_type",
            widget=pn.widgets.Select(
                name="Distance Location Type",
                options=["Workplace", "School", "University"],
                value="Workplace",
            ),
            label="Distance Location Type",
        )

        self._worker_section = self.section(
            "worker_geography",
            selectors=("geography_level",),
            render=self.render_worker_geography,
        )
        self._commuting_flows_section = self.section(
            "commuting_flows",
            selectors=("geography_level",),
            render=self.render_commuting_flows,
        )
        self._distance_section = self.section(
            "distance_distribution",
            selectors=("distance_location_type",),
            render=self.render_distance_distribution,
        )
        self._remote_work_section = self.section(
            "remote_work",
            selectors=("geography_level",),
            render=self.render_remote_work,
        )
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

        return self.new_section(
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

    def sync_controls(self) -> None:
        self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

    def _collect_data(self) -> dict[str, object]:
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": ["Total"],
            }
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
            return {
                "mode": "unavailable",
                "geo_opts": ["Total"],
            }

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

        geo_opts = core_geo_level_options(
            internal_external, commuting_flows, wfh_summary
        )
        return {
            "mode": "ready",
            "geo_opts": geo_opts,
            "internal_external": internal_external,
            "external_workplace": external_workplace,
            "commuting_flows": commuting_flows,
            "wfh_summary": wfh_summary,
            "telecommute": telecommute,
            "distance_summary": distance_summary,
            "dist_summary_id": dist_summary_id,
        }

    def render_worker_geography(self) -> SectionContent:
        if self._current_data["mode"] == "no_runs":
            return [pn.pane.Markdown("No runs loaded.")]
        if self._current_data["mode"] == "unavailable":
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
        geo_level = str(self.geo_level_sel.value)
        internal_external = self._current_data["internal_external"]
        external_workplace = self._current_data["external_workplace"]
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
        return worker_views

    def render_commuting_flows(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        geo_level = str(self.geo_level_sel.value)
        commuting_flows = self._current_data["commuting_flows"]
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
        return [commuting_widget]

    def render_distance_distribution(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        distance_summary = self._current_data["distance_summary"]
        dist_summary_id = self._current_data["dist_summary_id"]
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
                yaxis_title=f"{self.location_type_sel.value} Locations",
                normalize=False,
                as_percent=self.as_percent,
            )
        else:
            distance_widget = self.data_not_available_card(
                detail="The selected distance distribution summary is unavailable.",
                missing_items=[dist_summary_id],
            )
        return [distance_widget]

    def render_remote_work(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        geo_level = str(self.geo_level_sel.value)
        wfh_summary = self._current_data["wfh_summary"]
        telecommute = self._current_data["telecommute"]
        remote_views: list[pn.viewable.Viewable] = [pn.pane.Markdown("### Remote Work")]
        remote_row: list[pn.viewable.Viewable] = []
        if wfh_summary is not None:
            wfh_data = self.get_filtered_view(
                "mandatory_wfh",
                geo_level,
                factory=lambda: wfh_chart_data(
                    wfh_summary,
                    geo_level,
                ),
            )
            remote_row.append(
                bar_chart(
                    wfh_data,
                    x_col="geography_label",
                    y_col="work_from_home_rate",
                    title="Work From Home Rate by Geography",
                    xaxis_title="Geography",
                    yaxis_title="Workers Working From Home (%)",
                    as_percent=False,
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
                    yaxis_title="Workers Who Do Not Work From Home",
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
        return remote_views


PAGE = DashboardPageDefinition(
    page_id="mandatory_location_choice",
    title="Mandatory Location Choice",
    group_id="long_term_choices",
    order=27,
    page_cls=MandatoryLocationChoicePage,
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
