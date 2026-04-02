"""System-wide KPI totals."""

import polars as pl
from .reader import RunData, Config


def system_totals(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """
    System-wide KPIs. Returns single-row DataFrame with columns:
    population, households, employment, tours, trips, stops,
    pmt, vmt, vehicle_trips.
    """
    pop = rd.per["finalweight"].sum()
    hh = rd.hh["finalweight"].sum()
    emp_col = next(
        (
            c
            for c in ["EMPLOY_TOT", "TOTEMP", "total_employment", "employment"]
            if c in rd.land_use.columns
        ),
        None,
    )
    emp = rd.land_use[emp_col].sum() if emp_col else 0

    tours = rd.tours["finalweight"].sum()
    trips_total = rd.trips["finalweight"].sum()
    stops = rd.trips.filter(pl.col("stops") == 1)["finalweight"].sum()

    # PMT = sum of od_dist * finalweight for all trips
    pmt = rd.trips.with_columns(
        (pl.col("od_dist") * pl.col("finalweight")).alias("pmt_w")
    )["pmt_w"].sum()

    # Identify auto trips via trip_mode string:
    # Use config.mode_groups["Auto"] if defined, else check for common auto mode substrings.
    trips_df = rd.trips
    if "trip_mode" in trips_df.columns:
        auto_modes: list[str] | None = None
        if config is not None and config.mode_groups and "Auto" in config.mode_groups:
            auto_modes = config.mode_groups["Auto"]

        if auto_modes is not None:
            auto_filter = pl.col("trip_mode").cast(pl.Utf8).is_in(auto_modes)
        else:
            # Fallback: modes that look like auto (drive alone / shared ride)
            auto_filter = (
                pl.col("trip_mode")
                .cast(pl.Utf8)
                .str.to_uppercase()
                .str.contains("DRIVE|SHARED|SOV|HOV|AUTO")
            )
        auto_trips = trips_df.filter(auto_filter)
    else:
        auto_trips = trips_df.head(0)

    vmt = auto_trips.with_columns(
        (
            pl.col("od_dist")
            * pl.col("finalweight")
            / pl.col("num_participants").fill_null(1)
        ).alias("vmt_w")
    )["vmt_w"].sum()

    vehicle_trips = auto_trips["finalweight"].sum()

    return pl.DataFrame(
        [
            {
                "population": float(pop),
                "households": float(hh),
                "employment": float(emp),
                "tours": float(tours),
                "trips": float(trips_total),
                "stops": float(stops),
                "pmt": float(pmt) if pmt else 0.0,
                "vmt": float(vmt) if vmt else 0.0,
                "vehicle_trips": float(vehicle_trips),
            }
        ]
    )
