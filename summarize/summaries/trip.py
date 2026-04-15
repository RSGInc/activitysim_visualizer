"""Trip summaries."""

import polars as pl
from runtime.config import Config
from runtime.models import RunData


def trip_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def stop_purpose_by_tour_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    """Stop destination purpose by tour purpose.

    Returns DataFrame: stop_destination_purpose, tour_purpose, stop_count.
    """
    result_schema = {
        "stop_destination_purpose": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "stop_count": pl.Float64,
    }
    # Find a valid non-numeric purpose column if available
    purpose_col = None
    for cand in ("primary_purpose", "tour_type"):
        if cand in rd.trips.columns and not rd.trips[cand].dtype.is_numeric():
            purpose_col = cand
            break

    if "stops" not in rd.trips.columns or "purpose" not in rd.trips.columns:
        return pl.DataFrame(schema=result_schema)

    if purpose_col is None:
        return pl.DataFrame(schema=result_schema)

    return (
        rd.trips.filter(pl.col("stops") == 1)
        .filter(pl.col(purpose_col).is_not_null() & pl.col("purpose").is_not_null())
        .group_by([purpose_col, "purpose"])
        .agg(stop_count=pl.col("finalweight").sum())
        .rename(
            {
                purpose_col: "tour_purpose",
                "purpose": "stop_destination_purpose",
            }
        )
        .select("stop_destination_purpose", "tour_purpose", "stop_count")
        .sort(["tour_purpose", "stop_destination_purpose"])
    )


def trip_mode(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: tour_purpose, tour_mode, trip_mode, trip_count."""
    result_schema = {
        "tour_purpose": pl.Utf8,
        "tour_mode": pl.Utf8,
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
    }
    needed = {"tour_mode", "trip_mode"}
    if not needed.issubset(rd.trips.columns):
        return pl.DataFrame(schema=result_schema)

    # Find a valid non-numeric purpose column if available
    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.trips.columns and not rd.trips[cand].dtype.is_numeric():
            purpose_col = cand
            break

    if purpose_col is None:
        return pl.DataFrame(schema=result_schema)

    base = (
        rd.trips.filter(
            pl.col(purpose_col).is_not_null()
            & pl.col("tour_mode").is_not_null()
            & pl.col("trip_mode").is_not_null()
        )
        .group_by([purpose_col, "tour_mode", "trip_mode"])
        .agg(trip_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
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


def trip_stop_tod(rd: RunData, config: Config) -> pl.DataFrame:
    """Stop and trip departure timing profiles.

    Returns DataFrame: tour_purpose, time_bin, departure_trip_count, departure_stop_count.
    """
    result_schema = {
        "tour_purpose": pl.Utf8,
        "time_bin": pl.Int32,
        "departure_trip_count": pl.Float64,
        "departure_stop_count": pl.Float64,
    }
    # Prefer "depart", fallback to "depart_hour"
    dep_col = None
    if "depart" in rd.trips.columns:
        dep_col = "depart"
    elif "depart_hour" in rd.trips.columns:
        dep_col = "depart_hour"
    else:
        return pl.DataFrame(schema=result_schema)

    if "stops" not in rd.trips.columns:
        return pl.DataFrame(schema=result_schema)

    stops = rd.trips.filter(pl.col("stops") == 1)
    all_trips = rd.trips

    max_period = 48
    try:
        max_period = int(rd.trips[dep_col].max())
    except Exception:
        max_period = 48

    bins = list(range(1, 25 if max_period <= 24 else 49))

    # Find a valid non-numeric purpose column if available
    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.trips.columns and not rd.trips[cand].dtype.is_numeric():
            purpose_col = cand
            break

    if purpose_col is None:
        purposes = {"all_tour_purposes": pl.lit(True)}
    else:
        purpose_list = rd.trips[purpose_col].drop_nulls().unique().sort().to_list()
        purposes = {p: pl.col(purpose_col) == p for p in purpose_list}
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
        pl.DataFrame(rows, schema=result_schema)
        .select(
            "tour_purpose",
            "time_bin",
            "departure_trip_count",
            "departure_stop_count",
        )
        .sort(["tour_purpose", "time_bin"])
    )


def trip_distance(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def stop_ood_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Out-of-direction distance for stops, in 41 bins (0–40 miles).

    Returns DataFrame: distance_bin, tour_purpose, stop_count.
    """
    result_schema = {
        "distance_bin": pl.Int32,
        "tour_purpose": pl.Utf8,
        "stop_count": pl.Float64,
    }
    if "stops" not in rd.trips.columns:
        return pl.DataFrame(schema=result_schema)

    stops = rd.trips.filter(pl.col("stops") == 1)

    if "out_dir_dist" not in stops.columns:
        return pl.DataFrame(schema=result_schema)

    stops2 = stops.with_columns(
        pl.col("out_dir_dist").fill_null(0).clip(0, 999).alias("ood")
    ).with_columns(pl.col("ood").cast(pl.Int32).clip(0, 40).alias("distance_bin"))

    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.trips.columns and not rd.trips[cand].dtype.is_numeric():
            purpose_col = cand
            break

    bins_df = pl.DataFrame(
        {"distance_bin": list(range(0, 41))}, schema={"distance_bin": pl.Int32}
    )

    if purpose_col is None:
        total = (
            stops2.group_by("distance_bin")
            .agg(stop_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
            .select("distance_bin", "tour_purpose", "stop_count")
        )

        return (
            bins_df.with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
            .join(total, on=["distance_bin", "tour_purpose"], how="left")
            .with_columns(pl.col("stop_count").fill_null(0.0))
            .select("distance_bin", "tour_purpose", "stop_count")
            .sort(["distance_bin", "tour_purpose"])
        )

    by_purpose = (
        stops2.filter(pl.col(purpose_col).is_not_null())
        .group_by([purpose_col, "distance_bin"])
        .agg(stop_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
        .select(
            pl.col("distance_bin").cast(pl.Int32),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Float64),
        )
    )

    purposes = (
        stops2.select(pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"))
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
        .sort(["distance_bin", "tour_purpose"])
    )


def parking_location(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()
