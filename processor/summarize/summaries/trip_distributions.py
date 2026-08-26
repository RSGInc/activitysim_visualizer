"""Distribution-style trip summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    ALL_TOUR_PURPOSES,
    _all_purpose_rollup as _all_tour_purpose_rollup,
    _dense_zero_fill,
    _distance_bin_expr,
    _distance_bin_labels,
    _distance_bin_sort_expr,
    _summary_purpose_column as _trip_purpose_column,
    weighted_group_sum,
)
from runtime.config import Config


@summary(
    id="trip_departure_time_by_purpose",
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
        return trip_stop_tod.empty()

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return trip_stop_tod.empty()

    all_trips = rd.trips.with_columns(
        pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose")
    )
    if "tour_purpose" not in all_trips.columns:
        return trip_stop_tod.empty()

    stops = all_trips.filter(pl.col("stops") == 1)
    bins = _departure_bins(all_trips, dep_col)
    if not bins:
        return trip_stop_tod.empty()

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
        stop_sub = stops.filter(
            purpose_filter & pl.col(dep_col).is_between(1, bins[-1])
        )
        trip_sub = all_trips.filter(
            purpose_filter & pl.col(dep_col).is_between(1, bins[-1])
        )

        stop_counts = weighted_group_sum(
            stop_sub,
            dep_col,
            weight_col="finalweight",
            output_col="departure_stop_count",
        )
        trip_counts = weighted_group_sum(
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


@summary(
    id="trip_distance_by_purpose",
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
        return trip_distance.empty()

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return trip_distance.empty()

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
        )
        .with_columns(_distance_bin_expr("od_dist"))
        .filter(pl.col("distance_bin").is_not_null())
    )

    by_purpose = weighted_group_sum(
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
            _distance_bin_sort_expr().alias("_sort_distance"),
        )
        .select("distance_bin", "tour_purpose", "trip_count", "_sort_distance")
        .sort(["_sort_distance", "tour_purpose"])
        .select("distance_bin", "tour_purpose", "trip_count")
    )


@summary(
    id="stop_out_of_direction_distance_by_tour_purpose",
    schema={
        "distance_bin": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "stop_count": pl.Float64,
    },
    required_columns={
        "trips": ("stops", "out_dir_dist", "tour_purpose", "finalweight")
    },
)
def stop_ood_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Out-of-direction distance for stops, with exact-zero and 40+ bins."""
    if "stops" not in rd.trips.columns:
        return stop_ood_distance.empty()

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return stop_ood_distance.empty()

    stops = rd.trips.filter(pl.col("stops") == 1)
    if "out_dir_dist" not in stops.columns:
        return stop_ood_distance.empty()

    stops2 = (
        stops.filter(pl.col("out_dir_dist").is_not_null())
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            _distance_bin_expr("out_dir_dist"),
        )
        .filter(pl.col("distance_bin").is_not_null())
    )

    if "tour_purpose" not in stops2.columns or stops2.is_empty():
        return stop_ood_distance.empty()

    bins_df = pl.DataFrame(
        {"distance_bin": _distance_bin_labels()}, schema={"distance_bin": pl.Utf8}
    )
    by_purpose = weighted_group_sum(
        stops2.filter(pl.col("tour_purpose").is_not_null()),
        ["tour_purpose", "distance_bin"],
        weight_col="finalweight",
        output_col="stop_count",
    ).select(
        pl.col("distance_bin").cast(pl.Utf8),
        pl.col("tour_purpose").cast(pl.Utf8),
        pl.col("stop_count").cast(pl.Float64),
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
        pl.col("distance_bin").cast(pl.Utf8),
        pl.col("tour_purpose").cast(pl.Utf8),
        pl.col("stop_count").cast(pl.Float64),
    )

    total = (
        weighted_group_sum(
            stops2,
            "distance_bin",
            weight_col="finalweight",
            output_col="stop_count",
        )
        .with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
        .select(
            pl.col("distance_bin").cast(pl.Utf8),
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
        .with_columns(_distance_bin_sort_expr().alias("_sort_distance"))
        .sort(["tour_purpose", "_sort_distance"])
        .select("distance_bin", "tour_purpose", "stop_count")
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
