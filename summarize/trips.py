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

    # Find a valid non-numeric purpose column if available
    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.trips.columns and not rd.trips[cand].dtype.is_numeric():
            purpose_col = cand
            break

    cols = ["tour_mode", "trip_mode"]
    if purpose_col:
        cols = [purpose_col] + cols

    return (
        rd.trips.filter(
            pl.col("tour_mode").is_not_null() & pl.col("trip_mode").is_not_null()
        )
        .group_by(cols)
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(cols)
    )
