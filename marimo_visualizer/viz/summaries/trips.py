"""Trip mode by tour mode cross-tab summaries."""

from __future__ import annotations

import polars as pl

from ..models import Config, RunData


def trip_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Trip mode by tour mode and primary purpose."""
    del config
    needed = {"tour_mode", "trip_mode"}
    if not needed.issubset(rd.trips.columns):
        return pl.DataFrame()

    cols = ["tour_mode", "trip_mode"]
    if "primary_purpose" in rd.trips.columns:
        cols = ["primary_purpose"] + cols

    return (
        rd.trips.filter(pl.col("tour_mode").is_not_null() & pl.col("trip_mode").is_not_null())
        .group_by(cols)
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(cols)
    )
