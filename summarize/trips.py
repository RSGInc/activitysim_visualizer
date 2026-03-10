"""Trip mode by tour mode cross-tab.

Uses tour_mode and trip_mode strings directly from ActivitySim outputs.
"""
import polars as pl
from .reader import RunData, Config


def trip_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Trip mode by tour mode by primary purpose.

    Columns: primary_purpose, tour_mode, trip_mode, freq.
    """
    needed = {"tour_mode", "trip_mode"}
    if not needed.issubset(rd.trips.columns):
        return pl.DataFrame()

    cols = ["tour_mode", "trip_mode"]
    if "primary_purpose" in rd.trips.columns:
        cols = ["primary_purpose"] + cols

    return (rd.trips
            .filter(pl.col("tour_mode").is_not_null() & pl.col("trip_mode").is_not_null())
            .group_by(cols)
            .agg(pl.col("finalweight").sum().alias("freq"))
            .sort(cols))

