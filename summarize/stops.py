"""Stop frequency, purpose, location, and timing summaries."""

import polars as pl
from runtime.config import Config
from runtime.models import RunData


def stop_freq(rd: RunData) -> pl.DataFrame:
    """Stop frequency by tour purpose (outbound, inbound, total).

    Columns: purpose, ob_stops (0-3+), ib_stops (0-3+), tot_stops (0-6+), freq.
    """
    if "tour_purpose" not in rd.tours.columns:
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
        .group_by(["tour_purpose", "ob_stops", "ib_stops", "tot_stops"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .rename({"tour_purpose": "purpose"})
    )


def stop_purpose_by_tour_purpose(rd: RunData) -> pl.DataFrame:
    """Stop destination purpose by tour purpose.

    Columns: tour_purpose, stop_purpose, freq.
    """
    needed = {"stops", "tour_purpose", "trip_purpose"}
    if not needed.issubset(rd.trips.columns):
        return pl.DataFrame()

    stops = rd.trips.filter(pl.col("stops") == 1)
    return (
        stops.filter(
            pl.col("tour_purpose").is_not_null() & pl.col("trip_purpose").is_not_null()
        )
        .group_by(["tour_purpose", "trip_purpose"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(["tour_purpose", "trip_purpose"])
        .rename({"trip_purpose": "stop_purpose"})
    )


def stop_location(rd: RunData) -> pl.DataFrame:
    """Out-of-direction distance for stops, in 41 bins (0–40 miles).

    Columns: distbin (0-40), purpose, freq.
    """
    if "stops" not in rd.trips.columns:
        return pl.DataFrame()

    stops = rd.trips.filter(pl.col("stops") == 1)
    stops2 = stops.with_columns(
        pl.col("out_dir_dist").clip(0, 999).alias("ood")
    ).with_columns(pl.col("ood").cast(pl.Int32).clip(0, 40).alias("distbin"))

    bins = list(range(0, 41))
    if "tour_purpose" not in stops2.columns:
        counts = stops2.group_by("distbin").agg(pl.col("finalweight").sum().alias("n"))
        base = pl.DataFrame({"distbin": bins})
        result = base.join(counts, on="distbin", how="left").fill_null(0)
        return (
            result.with_columns(pl.lit("Total").alias("purpose"))
            .rename({"n": "freq"})
            .select(["distbin", "purpose", "freq"])
        )

    purposes = stops2["tour_purpose"].drop_nulls().unique().to_list()
    rows = []
    for purp in purposes:
        sub = stops2.filter(pl.col("tour_purpose") == purp)
        counts = sub.group_by("distbin").agg(pl.col("finalweight").sum().alias("n"))
        for db in bins:
            n_row = counts.filter(pl.col("distbin") == db)["n"]
            rows.append(
                {
                    "distbin": db,
                    "purpose": purp,
                    "freq": float(n_row[0]) if len(n_row) > 0 else 0.0,
                }
            )
    return pl.DataFrame(rows)


def stop_timing(rd: RunData) -> pl.DataFrame:
    """Stop and trip departure timing profiles.

    Columns: timebin, purpose, freq_stop_dep, freq_trip_dep.
    """
    dep_col = "depart_hour"
    if dep_col not in rd.trips.columns:
        return pl.DataFrame()

    if "stops" not in rd.trips.columns:
        return pl.DataFrame()

    stops = rd.trips.filter(pl.col("stops") == 1)
    all_trips = rd.trips
    max_period = 48
    if dep_col in rd.trips.columns:
        try:
            max_period = int(rd.trips[dep_col].max())
        except Exception:
            max_period = 48
    bins = list(range(1, 25 if max_period <= 24 else 49))

    if "tour_purpose" not in rd.trips.columns:
        purposes = {"Total": pl.lit(True)}
    else:
        purpose_list = rd.trips["tour_purpose"].drop_nulls().unique().sort().to_list()
        purposes = {p: pl.col("tour_purpose") == p for p in purpose_list}
        purposes["Total"] = pl.lit(True)

    rows = []
    for purp_name, filt in purposes.items():
        stop_sub = stops.filter(filt & pl.col(dep_col).is_between(1, bins[-1]))
        trip_sub = all_trips.filter(filt & pl.col(dep_col).is_between(1, bins[-1]))
        stop_counts = stop_sub.group_by(dep_col).agg(
            pl.col("finalweight").sum().alias("n_stop")
        )
        trip_counts = trip_sub.group_by(dep_col).agg(
            pl.col("finalweight").sum().alias("n_trip")
        )
        for tb in bins:
            ns = stop_counts.filter(pl.col(dep_col) == tb)["n_stop"]
            nt = trip_counts.filter(pl.col(dep_col) == tb)["n_trip"]
            rows.append(
                {
                    "timebin": tb,
                    "purpose": purp_name,
                    "freq_stop_dep": float(ns[0]) if len(ns) > 0 else 0.0,
                    "freq_trip_dep": float(nt[0]) if len(nt) > 0 else 0.0,
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)
