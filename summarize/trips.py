"""Trip mode by tour mode cross-tab."""

import polars as pl
from runtime.config import Config
from runtime.models import RunData


def trip_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Trip mode by tour mode by purpose.

    Columns: purpose, tour_mode, trip_mode, freq.
    """
    needed = {"tour_mode", "trip_mode"}
    if not needed.issubset(rd.trips.columns):
        return pl.DataFrame()

    cols = ["tour_mode", "trip_mode"]
    if "tour_purpose" in rd.trips.columns:
        cols = ["tour_purpose"] + cols

    result = (
        rd.trips.filter(
            pl.col("tour_mode").is_not_null() & pl.col("trip_mode").is_not_null()
        )
        .group_by(cols)
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(cols)
    )
    if "tour_purpose" in result.columns:
        result = result.rename({"tour_purpose": "purpose"})
    else:
        result = result.with_columns(pl.lit("Total").alias("purpose")).select(
            ["purpose", "tour_mode", "trip_mode", "freq"]
        )
    return result
