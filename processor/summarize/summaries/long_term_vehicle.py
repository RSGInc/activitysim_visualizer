"""Vehicle and household-asset long-term summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from runtime.config import Config


@summary(
    id="autonomous_vehicle_ownership_totals",
    schema={"household_with_autonomous_vehicle_count": pl.Float64},
    required_columns={"hh": ("av_ownership", "finalweight")},
)
def av_ownership(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"av_ownership", "finalweight"}
    if not required.issubset(set(rd.hh.columns)):
        return av_ownership.empty()

    return rd.hh.filter(pl.col("av_ownership") == True).select(
        pl.col("finalweight")
        .sum()
        .cast(pl.Float64)
        .alias("household_with_autonomous_vehicle_count")
    )


@summary(
    id="auto_ownership_distribution",
    schema={
        "household_size": pl.Utf8,
        "household_vehicle_count": pl.Int64,
        "household_count": pl.Float64,
    },
    required_columns={"hh": ("HHSIZE", "HHVEH", "finalweight")},
)
def auto_ownership(rd: RunData, config: Config) -> pl.DataFrame:
    return (
        rd.hh.with_columns(
            pl.when(pl.col("HHSIZE").cast(pl.Int64, strict=False) >= 5)
            .then(pl.lit("5+"))
            .otherwise(pl.col("HHSIZE").cast(pl.Int64, strict=False).cast(pl.Utf8))
            .alias("household_size")
        )
        .group_by(["household_size", "HHVEH"])
        .agg(household_count=pl.col("finalweight").sum())
        .rename({"HHVEH": "household_vehicle_count"})
        .with_columns(
            pl.col("household_size").cast(pl.Utf8),
            pl.col("household_vehicle_count").cast(pl.Int64),
            pl.col("household_count").cast(pl.Float64),
            pl.when(pl.col("household_size") == "5+")
            .then(999)
            .otherwise(pl.col("household_size").cast(pl.Int64, strict=False))
            .alias("_sort_household_size"),
        )
        .sort(["_sort_household_size", "household_vehicle_count"])
        .select("household_size", "household_vehicle_count", "household_count")
    )


@summary(
    id="vehicle_age_distribution",
    schema={
        "age": pl.Utf8,
        "vehicle_count": pl.Float64,
    },
    required_columns={"vehicles": ("vehicle_age", "finalweight")},
)
def vehicle_char_age(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"vehicle_age", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return vehicle_char_age.empty()
    if not required.issubset(set(rd.vehicles.columns)):
        return vehicle_char_age.empty()

    return (
        rd.vehicles.filter(pl.col("vehicle_age").is_not_null())
        .with_columns(
            pl.when(pl.col("vehicle_age") >= 20)
            .then(pl.lit("20+"))
            .otherwise(pl.col("vehicle_age").cast(pl.Utf8))
            .alias("age")
        )
        .group_by("age")
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("age").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
            pl.when(pl.col("age") == "20+")
            .then(999)
            .otherwise(pl.col("age").cast(pl.Int64, strict=False))
            .alias("_sort_age"),
        )
        .sort("_sort_age")
        .select("age", "vehicle_count")
    )


@summary(
    id="vehicle_fuel_type_distribution",
    schema={
        "fuel_type": pl.Utf8,
        "vehicle_count": pl.Float64,
    },
    required_columns={"vehicles": ("fuel_type", "finalweight")},
)
def vehicle_char_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"fuel_type", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return vehicle_char_fuel.empty()
    if not required.issubset(set(rd.vehicles.columns)):
        return vehicle_char_fuel.empty()

    return (
        rd.vehicles.filter(pl.col("fuel_type").is_not_null())
        .group_by("fuel_type")
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("fuel_type").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("fuel_type", "vehicle_count")
        .sort("fuel_type")
    )


@summary(
    id="vehicle_body_type_distribution",
    schema={
        "body_type": pl.Utf8,
        "vehicle_count": pl.Float64,
    },
    required_columns={"vehicles": ("body_type", "finalweight")},
)
def vehicle_char_body(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"body_type", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return vehicle_char_body.empty()
    if not required.issubset(set(rd.vehicles.columns)):
        return vehicle_char_body.empty()

    return (
        rd.vehicles.filter(pl.col("body_type").is_not_null())
        .group_by("body_type")
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("body_type").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("body_type", "vehicle_count")
        .sort("body_type")
    )
