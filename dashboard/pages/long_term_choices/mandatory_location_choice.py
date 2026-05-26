"""Mandatory location choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import (
    bar_chart,
    control_row,
    data_table,
    density_chart,
    format_numeric_for_display,
)
from dashboard.helpers.category_helpers import label_category_data, ordered_category_values
from dashboard.helpers.geography_helpers import detail_geography_levels
from dashboard.page_base import DashboardPage
from dashboard.page_base import SectionContent
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config

GEO_LEVEL_COL = "geography_level"
GEO_COL = "geography"
GEO_TYPE_COL = "geography_type"
GEO_ID_COL = "geography_id"
ALL_GEOGRAPHIES_VALUE = "all_geographies"
ALL_WITHIN_LEVEL_VALUE = "All"


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
        if GEO_COL in normalized.columns and "workplace_location" not in normalized.columns:
            normalized = normalized.with_columns(
                pl.col(GEO_COL).alias("workplace_location")
            )
        normalized = _rename_present(normalized, {"external_worker_count": "person_count"})
        out.append((label, normalized))
    return out


def _external_workplace_percent_data(
    external_workplace: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    if geo_level != "all_geographies":
        return external_workplace

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(external_workplace):
        if "all_worker_count" not in df.columns:
            out.append((label, df))
            continue
        denominator = float(df["all_worker_count"][0] or 0.0)
        if denominator <= 0:
            out.append((label, df))
            continue
        normalized = df.with_columns(
            (
                pl.col("person_count").cast(pl.Float64) / denominator * 100.0
            ).alias("external_worker_percent")
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


def _ordered_geo_options(values: set[str], *, config: Config) -> list[str]:
    return detail_geography_levels(list(values), config=config)


def _ordered_geography_ids(values: set[str], *, config: Config) -> list[str]:
    ordered = sorted(str(value) for value in values if str(value).strip())
    return config.ordered_values("geography", ordered)


def geo_level_option_set(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> set[str]:
    """Return geography levels available in any non-empty run in this summary."""
    if data_list is None:
        return set()

    available: set[str] = set()

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
            available.update(vals)
        elif GEO_TYPE_COL in df.columns:
            vals = (
                df.select(GEO_TYPE_COL)
                .drop_nulls()
                .unique()
                .to_series()
                .cast(pl.Utf8)
                .to_list()
            )
            available.update(vals)

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
            available.update(origin_vals & dest_vals)

    return available


def core_geo_level_options(
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
) -> list[str]:
    """Use geography levels available in any provided core summary."""
    available_sets = [
        geo_level_option_set(summary)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [s for s in available_sets if s]

    if not available_sets:
        return ["Total"]

    union = set().union(*available_sets)
    return _ordered_geo_options(union, config=config) or ["Total"]


def geography_id_option_set(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    geo_level: str,
) -> set[str]:
    """Return geography ids available at one geography level in this summary."""
    if data_list is None:
        return set()

    available: set[str] = set()
    for _, df in _nonempty(data_list):
        if {GEO_TYPE_COL, GEO_ID_COL}.issubset(df.columns):
            ids = (
                df.with_columns(
                    pl.col(GEO_TYPE_COL).cast(pl.Utf8),
                    pl.col(GEO_ID_COL).cast(pl.Utf8),
                )
                .filter(pl.col(GEO_TYPE_COL) == geo_level)
                .select(GEO_ID_COL)
                .drop_nulls()
                .unique()
                .to_series()
                .to_list()
            )
            available.update(str(value) for value in ids)
        elif {GEO_LEVEL_COL, GEO_COL}.issubset(df.columns):
            ids = (
                df.with_columns(
                    pl.col(GEO_LEVEL_COL).cast(pl.Utf8),
                    pl.col(GEO_COL).cast(pl.Utf8),
                )
                .filter(pl.col(GEO_LEVEL_COL) == geo_level)
                .select(GEO_COL)
                .drop_nulls()
                .unique()
                .to_series()
                .to_list()
            )
            available.update(str(value) for value in ids)
        elif {"origin_geography_level", "origin_geography_id"}.issubset(df.columns):
            ids = (
                df.with_columns(
                    pl.col("origin_geography_level").cast(pl.Utf8),
                    pl.col("origin_geography_id").cast(pl.Utf8),
                )
                .filter(pl.col("origin_geography_level") == geo_level)
                .select("origin_geography_id")
                .drop_nulls()
                .unique()
                .to_series()
                .to_list()
            )
            available.update(str(value) for value in ids)
    return available


def geography_options_for_level(
    geo_level: str,
    *summary_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
) -> list[str]:
    if geo_level in {"Total", "All"}:
        return [ALL_WITHIN_LEVEL_VALUE]
    if geo_level == ALL_GEOGRAPHIES_VALUE:
        return [ALL_GEOGRAPHIES_VALUE]

    available_sets = [
        geography_id_option_set(summary, geo_level)
        for summary in summary_lists
        if summary is not None
    ]
    available_sets = [s for s in available_sets if s]
    if not available_sets:
        return [ALL_WITHIN_LEVEL_VALUE]

    union = set().union(*available_sets)
    ordered = _ordered_geography_ids(union, config=config)
    return [ALL_WITHIN_LEVEL_VALUE] + ordered if ordered else [ALL_WITHIN_LEVEL_VALUE]


def geo_level_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    config: Config,
) -> list[str]:
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
    elif GEO_TYPE_COL in first_df.columns:
        vals = (
            first_df.select(GEO_TYPE_COL)
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
    ordered = detail_geography_levels(vals, config=config)
    return ordered if ordered else ["Total"]


def wfh_geo_level_options(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    config: Config,
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

    return detail_geography_levels(vals, config=config)


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
        }.issubset(
            df.columns
        ) and geo_level not in {"Total", "All"}:
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
    geography: str = ALL_WITHIN_LEVEL_VALUE,
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
            .pipe(
                lambda frame: frame
                if geography in {ALL_WITHIN_LEVEL_VALUE, "Total", "All"}
                else frame.filter(pl.col(GEO_ID_COL) == geography)
            )
            .with_columns(
                pl.when(pl.col("worker_count") > 0)
                .then(
                    pl.col("work_from_home_worker_count")
                    / pl.col("worker_count")
                    * 100.0
                )
                .otherwise(0.0)
                .alias("work_from_home_percent")
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
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        chart_df = df
        if {"geography_type", "geography_id"}.issubset(df.columns):
            chart_df = (
                df.group_by("distance_bin")
                .agg(person_count=pl.col("person_count").sum())
                .sort("distance_bin")
            )
        else:
            chart_df = df.select(
                pl.col("distance_bin"),
                pl.col("person_count"),
            ).sort("distance_bin")
        out.append((label, chart_df))
    return out


def filter_geography(
    data_list: list[tuple[str, pl.DataFrame]],
    geography: str,
) -> list[tuple[str, pl.DataFrame]]:
    if geography in {ALL_WITHIN_LEVEL_VALUE, "Total", "All"}:
        return _nonempty(data_list)

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if GEO_COL in df.columns:
            filtered = df.with_columns(pl.col(GEO_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_COL) == geography
            )
        elif GEO_ID_COL in df.columns:
            filtered = df.with_columns(pl.col(GEO_ID_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_ID_COL) == geography
            )
        else:
            filtered = df
        out.append((label, filtered))
    return out


def filter_origin_geography(
    data_list: list[tuple[str, pl.DataFrame]],
    geography: str,
) -> list[tuple[str, pl.DataFrame]]:
    if geography in {ALL_WITHIN_LEVEL_VALUE, "Total", "All"}:
        return _nonempty(data_list)

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if "origin_geography_id" in df.columns:
            filtered = df.with_columns(
                pl.col("origin_geography_id").cast(pl.Utf8)
            ).filter(pl.col("origin_geography_id") == geography)
        elif GEO_COL in df.columns:
            filtered = df.with_columns(pl.col(GEO_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_COL) == geography
            )
        elif GEO_ID_COL in df.columns:
            filtered = df.with_columns(pl.col(GEO_ID_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_ID_COL) == geography
            )
        else:
            filtered = df
        out.append((label, filtered))
    return out


def filter_distance_geo_level(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        filtered = df
        if geo_level not in {"Total", "All"}:
            if GEO_TYPE_COL in filtered.columns:
                filtered = filtered.with_columns(pl.col(GEO_TYPE_COL).cast(pl.Utf8)).filter(
                    pl.col(GEO_TYPE_COL) == geo_level
                )
            elif GEO_LEVEL_COL in filtered.columns:
                filtered = filtered.with_columns(pl.col(GEO_LEVEL_COL).cast(pl.Utf8)).filter(
                    pl.col(GEO_LEVEL_COL) == geo_level
                )
            elif GEO_COL in filtered.columns:
                filtered = filtered.with_columns(pl.col(GEO_COL).cast(pl.Utf8)).filter(
                    pl.col(GEO_COL) == geo_level
                )
        out.append((label, filtered))
    return out


def filter_distance_geography(
    data_list: list[tuple[str, pl.DataFrame]],
    geography: str,
) -> list[tuple[str, pl.DataFrame]]:
    return filter_geography(data_list, geography)


def mandatory_distance_comparison_table(
    data_list: list[tuple[str, pl.DataFrame]],
    geography_level: str,
    geography: str,
    *,
    config: Config,
) -> pl.DataFrame:
    filtered = filter_distance_geography(
        filter_distance_geo_level(data_list, geography_level),
        geography,
    )
    nonempty_runs = _nonempty(filtered)
    if not nonempty_runs:
        return pl.DataFrame()

    purpose_values = ordered_category_values(
        nonempty_runs,
        "mandatory_tour_purpose",
        category_id="tour_purpose",
        config=config,
    )
    if not purpose_values:
        return pl.DataFrame()

    base_label, base_df = nonempty_runs[0]
    def _aggregated_lookup(df: pl.DataFrame) -> dict[str, float]:
        if df.is_empty():
            return {}
        if "person_count" in df.columns:
            aggregated = (
                df.group_by("mandatory_tour_purpose")
                .agg(
                    person_count=pl.col("person_count").sum(),
                    weighted_distance=(
                        pl.col("average_tour_distance") * pl.col("person_count")
                    ).sum(),
                )
                .with_columns(
                    pl.when(pl.col("person_count") > 0)
                    .then(pl.col("weighted_distance") / pl.col("person_count"))
                    .otherwise(None)
                    .alias("average_tour_distance")
                )
                .select("mandatory_tour_purpose", "average_tour_distance")
            )
        else:
            aggregated = (
                df.group_by("mandatory_tour_purpose")
                .agg(pl.col("average_tour_distance").mean().alias("average_tour_distance"))
                .select("mandatory_tour_purpose", "average_tour_distance")
            )
        return {
            str(row["mandatory_tour_purpose"]): float(row["average_tour_distance"])
            for row in aggregated.to_dicts()
            if row.get("mandatory_tour_purpose") is not None
            and row.get("average_tour_distance") is not None
        }

    lookups_by_label = {
        run_label: _aggregated_lookup(run_df)
        for run_label, run_df in nonempty_runs
    }
    base_lookup = lookups_by_label[base_label]

    rows: list[dict[str, object]] = []
    for purpose in purpose_values:
        row = {
            "Mandatory Tour Purpose": config.label_value("tour_purpose", purpose),
        }
        base_value = base_lookup.get(str(purpose))
        row[base_label] = "0%" if base_value is not None else ""
        for run_label, _ in nonempty_runs[1:]:
            run_value = lookups_by_label[run_label].get(str(purpose))
            if run_value in {None} or base_value in {None, 0.0}:
                row[run_label] = ""
                continue
            pct_diff = ((run_value - base_value) / base_value) * 100.0
            formatted = format_numeric_for_display(pct_diff, precision=2)
            row[run_label] = f"{formatted}%" if formatted is not None else ""
        rows.append(row)

    return pl.DataFrame(rows) if rows else pl.DataFrame()


def telecommute_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    telecommute_values: list[str],
) -> list[tuple[str, pl.DataFrame]]:
    if not telecommute_values:
        return _nonempty(data_list)

    scaffold = pl.DataFrame(
        {"telecommute_frequency": telecommute_values},
        schema={"telecommute_frequency": pl.Utf8},
    )
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        if "telecommute_frequency" not in df.columns or "person_count" not in df.columns:
            continue
        aggregated = (
            df.with_columns(pl.col("telecommute_frequency").cast(pl.Utf8))
            .group_by("telecommute_frequency")
            .agg(person_count=pl.col("person_count").sum())
        )
        completed = (
            scaffold.join(aggregated, on="telecommute_frequency", how="left")
            .with_columns(pl.col("person_count").fill_null(0.0).cast(pl.Float64))
        )
        out.append((label, completed))
    return out


class MandatoryLocationChoicePage(DashboardPage):
    def on_global_state_changed(self) -> None:
        self.clear_filtered_view_cache()
        self._current_data = self._collect_data()

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
        self.geography_sel = self.selector(
            "geography",
            widget=pn.widgets.Select(
                name="Geography",
                options=[ALL_WITHIN_LEVEL_VALUE],
                value=ALL_WITHIN_LEVEL_VALUE,
            ),
            label="Geography",
        )

        self._worker_section = self.section(
            "worker_geography",
            selectors=("geography_level", "geography"),
            render=self.render_worker_geography,
        )
        self._commuting_flows_section = self.section(
            "commuting_flows",
            selectors=("geography_level", "geography"),
            render=self.render_commuting_flows,
        )
        self._mandatory_distance_table_section = self.section(
            "mandatory_distance_table",
            selectors=("geography_level", "geography"),
            render=self.render_mandatory_distance_table,
        )
        self._distance_section = self.section(
            "distance_distribution",
            selectors=("geography_level", "geography"),
            render=self.render_distance_distribution,
        )
        self._remote_work_section = self.section(
            "remote_work",
            selectors=("geography_level", "geography"),
            render=self.render_remote_work,
        )

        return self.new_section(
            pn.pane.Markdown("## Mandatory Location Choice"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
                pn.pane.Markdown("**Geography:**"),
                self.geography_sel,
            ),
            self._remote_work_section,
            self._distance_section,
            self._worker_section,
            self._commuting_flows_section,
            self._mandatory_distance_table_section,
        )

    def _geo_level_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "internal_external_worker_by_geography", "weighted"
        )
        if data is not None:
            return geo_level_options(_adapt_internal_external(data), config=self.config)
        commuting = self.state.get_summary_table_set("commuting_flows", "weighted")
        if commuting is not None:
            return geo_level_options(_adapt_commuting_flows(commuting), config=self.config)
        return ["Total"]

    def sync_controls(self) -> None:
        if not self._current_data:
            self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]
        geography_opts = self._current_data["geography_opts_by_level"].get(
            str(self.geo_level_sel.value),
            [ALL_WITHIN_LEVEL_VALUE],
        )
        self.geography_sel.options = geography_opts
        if self.geography_sel.value not in geography_opts:
            self.geography_sel.value = geography_opts[0]

    def _collect_data(self) -> dict[str, object]:
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": ["Total"],
                "geography_opts_by_level": {"Total": [ALL_WITHIN_LEVEL_VALUE]},
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
        work_distance_summary = self.state.get_summary_table_set(
            "work_location_distance_distribution_by_geography",
            self.weighting_key,
        )
        school_distance_summary = self.state.get_summary_table_set(
            "school_location_distance_distribution_by_geography",
            self.weighting_key,
        )
        university_distance_summary = self.state.get_summary_table_set(
            "university_location_distance_distribution_by_geography",
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
                work_distance_summary,
                school_distance_summary,
                university_distance_summary,
            )
        ):
            return {
                "mode": "unavailable",
                "geo_opts": ["Total"],
                "geography_opts_by_level": {"Total": [ALL_WITHIN_LEVEL_VALUE]},
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
            internal_external, commuting_flows, wfh_summary, config=self.config
        )
        geography_option_sources = (
            internal_external,
            commuting_flows,
            work_distance_summary,
            school_distance_summary,
            university_distance_summary,
            self.state.get_summary_table_set(
                "average_mandatory_tour_distance_by_purpose_and_geography",
                self.weighting_key,
            ),
        )
        geography_opts_by_level = {
            geo_level: geography_options_for_level(
                geo_level,
                *geography_option_sources,
                config=self.config,
            )
            for geo_level in geo_opts
        }
        return {
            "mode": "ready",
            "geo_opts": geo_opts,
            "geography_opts_by_level": geography_opts_by_level,
            "internal_external": internal_external,
            "external_workplace": external_workplace,
            "commuting_flows": commuting_flows,
            "wfh_summary": wfh_summary,
            "telecommute": telecommute,
            "work_distance_summary": work_distance_summary,
            "school_distance_summary": school_distance_summary,
            "university_distance_summary": university_distance_summary,
            "average_mandatory_tour_distance": self.state.get_summary_table_set(
                "average_mandatory_tour_distance_by_purpose_and_geography",
                self.weighting_key,
            ),
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
        geography = str(self.geography_sel.value)
        internal_external = self._current_data["internal_external"]
        external_workplace = self._current_data["external_workplace"]
        worker_views: list[pn.viewable.Viewable] = []
        if internal_external is not None:
            internal_external_table = self.get_filtered_view(
                "mandatory_internal_external",
                (geo_level, geography),
                factory=lambda: filter_geography(
                    filter_geo_level(internal_external, geo_level),
                    geography,
                ),
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
            filtered_external_workplace = self.get_filtered_view(
                "mandatory_external_workplace",
                (geo_level, geography),
                factory=lambda: filter_geography(
                    filter_geo_level(external_workplace, geo_level),
                    geography,
                ),
            )
            external_workplace_data = filtered_external_workplace
            if self.as_percent:
                external_workplace_data = self.get_filtered_view(
                    "mandatory_external_workplace_percent",
                    (geo_level, geography),
                    factory=lambda: _external_workplace_percent_data(
                        filtered_external_workplace,
                        geo_level,
                    ),
                )
            external_workplace_chart = bar_chart(
                external_workplace_data,
                x_col="workplace_location",
                y_col=(
                    "external_worker_percent"
                    if self.as_percent and geo_level == "all_geographies"
                    else "person_count"
                ),
                title="External Worker Workplace Location",
                xaxis_title="Workplace Location",
                yaxis_title=(
                    "Workers with External Workplaces (%)"
                    if self.as_percent and geo_level == "all_geographies"
                    else "External Workers"
                ),
                pct_col="pct",
                as_percent=False if geo_level == "all_geographies" else self.as_percent,
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
        geography = str(self.geography_sel.value)
        commuting_flows = self._current_data["commuting_flows"]
        commuting_widget: pn.viewable.Viewable
        if commuting_flows is not None:
            commuting_flows_table = self.get_filtered_view(
                "mandatory_commuting_flows",
                (geo_level, geography),
                factory=lambda: filter_origin_geography(
                    filter_geo_level(commuting_flows, geo_level),
                    geography,
                ),
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
        geo_level = str(self.geo_level_sel.value)
        geography = str(self.geography_sel.value)

        def _distance_view(
            summary_data: list[tuple[str, pl.DataFrame]] | None,
            *,
            cache_key: str,
            title: str,
            yaxis_title: str,
            summary_id: str,
        ) -> pn.viewable.Viewable:
            if summary_data is None:
                return self.data_not_available_card(
                    detail="The selected distance distribution summary is unavailable.",
                    missing_items=[summary_id],
                )
            filtered_summary = self.get_filtered_view(
                cache_key,
                (geo_level, geography),
                factory=lambda: filter_distance_geography(
                    filter_distance_geo_level(summary_data, geo_level),
                    geography,
                ),
            )
            distance_data = self.get_filtered_view(
                f"{cache_key}_chart",
                (geo_level, geography),
                factory=lambda: distance_chart_data(filtered_summary),
            )
            if not any(not df.is_empty() for _, df in distance_data):
                return self.data_not_available_card(
                    detail=f"No distance distribution data is available for geography `{geography}` at level `{geo_level}`.",
                    missing_items=[summary_id],
                )
            return density_chart(
                distance_data,
                x_col="distance_bin",
                y_col="person_count",
                title=title,
                xaxis_title="Distance (miles)",
                yaxis_title=yaxis_title,
                normalize=False,
                as_percent=self.as_percent,
            )

        return [
            pn.pane.Markdown("### Mandatory Location Distance"),
            pn.Row(
                _distance_view(
                    self._current_data["work_distance_summary"],
                    cache_key="mandatory_work_distance_distribution",
                    title="Workplace Location Distance Distribution",
                    yaxis_title="Workplace Locations",
                    summary_id="work_location_distance_distribution_by_geography",
                ),
                _distance_view(
                    self._current_data["school_distance_summary"],
                    cache_key="mandatory_school_distance_distribution",
                    title="School Location Distance Distribution",
                    yaxis_title="School Locations",
                    summary_id="school_location_distance_distribution_by_geography",
                ),
                _distance_view(
                    self._current_data["university_distance_summary"],
                    cache_key="mandatory_university_distance_distribution",
                    title="University Location Distance Distribution",
                    yaxis_title="University Locations",
                    summary_id="university_location_distance_distribution_by_geography",
                ),
                sizing_mode="stretch_width",
            ),
        ]

    def render_remote_work(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        geo_level = str(self.geo_level_sel.value)
        geography = str(self.geography_sel.value)
        wfh_summary = self._current_data["wfh_summary"]
        telecommute = self._current_data["telecommute"]
        remote_views: list[pn.viewable.Viewable] = [pn.pane.Markdown("### Remote Work")]
        remote_row: list[pn.viewable.Viewable] = []
        if wfh_summary is not None:
            wfh_data = self.get_filtered_view(
                "mandatory_wfh",
                (geo_level, geography),
                factory=lambda: wfh_chart_data(
                    wfh_summary,
                    geo_level,
                    geography,
                ),
            )
            wfh_y_col = (
                "work_from_home_percent"
                if self.as_percent
                else "work_from_home_worker_count"
            )
            wfh_yaxis_title = (
                "Workers Working From Home (%)"
                if self.as_percent
                else "Workers Working From Home"
            )
            wfh_title = (
                "Work From Home Rate by Geography"
                if self.as_percent
                else "Workers Working From Home by Geography"
            )
            remote_row.append(
                bar_chart(
                    wfh_data,
                    x_col="geography_label",
                    y_col=wfh_y_col,
                    title=wfh_title,
                    xaxis_title="Geography",
                    yaxis_title=wfh_yaxis_title,
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
            telecommute_level_data = self.get_filtered_view(
                "mandatory_telecommute_level",
                geo_level,
                factory=lambda: filter_geo_level(_nonempty(telecommute), geo_level),
            )
            telecommute_values = ordered_category_values(
                telecommute_level_data,
                "telecommute_frequency",
                category_id="telecommute_frequency",
                config=self.config,
            )
            filtered_telecommute = self.get_filtered_view(
                "mandatory_telecommute",
                (geo_level, geography),
                factory=lambda: filter_geography(
                    telecommute_level_data,
                    geography,
                ),
            )
            telecommute_chart_ready = self.get_filtered_view(
                "mandatory_telecommute_chart",
                (geo_level, geography),
                factory=lambda: telecommute_chart_data(
                    filtered_telecommute,
                    telecommute_values,
                ),
            )
            telecommute_labeled = label_category_data(
                telecommute_chart_ready,
                source_col="telecommute_frequency",
                category_id="telecommute_frequency",
                config=self.config,
                target_col="telecommute_frequency_label",
            )
            remote_row.append(
                bar_chart(
                    telecommute_labeled,
                    x_col="telecommute_frequency_label",
                    y_col="person_count",
                    title="Telecommute Rate",
                    xaxis_title="Telecommute Frequency",
                    yaxis_title="Workers Who Do Not Work From Home",
                    as_percent=self.as_percent,
                    xaxis_categoryarray=self.config.ordered_labels(
                        "telecommute_frequency",
                        telecommute_values,
                    ),
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

    def render_mandatory_distance_table(self) -> SectionContent:
        if self._current_data["mode"] != "ready":
            return []
        geo_level = str(self.geo_level_sel.value)
        geography = str(self.geography_sel.value)
        average_mandatory = self._current_data["average_mandatory_tour_distance"]
        if average_mandatory is None:
            return [
                self.data_not_available_card(
                    detail="The average mandatory tour distance summary is unavailable.",
                    missing_items=[
                        "average_mandatory_tour_distance_by_purpose_and_geography"
                    ],
                )
            ]
        comparison_df = self.get_filtered_view(
            "mandatory_distance_comparison_table",
            (geo_level, geography),
            factory=lambda: mandatory_distance_comparison_table(
                average_mandatory,
                geo_level,
                geography,
                config=self.config,
            ),
        )
        if comparison_df.is_empty():
            return [
                self.data_not_available_card(
                    detail=f"No average mandatory tour distance data is available for geography `{geography}` at level `{geo_level}`.",
                    missing_items=[
                        "average_mandatory_tour_distance_by_purpose_and_geography"
                    ],
                )
            ]
        return [
            data_table(
                [("Comparison", comparison_df)],
                "Average Mandatory Tour Distance vs Base Run",
            )
        ]


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
        "average_mandatory_tour_distance_by_purpose_and_geography",
    ),
)

MandatoryLocationChoicePage.definition = PAGE
