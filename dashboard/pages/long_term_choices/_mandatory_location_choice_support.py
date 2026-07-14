"""Page-local support helpers for the mandatory location choice page.

These transforms encode page-specific semantics that do not belong in the
cross-page helper modules, while still keeping the main page controller small
and readable.
"""

from __future__ import annotations

import polars as pl

from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    cap_numeric_category_frame,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.helpers.comparison_helpers import (
    build_ab_comparison_row,
    build_ab_comparison_table,
    weighted_average_lookup,
)
from dashboard.helpers.geography_helpers import (
    DEFAULT_GEO_COL,
    DEFAULT_GEO_LEVEL_COL,
    ALL_WITHIN_LEVEL_VALUE,
    AGGREGATE_GEOGRAPHY_LEVEL,
    filter_geography,
    filter_geography_level,
    is_all_geographies,
    normalize_geography_data,
    rename_present,
)
from runtime.config import Config


def adapt_external_workplace(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Normalize workplace summaries onto the page's chart-ready schema."""

    def normalize(frame: pl.DataFrame) -> pl.DataFrame:
        normalized = frame
        if (
            DEFAULT_GEO_COL in normalized.columns
            and "workplace_location" not in normalized.columns
        ):
            normalized = normalized.with_columns(
                pl.col(DEFAULT_GEO_COL).alias("workplace_location")
            )
        return rename_present(
            normalized,
            {"external_worker_count": "person_count"},
        )

    return RunTables.from_runs(normalize_geography_data(data_list)).map(normalize)


def adapt_commuting_flows(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Normalize commuting-flow geography column names used by this page."""
    return RunTables.from_runs(data_list).map(
        lambda frame: rename_present(
            frame,
            {
                "origin_geography_type": "origin_geography_level",
                "destination_geography_type": "destination_geography_level",
            },
        )
    )


def external_workplace_percent_data(
    external_workplace: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Compute percent-of-all-workers values for the all-geographies aggregate view."""
    if is_all_geographies(geo_level):
        geo_level = AGGREGATE_GEOGRAPHY_LEVEL
    if geo_level != AGGREGATE_GEOGRAPHY_LEVEL:
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
    if is_all_geographies(geography_level):
        geography_level = AGGREGATE_GEOGRAPHY_LEVEL
    if is_all_geographies(geography):
        geography = AGGREGATE_GEOGRAPHY_LEVEL

    def prepare(frame: pl.DataFrame) -> pl.DataFrame:
        return (
            frame.with_columns(
                pl.col(DEFAULT_GEO_LEVEL_COL).cast(pl.Utf8),
                pl.col(DEFAULT_GEO_COL).cast(pl.Utf8),
            )
            .filter(pl.col(DEFAULT_GEO_LEVEL_COL) == geography_level)
            .pipe(
                lambda frame: (
                    frame
                    if geography in {ALL_WITHIN_LEVEL_VALUE, "Total", "All"}
                    else frame.filter(pl.col(DEFAULT_GEO_COL) == geography)
                )
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

    return RunTables.from_runs(wfh_list).map(prepare)


def distance_distribution_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate geography-sliced distance summaries into distance-bin distributions."""
    return (
        RunTables.from_runs(data_list)
        .requiring("person_count", "distance_bin")
        .map(
            lambda frame: cap_numeric_category_frame(
                frame.group_by("distance_bin").agg(
                    person_count=pl.col("person_count").sum()
                ),
                category="distance_bin",
                cap_value=40,
                value_cols=("person_count",),
            )
        )
    )


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

    def complete(frame: pl.DataFrame) -> pl.DataFrame:
        aggregated = (
            frame.with_columns(pl.col("telecommute_frequency").cast(pl.Utf8))
            .group_by("telecommute_frequency")
            .agg(person_count=pl.col("person_count").sum())
        )
        return scaffold.join(
            aggregated, on="telecommute_frequency", how="left"
        ).with_columns(pl.col("person_count").fill_null(0.0).cast(pl.Float64))

    completed = (
        RunTables.from_runs(data_list)
        .requiring("telecommute_frequency", "person_count")
        .map(complete)
    )

    return label_category_data(
        completed,
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
) -> list[tuple[str, pl.DataFrame]]:
    """Compare average mandatory tour distances against the base run."""
    filtered = filter_geography(
        filter_geography_level(data_list, geography_level),
        geography,
    )
    runs = nonempty(filtered)
    if not runs:
        return []

    purpose_values = ordered_category_values(
        runs,
        "mandatory_tour_purpose",
        category_id="tour_purpose",
        config=config,
    )
    if not purpose_values:
        return []

    _, base_run_df = runs[0]
    base_lookup = weighted_average_lookup(
        base_run_df,
        category="mandatory_tour_purpose",
        average_col="average_tour_distance",
        weight_col="person_count",
    )
    quantity_a_column = "Average Mandatory Tour Distance"
    quantity_b_column = "Base Run Average Mandatory Tour Distance"
    out: list[tuple[str, pl.DataFrame]] = []
    for run_label, run_df in runs:
        lookup = weighted_average_lookup(
            run_df,
            category="mandatory_tour_purpose",
            average_col="average_tour_distance",
            weight_col="person_count",
        )
        rows = []
        for raw_purpose in purpose_values:
            display_purpose = config.label_value("tour_purpose", raw_purpose)
            rows.append(
                build_ab_comparison_row(
                    keys={"Mandatory Tour Purpose": display_purpose},
                    quantity_a=lookup.get(str(raw_purpose)),
                    quantity_b=base_lookup.get(str(raw_purpose)),
                    quantity_a_column=quantity_a_column,
                    quantity_b_column=quantity_b_column,
                )
            )

        table = build_ab_comparison_table(
            rows,
            key_columns=["Mandatory Tour Purpose"],
            quantity_a_column=quantity_a_column,
            quantity_b_column=quantity_b_column,
        )
        if not table.is_empty():
            out.append((run_label, table))
    return out


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
