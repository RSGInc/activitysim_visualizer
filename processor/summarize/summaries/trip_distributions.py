"""Distribution-style trip summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.trip_helpers import (
    ALL_TOUR_PURPOSES,
    _all_tour_purpose_rollup,
    _dense_zero_fill,
    _trip_purpose_column,
    _weighted_group_sum,
)
from runtime.config import Config


@summary_contract(
    schema={
        "tour_purpose": pl.Utf8,
        "time_bin": pl.Int32,
        "departure_trip_count": pl.Float64,
        "departure_stop_count": pl.Float64,
    },
    required_columns={"trips": ("tour_purpose", "stops", "finalweight")},
)
def trip_stop_tod(rd: RunData, config: Config) -> pl.DataFrame:
    """Stop and trip departure timing profiles."""
    dep_col = _departure_time_column(rd.trips)
    if dep_col is None or "stops" not in rd.trips.columns:
        return empty_summary_frame(trip_stop_tod)

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return empty_summary_frame(trip_stop_tod)

    all_trips = rd.trips.with_columns(
        pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose")
    )
    if "tour_purpose" not in all_trips.columns:
        return empty_summary_frame(trip_stop_tod)

    stops = all_trips.filter(pl.col("stops") == 1)
    bins = _departure_bins(all_trips, dep_col)
    if not bins:
        return empty_summary_frame(trip_stop_tod)

    purpose_values = (
        all_trips.select(pl.col("tour_purpose"))
        .drop_nulls()
        .unique()
        .sort("tour_purpose")
        .to_series()
        .to_list()
    )

    rows: list[dict[str, object]] = []
    purpose_names = [*purpose_values, ALL_TOUR_PURPOSES]
    for purpose_name in purpose_names:
        purpose_filter = (
            pl.lit(True)
            if purpose_name == ALL_TOUR_PURPOSES
            else pl.col("tour_purpose") == purpose_name
        )
        stop_sub = stops.filter(purpose_filter & pl.col(dep_col).is_between(1, bins[-1]))
        trip_sub = all_trips.filter(
            purpose_filter & pl.col(dep_col).is_between(1, bins[-1])
        )

        stop_counts = _weighted_group_sum(
            stop_sub,
            dep_col,
            weight_col="finalweight",
            output_col="departure_stop_count",
        )
        trip_counts = _weighted_group_sum(
            trip_sub,
            dep_col,
            weight_col="finalweight",
            output_col="departure_trip_count",
        )

        for time_bin in bins:
            stop_values = stop_counts.filter(pl.col(dep_col) == time_bin)[
                "departure_stop_count"
            ]
            trip_values = trip_counts.filter(pl.col(dep_col) == time_bin)[
                "departure_trip_count"
            ]
            rows.append(
                {
                    "tour_purpose": purpose_name,
                    "time_bin": time_bin,
                    "departure_trip_count": float(trip_values[0])
                    if len(trip_values) > 0
                    else 0.0,
                    "departure_stop_count": float(stop_values[0])
                    if len(stop_values) > 0
                    else 0.0,
                }
            )

    return (
        pl.DataFrame(
            rows,
            schema={
                "tour_purpose": pl.Utf8,
                "time_bin": pl.Int32,
                "departure_trip_count": pl.Float64,
                "departure_stop_count": pl.Float64,
            },
        )
        .select(
            "tour_purpose",
            "time_bin",
            "departure_trip_count",
            "departure_stop_count",
        )
        .sort(["tour_purpose", "time_bin"])
    )


@summary_contract(
    schema={
        "distance_bin": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={
        "trips": ("tour_purpose", "od_dist", "num_participants", "finalweight")
    },
)
def trip_distance(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "tour_purpose",
        "od_dist",
        "num_participants",
        "finalweight",
    }
    if not required.issubset(set(rd.trips.columns)):
        return empty_summary_frame(trip_distance)

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return empty_summary_frame(trip_distance)

    base = (
        rd.trips.filter(
            pl.col(purpose_col).is_not_null() & pl.col("od_dist").is_not_null()
        )
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            (
                pl.col("finalweight")
                * pl.coalesce(
                    [pl.col("num_participants").cast(pl.Float64), pl.lit(1.0)]
                )
            ).alias("adjusted_weight"),
            pl.col("od_dist").cast(pl.Float64).round(0).alias("distance_miles_rounded"),
        )
        .with_columns(
            pl.when(pl.col("distance_miles_rounded") >= 40)
            .then(pl.lit("40+"))
            .otherwise(
                pl.col("distance_miles_rounded")
                .cast(pl.Int64, strict=False)
                .cast(pl.Utf8)
            )
            .alias("distance_bin")
        )
    )

    by_purpose = _weighted_group_sum(
        base,
        ["distance_bin", "tour_purpose"],
        weight_col="adjusted_weight",
        output_col="trip_count",
    )
    all_purposes = _all_tour_purpose_rollup(
        by_purpose,
        group_cols=["distance_bin"],
        value_col="trip_count",
    )

    return (
        pl.concat([by_purpose, all_purposes], how="vertical")
        .with_columns(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
            pl.when(pl.col("distance_bin") == "40+")
            .then(999)
            .otherwise(pl.col("distance_bin").cast(pl.Int64, strict=False))
            .alias("_sort_distance"),
        )
        .select("distance_bin", "tour_purpose", "trip_count", "_sort_distance")
        .sort(["_sort_distance", "tour_purpose"])
        .select("distance_bin", "tour_purpose", "trip_count")
    )


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "tour_purpose": pl.Utf8,
        "stop_count": pl.Float64,
    },
    required_columns={
        "trips": ("stops", "out_dir_dist", "tour_purpose", "finalweight")
    },
)
def stop_ood_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Out-of-direction distance for stops, in 41 bins (0-40 miles)."""
    if "stops" not in rd.trips.columns:
        return empty_summary_frame(stop_ood_distance)

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return empty_summary_frame(stop_ood_distance)

    stops = rd.trips.filter(pl.col("stops") == 1)
    if "out_dir_dist" not in stops.columns:
        return empty_summary_frame(stop_ood_distance)

    stops2 = stops.with_columns(
        pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
        pl.col("out_dir_dist").fill_null(0).clip(0, 999).alias("ood"),
    ).with_columns(pl.col("ood").cast(pl.Int32).clip(0, 40).alias("distance_bin"))

    if "tour_purpose" not in stops2.columns:
        return empty_summary_frame(stop_ood_distance)

    bins_df = pl.DataFrame(
        {"distance_bin": list(range(0, 41))}, schema={"distance_bin": pl.Int32}
    )
    by_purpose = (
        _weighted_group_sum(
            stops2.filter(pl.col("tour_purpose").is_not_null()),
            ["tour_purpose", "distance_bin"],
            weight_col="finalweight",
            output_col="stop_count",
        )
        .select(
            pl.col("distance_bin").cast(pl.Int32),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Float64),
        )
    )

    purposes = (
        stops2.select(pl.col("tour_purpose").cast(pl.Utf8).alias("tour_purpose"))
        .drop_nulls()
        .unique()
        .sort("tour_purpose")
    )
    dense_by_purpose = _dense_zero_fill(
        bins_df=bins_df,
        groups_df=purposes,
        counts_df=by_purpose,
        join_cols=["distance_bin", "tour_purpose"],
        value_col="stop_count",
    ).select(
        pl.col("distance_bin").cast(pl.Int32),
        pl.col("tour_purpose").cast(pl.Utf8),
        pl.col("stop_count").cast(pl.Float64),
    )

    total = (
        _weighted_group_sum(
            stops2,
            "distance_bin",
            weight_col="finalweight",
            output_col="stop_count",
        )
        .with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
        .select(
            pl.col("distance_bin").cast(pl.Int32),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Float64),
        )
    )
    dense_total = (
        bins_df.with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
        .join(total, on=["distance_bin", "tour_purpose"], how="left")
        .with_columns(pl.col("stop_count").fill_null(0.0))
    )

    return (
        pl.concat([dense_by_purpose, dense_total], how="vertical")
        .select("distance_bin", "tour_purpose", "stop_count")
        .sort(["tour_purpose", "distance_bin"])
    )


def _departure_time_column(trips: pl.DataFrame) -> str | None:
    """Return the preferred departure-time column name when available."""
    if "depart" in trips.columns:
        return "depart"
    if "depart_hour" in trips.columns:
        return "depart_hour"
    return None


def _departure_bins(trips: pl.DataFrame, dep_col: str) -> list[int]:
    max_period = 48
    try:
        max_period = int(trips[dep_col].max())
    except Exception:
        max_period = 48
    return list(range(1, 25 if max_period <= 24 else 49))
