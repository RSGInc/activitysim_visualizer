"""Stop frequency, purpose, location, and timing summaries."""

from __future__ import annotations

import polars as pl

from ..models import RunData


def stop_freq(rd: RunData) -> pl.DataFrame:
    """Stop frequency by tour purpose for outbound, inbound, and total stops."""
    needed = {"primary_purpose", "num_ob_stops", "num_ib_stops", "num_tot_stops"}
    if not needed.issubset(rd.tours.columns):
        return pl.DataFrame()

    all_tours = rd.tours.filter(pl.col("tour_category").is_not_null())
    return (
        all_tours.with_columns(
            [
                pl.col("num_ob_stops").clip(0, 3).alias("ob_stops"),
                pl.col("num_ib_stops").clip(0, 3).alias("ib_stops"),
                pl.col("num_tot_stops").clip(0, 6).alias("tot_stops"),
            ]
        )
        .group_by(["primary_purpose", "ob_stops", "ib_stops", "tot_stops"])
        .agg(pl.col("finalweight").sum().alias("freq"))
    )


def stop_purpose_by_tour_purpose(rd: RunData) -> pl.DataFrame:
    """Stop destination purpose by tour purpose."""
    if "stops" not in rd.trips.columns or "purpose" not in rd.trips.columns or "primary_purpose" not in rd.trips.columns:
        return pl.DataFrame()

    stops_df = rd.trips.filter(pl.col("stops") == 1)
    return (
        stops_df.filter(pl.col("primary_purpose").is_not_null() & pl.col("purpose").is_not_null())
        .group_by(["primary_purpose", "purpose"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(["primary_purpose", "purpose"])
    )


def stop_location(rd: RunData) -> pl.DataFrame:
    """Out-of-direction distance distribution for stops in 0-40 mile bins."""
    if "stops" not in rd.trips.columns or "out_dir_dist" not in rd.trips.columns:
        return pl.DataFrame()

    stops_df = (
        rd.trips.filter(pl.col("stops") == 1)
        .with_columns(pl.col("out_dir_dist").clip(0, 999).alias("ood"))
        .with_columns(pl.col("ood").cast(pl.Int32).clip(0, 40).alias("distbin"))
    )

    bins = list(range(0, 41))
    if "primary_purpose" not in stops_df.columns:
        counts = stops_df.group_by("distbin").agg(pl.col("finalweight").sum().alias("n"))
        result = pl.DataFrame({"distbin": bins}).join(counts, on="distbin", how="left").fill_null(0)
        return result.with_columns(pl.lit("Total").alias("primary_purpose"))

    purposes = stops_df["primary_purpose"].drop_nulls().unique().to_list()
    rows: list[dict[str, object]] = []
    for purpose in purposes:
        subset = stops_df.filter(pl.col("primary_purpose") == purpose)
        counts = subset.group_by("distbin").agg(pl.col("finalweight").sum().alias("n"))
        for distbin in bins:
            n_row = counts.filter(pl.col("distbin") == distbin)["n"]
            rows.append({"distbin": distbin, "primary_purpose": purpose, "freq": float(n_row[0]) if len(n_row) > 0 else 0.0})
    return pl.DataFrame(rows)


def stop_timing(rd: RunData) -> pl.DataFrame:
    """Stop and trip departure timing profiles by purpose."""
    if "stops" not in rd.trips.columns or "depart_hour" not in rd.trips.columns:
        return pl.DataFrame()

    stops_df = rd.trips.filter(pl.col("stops") == 1)
    all_trips = rd.trips
    max_period = 48
    if "depart_hour" in rd.trips.columns:
        try:
            max_period = int(rd.trips["depart_hour"].max())
        except Exception:
            max_period = 48
    bins = list(range(1, 25 if max_period <= 24 else 49))

    if "primary_purpose" not in rd.trips.columns:
        purposes = {"Total": pl.lit(True)}
    else:
        purpose_list = rd.trips["primary_purpose"].drop_nulls().unique().sort().to_list()
        purposes = {purpose: pl.col("primary_purpose") == purpose for purpose in purpose_list}
        purposes["Total"] = pl.lit(True)

    rows: list[dict[str, object]] = []
    for purpose_name, filt in purposes.items():
        stop_subset = stops_df.filter(filt & pl.col("depart_hour").is_between(1, bins[-1]))
        trip_subset = all_trips.filter(filt & pl.col("depart_hour").is_between(1, bins[-1]))
        stop_counts = stop_subset.group_by("depart_hour").agg(pl.col("finalweight").sum().alias("n_stop"))
        trip_counts = trip_subset.group_by("depart_hour").agg(pl.col("finalweight").sum().alias("n_trip"))
        for timebin in bins:
            stop_row = stop_counts.filter(pl.col("depart_hour") == timebin)["n_stop"]
            trip_row = trip_counts.filter(pl.col("depart_hour") == timebin)["n_trip"]
            rows.append(
                {
                    "timebin": timebin,
                    "primary_purpose": purpose_name,
                    "freq_stop_dep": float(stop_row[0]) if len(stop_row) > 0 else 0.0,
                    "freq_trip_dep": float(trip_row[0]) if len(trip_row) > 0 else 0.0,
                }
            )
    return pl.DataFrame(rows)
