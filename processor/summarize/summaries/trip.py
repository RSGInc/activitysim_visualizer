"""Trip summaries."""

import polars as pl
from runtime.config import Config
from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract


@summary_contract(
    schema={
        "trip_purpose": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={"trips": ("trip_purpose", "finalweight")},
)
def trip_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"trip_purpose", "finalweight"}
    if not required.issubset(set(rd.trips.columns)):
        return empty_summary_frame(trip_purpose)

    return (
        rd.trips.filter(pl.col("trip_purpose").is_not_null())
        .group_by("trip_purpose")
        .agg(trip_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("trip_purpose").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
        .select("trip_purpose", "trip_count")
        .sort("trip_purpose")
    )


@summary_contract(
    schema={
        "stop_destination_purpose": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "stop_count": pl.Float64,
    },
    required_columns={
        "trips": ("stops", "tour_purpose", "trip_purpose", "finalweight")
    },
)
def stop_purpose_by_tour_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    """Stop destination purpose by tour purpose.

    Returns DataFrame: stop_destination_purpose, tour_purpose, stop_count.
    """
    required = {"stops", "tour_purpose", "trip_purpose", "finalweight"}
    if not required.issubset(rd.trips.columns):
        return empty_summary_frame(stop_purpose_by_tour_purpose)

    return (
        rd.trips.filter(pl.col("stops") == 1)
        .filter(
            pl.col("tour_purpose").is_not_null() & pl.col("trip_purpose").is_not_null()
        )
        .group_by(["tour_purpose", "trip_purpose"])
        .agg(stop_count=pl.col("finalweight").sum())
        .rename(
            {
                "trip_purpose": "stop_destination_purpose",
            }
        )
        .select("stop_destination_purpose", "tour_purpose", "stop_count")
        .sort(["tour_purpose", "stop_destination_purpose"])
    )


@summary_contract(
    schema={
        "tour_purpose": pl.Utf8,
        "tour_mode": pl.Utf8,
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={
        "trips": ("tour_purpose", "tour_mode", "trip_mode", "finalweight")
    },
)
def trip_mode(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: tour_purpose, tour_mode, trip_mode, trip_count."""
    needed = {"tour_mode", "trip_mode"}
    if not needed.issubset(rd.trips.columns):
        return empty_summary_frame(trip_mode)

    if "tour_purpose" not in rd.trips.columns:
        return empty_summary_frame(trip_mode)

    base = (
        rd.trips.filter(
            pl.col("tour_purpose").is_not_null()
            & pl.col("tour_mode").is_not_null()
            & pl.col("trip_mode").is_not_null()
        )
        .group_by(["tour_purpose", "tour_mode", "trip_mode"])
        .agg(trip_count=pl.col("finalweight").sum())
        .select(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
            pl.col("trip_mode").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
    )

    all_purposes = (
        base.group_by(["tour_mode", "trip_mode"])
        .agg(trip_count=pl.col("trip_count").sum())
        .with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
    )

    all_tour_modes = (
        base.group_by(["tour_purpose", "trip_mode"])
        .agg(trip_count=pl.col("trip_count").sum())
        .with_columns(pl.lit("all_tour_modes").alias("tour_mode"))
        .select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
    )

    grand_total = (
        base.group_by("trip_mode")
        .agg(trip_count=pl.col("trip_count").sum())
        .with_columns(
            pl.lit("all_tour_purposes").alias("tour_purpose"),
            pl.lit("all_tour_modes").alias("tour_mode"),
        )
        .select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
    )

    return (
        pl.concat([base, all_purposes, all_tour_modes, grand_total], how="vertical")
        .select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
        .sort(["tour_purpose", "tour_mode", "trip_mode"])
    )


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
    """Stop and trip departure timing profiles.

    Returns DataFrame: tour_purpose, time_bin, departure_trip_count, departure_stop_count.
    """
    # Prefer "depart", fallback to "depart_hour"
    dep_col = None
    if "depart" in rd.trips.columns:
        dep_col = "depart"
    elif "depart_hour" in rd.trips.columns:
        dep_col = "depart_hour"
    else:
        return empty_summary_frame(trip_stop_tod)

    if "stops" not in rd.trips.columns:
        return empty_summary_frame(trip_stop_tod)

    stops = rd.trips.filter(pl.col("stops") == 1)
    all_trips = rd.trips

    max_period = 48
    try:
        max_period = int(rd.trips[dep_col].max())
    except Exception:
        max_period = 48

    bins = list(range(1, 25 if max_period <= 24 else 49))

    if "tour_purpose" not in rd.trips.columns:
        return empty_summary_frame(trip_stop_tod)

    purpose_list = rd.trips["tour_purpose"].drop_nulls().unique().sort().to_list()
    purposes = {p: pl.col("tour_purpose") == p for p in purpose_list}
    purposes["all_tour_purposes"] = pl.lit(True)

    rows = []
    for purpose_name, filt in purposes.items():
        stop_sub = stops.filter(filt & pl.col(dep_col).is_between(1, bins[-1]))
        trip_sub = all_trips.filter(filt & pl.col(dep_col).is_between(1, bins[-1]))

        stop_counts = stop_sub.group_by(dep_col).agg(
            pl.col("finalweight").sum().alias("departure_stop_count")
        )
        trip_counts = trip_sub.group_by(dep_col).agg(
            pl.col("finalweight").sum().alias("departure_trip_count")
        )

        for tb in bins:
            ns = stop_counts.filter(pl.col(dep_col) == tb)["departure_stop_count"]
            nt = trip_counts.filter(pl.col(dep_col) == tb)["departure_trip_count"]

            rows.append(
                {
                    "tour_purpose": purpose_name,
                    "time_bin": tb,
                    "departure_trip_count": float(nt[0]) if len(nt) > 0 else 0.0,
                    "departure_stop_count": float(ns[0]) if len(ns) > 0 else 0.0,
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

    base = (
        rd.trips.filter(
            pl.col("tour_purpose").is_not_null() & pl.col("od_dist").is_not_null()
        )
        .with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
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

    by_purpose = base.group_by(["distance_bin", "tour_purpose"]).agg(
        trip_count=pl.col("adjusted_weight").sum()
    )

    all_purposes = (
        base.with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .group_by(["distance_bin", "tour_purpose"])
        .agg(trip_count=pl.col("adjusted_weight").sum())
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
    """Out-of-direction distance for stops, in 41 bins (0–40 miles).

    Returns DataFrame: distance_bin, tour_purpose, stop_count.
    """
    if "stops" not in rd.trips.columns:
        return empty_summary_frame(stop_ood_distance)

    stops = rd.trips.filter(pl.col("stops") == 1)

    if "out_dir_dist" not in stops.columns:
        return empty_summary_frame(stop_ood_distance)

    stops2 = stops.with_columns(
        pl.col("out_dir_dist").fill_null(0).clip(0, 999).alias("ood")
    ).with_columns(pl.col("ood").cast(pl.Int32).clip(0, 40).alias("distance_bin"))

    bins_df = pl.DataFrame(
        {"distance_bin": list(range(0, 41))}, schema={"distance_bin": pl.Int32}
    )

    if "tour_purpose" not in stops2.columns:
        return empty_summary_frame(stop_ood_distance)

    by_purpose = (
        stops2.filter(pl.col("tour_purpose").is_not_null())
        .group_by(["tour_purpose", "distance_bin"])
        .agg(stop_count=pl.col("finalweight").sum())
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

    dense_by_purpose = (
        bins_df.join(purposes, how="cross")
        .join(by_purpose, on=["distance_bin", "tour_purpose"], how="left")
        .with_columns(pl.col("stop_count").fill_null(0.0))
        .select(
            pl.col("distance_bin").cast(pl.Int32),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Float64),
        )
    )

    total = (
        stops2.group_by("distance_bin")
        .agg(stop_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .select(
            pl.col("distance_bin").cast(pl.Int32),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Float64),
        )
    )

    dense_total = (
        bins_df.with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .join(total, on=["distance_bin", "tour_purpose"], how="left")
        .with_columns(pl.col("stop_count").fill_null(0.0))
    )

    return (
        pl.concat([dense_by_purpose, dense_total], how="vertical")
        .select("distance_bin", "tour_purpose", "stop_count")
        .sort(["tour_purpose", "distance_bin"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={"trips": ("parking_zone", "finalweight")},
)
def parking_locations(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"parking_zone", "finalweight"}
    if not required.issubset(set(rd.trips.columns)):
        return empty_summary_frame(parking_locations)

    def aggregate_counts(
        df: pl.DataFrame,
        geography_type: str,
        geography_id_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by(geography_id_col)
            .agg(trip_count=pl.col("finalweight").sum())
            .rename({geography_id_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("trip_count").cast(pl.Float64),
            )
            .select("geography_type", "geography_id", "trip_count")
        )

    base = rd.trips.filter(
        pl.col("parking_zone").is_not_null()
        & (pl.col("parking_zone").cast(pl.Int64, strict=False) > 0)
    ).select("parking_zone", "finalweight")

    if base.is_empty():
        return empty_summary_frame(parking_locations)

    outputs = [
        aggregate_counts(
            base,
            geography_type="maz",
            geography_id_col="parking_zone",
        )
    ]

    # TODO: Adapt this block to existing geography lookup helper pattern.
    # Example expected pattern:
    #
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.parking_maz_geography_lookups():
    #         # lookup_df maps parking MAZ -> geography_id
    #         geo_df = (
    #             base.join(
    #                 lookup_df,
    #                 left_on="parking_zone",
    #                 right_on="MAZ",
    #                 how="inner",
    #             )
    #             .pipe(aggregate_counts, geography_type, "geography_id")
    #         )
    #         outputs.append(geo_df)

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
        .select("geography_type", "geography_id", "trip_count")
        .sort(["geography_type", "geography_id"])
    )
