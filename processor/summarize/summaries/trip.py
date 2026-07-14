"""Trip summaries."""

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    ALL_TOUR_PURPOSES,
    aggregate_counts_across_geographies,
    _all_purpose_rollup as _all_tour_purpose_rollup,
    _configured_geography_dimensions,
    _summary_purpose_column as _trip_purpose_column,
    weighted_group_sum,
)
from runtime.config import Config


@summary(
    id="trip_purpose_distribution",
    schema={
        "tour_purpose": pl.Utf8,
        "trip_purpose": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={"trips": ("tour_purpose", "trip_purpose", "finalweight")},
)
def trip_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"trip_purpose", "finalweight"}
    if not required.issubset(set(rd.trips.columns)):
        return trip_purpose.empty()
    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return trip_purpose.empty()

    base = (
        rd.trips.filter(pl.col("trip_purpose").is_not_null())
        .filter(pl.col(purpose_col).is_not_null())
        .group_by([purpose_col, "trip_purpose"])
        .agg(trip_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
        .with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("trip_purpose").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
        .select("tour_purpose", "trip_purpose", "trip_count")
    )
    all_purposes = _all_tour_purpose_rollup(
        base,
        group_cols=["trip_purpose"],
        value_col="trip_count",
    ).select("tour_purpose", "trip_purpose", "trip_count")

    return pl.concat([base, all_purposes], how="vertical").sort(
        ["tour_purpose", "trip_purpose"]
    )


@summary(
    id="stop_destination_purpose_by_tour_purpose",
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
    """Stop destination purpose by tour purpose."""
    required = {"stops", "tour_purpose", "trip_purpose", "finalweight"}
    if not required.issubset(rd.trips.columns):
        return stop_purpose_by_tour_purpose.empty()

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return stop_purpose_by_tour_purpose.empty()

    return (
        rd.trips.filter(pl.col("stops") == 1)
        .filter(
            pl.col(purpose_col).is_not_null() & pl.col("trip_purpose").is_not_null()
        )
        .group_by([purpose_col, "trip_purpose"])
        .agg(stop_count=pl.col("finalweight").sum())
        .rename(
            {
                purpose_col: "tour_purpose",
                "trip_purpose": "stop_destination_purpose",
            }
        )
        .select("stop_destination_purpose", "tour_purpose", "stop_count")
        .sort(["tour_purpose", "stop_destination_purpose"])
    )


@summary(
    id="trip_mode_by_tour_purpose_and_tour_mode",
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
        return trip_mode.empty()
    if "tour_purpose" not in rd.trips.columns:
        return trip_mode.empty()

    purpose_col = _trip_purpose_column(rd.trips)
    if not purpose_col:
        return trip_mode.empty()

    base = (
        rd.trips.filter(
            pl.col(purpose_col).is_not_null()
            & pl.col("tour_mode").is_not_null()
            & pl.col("trip_mode").is_not_null()
        )
        .pipe(
            weighted_group_sum,
            [purpose_col, "tour_mode", "trip_mode"],
            weight_col="finalweight",
            output_col="trip_count",
        )
        .rename({purpose_col: "tour_purpose"})
        .select(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
            pl.col("trip_mode").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
    )

    all_purposes = _all_tour_purpose_rollup(
        base,
        group_cols=["tour_mode", "trip_mode"],
        value_col="trip_count",
    ).select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
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
            pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"),
            pl.lit("all_tour_modes").alias("tour_mode"),
        )
        .select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
    )

    return (
        pl.concat([base, all_purposes, all_tour_modes, grand_total], how="vertical")
        .select("tour_purpose", "tour_mode", "trip_mode", "trip_count")
        .sort(["tour_purpose", "tour_mode", "trip_mode"])
    )


@summary(
    id="parking_locations",
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
        return parking_locations.empty()

    base = rd.trips.filter(
        pl.col("parking_zone").is_not_null()
        & (pl.col("parking_zone").cast(pl.Int64, strict=False) > 0)
    ).select("parking_zone", "finalweight")
    if base.is_empty():
        return parking_locations.empty()

    outputs = [
        aggregate_counts_across_geographies(
            base,
            geography_dimensions=_configured_geography_dimensions(
                base,
                config=config,
                base_type="maz" if config.use_maz else "taz",
                base_col="parking_zone",
                role_prefix="parking",
            ),
        )
    ]

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
