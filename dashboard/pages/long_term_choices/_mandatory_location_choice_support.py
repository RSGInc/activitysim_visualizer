"""Page-local support helpers for the mandatory location choice page.

These transforms encode page-specific semantics that do not belong in the
cross-page helper modules, while still keeping the main page controller small
and readable.
"""

from __future__ import annotations

import polars as pl

from dashboard.helpers.category_helpers import (
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.helpers.comparison_helpers import (
    build_base_run_percent_difference_table,
    weighted_average_lookup,
)
from dashboard.helpers.geography_helpers import (
    DEFAULT_GEO_COL,
    DEFAULT_GEO_LEVEL_COL,
    ALL_WITHIN_LEVEL_VALUE,
    filter_geography,
    filter_geography_level,
    normalize_geography_data,
    rename_present,
)
from runtime.config import Config


def adapt_external_workplace(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Normalize workplace summaries onto the page's chart-ready schema."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in normalize_geography_data(data_list):
        normalized = df
        if DEFAULT_GEO_COL in normalized.columns and "workplace_location" not in normalized.columns:
            normalized = normalized.with_columns(
                pl.col(DEFAULT_GEO_COL).alias("workplace_location")
            )
        normalized = rename_present(
            normalized,
            {"external_worker_count": "person_count"},
        )
        out.append((label, normalized))
    return out


def adapt_commuting_flows(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Normalize commuting-flow geography column names used by this page."""
    if not data_list:
        return []
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        out.append(
            (
                label,
                rename_present(
                    df,
                    {
                        "origin_geography_type": "origin_geography_level",
                        "destination_geography_type": "destination_geography_level",
                    },
                ),
            )
        )
    return out


def external_workplace_percent_data(
    external_workplace: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Compute percent-of-all-workers values for the all-geographies aggregate view."""
    if geo_level != "all_geographies":
        return external_workplace

    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(external_workplace):
        if "all_worker_count" not in df.columns:
            out.append((label, df))
            continue
        denominator = float(df["all_worker_count"][0] or 0.0)
        if denominator <= 0:
            out.append((label, df))
            continue
        out.append(
            (
                label,
                df.with_columns(
                    (
                        pl.col("person_count").cast(pl.Float64) / denominator * 100.0
                    ).alias("external_worker_percent")
                ),
            )
        )
    return out


def work_from_home_chart_data(
    wfh_list: list[tuple[str, pl.DataFrame]],
    geography_level: str,
    geography: str = ALL_WITHIN_LEVEL_VALUE,
) -> list[tuple[str, pl.DataFrame]]:
    """Prepare work-from-home counts and rates for the selected geography slice."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(wfh_list):
        chart_df = (
            df.with_columns(
                pl.col(DEFAULT_GEO_LEVEL_COL).cast(pl.Utf8),
                pl.col(DEFAULT_GEO_COL).cast(pl.Utf8),
            )
            .filter(pl.col(DEFAULT_GEO_LEVEL_COL) == geography_level)
            .pipe(
                lambda frame: frame
                if geography in {ALL_WITHIN_LEVEL_VALUE, "Total", "All"}
                else frame.filter(pl.col(DEFAULT_GEO_COL) == geography)
            )
            .with_columns(
                pl.when(pl.col("worker_count") > 0)
                .then(
                    pl.col("work_from_home_worker_count")
                    / pl.col("worker_count")
                    * 100.0
                )
                .otherwise(0.0)
                .alias("work_from_home_percent"),
                pl.when(pl.col(DEFAULT_GEO_COL) == "all_geographies")
                .then(pl.lit("All Geographies"))
                .otherwise(pl.col(DEFAULT_GEO_COL))
                .alias("geography_label"),
            )
            .sort("geography_label")
        )
        out.append((label, chart_df))
    return out


def distance_distribution_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate geography-sliced distance summaries into distance-bin distributions."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        if "person_count" not in df.columns or "distance_bin" not in df.columns:
            continue
        out.append(
            (
                label,
                df.group_by("distance_bin")
                .agg(person_count=pl.col("person_count").sum())
                .sort("distance_bin"),
            )
        )
    return out


def telecommute_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    telecommute_values: list[str],
    *,
    config: Config,
) -> list[tuple[str, pl.DataFrame]]:
    """Complete and label telecommute categories so runs share one x-axis."""
    if not telecommute_values:
        return []

    scaffold = pl.DataFrame(
        {"telecommute_frequency": telecommute_values},
        schema={"telecommute_frequency": pl.Utf8},
    )
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
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

    return label_category_data(
        out,
        source_col="telecommute_frequency",
        category_id="telecommute_frequency",
        config=config,
        target_col="telecommute_frequency_label",
    )


def mandatory_distance_comparison_table(
    data_list: list[tuple[str, pl.DataFrame]],
    geography_level: str,
    geography: str,
    *,
    config: Config,
) -> pl.DataFrame:
    """Compare average mandatory tour distances against the base run."""
    filtered = filter_geography(
        filter_geography_level(data_list, geography_level),
        geography,
    )
    runs = nonempty(filtered)
    if not runs:
        return pl.DataFrame()

    purpose_values = ordered_category_values(
        runs,
        "mandatory_tour_purpose",
        category_id="tour_purpose",
        config=config,
    )
    if not purpose_values:
        return pl.DataFrame()

    run_labels = [label for label, _ in runs]
    base_run_label = run_labels[0]
    row_values: dict[str, dict[str, float | None]] = {}
    for raw_purpose in purpose_values:
        display_purpose = config.label_value("tour_purpose", raw_purpose)
        row_values[display_purpose] = {}
        for run_label, run_df in runs:
            lookup = weighted_average_lookup(
                run_df,
                category_col="mandatory_tour_purpose",
                average_col="average_tour_distance",
                weight_col="person_count",
            )
            row_values[display_purpose][run_label] = lookup.get(str(raw_purpose))

    return build_base_run_percent_difference_table(
        run_labels=run_labels,
        base_run_label=base_run_label,
        row_header="Mandatory Tour Purpose",
        row_values=row_values,
    )


def selected_telecommute_values(
    telecommute_data: list[tuple[str, pl.DataFrame]],
    *,
    config: Config,
) -> list[str]:
    """Return config-ordered telecommute categories for the current run slice."""
    return ordered_category_values(
        telecommute_data,
        "telecommute_frequency",
        category_id="telecommute_frequency",
        config=config,
    )


def filter_selected_geography(
    data_list: list[tuple[str, pl.DataFrame]],
    geography_level: str,
    geography: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Apply the page's standard level-then-geography filter order."""
    return filter_geography(
        filter_geography_level(data_list, geography_level),
        geography,
    )
