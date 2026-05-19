"""Allocated-vehicle tour summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from runtime.config import Config


def _prepared_allocated_vehicles_from_tours(rd: RunData) -> pl.DataFrame:
    """Reshape allocated vehicle columns on tours into one long prepared frame."""
    required = {
        "vehicle_occup_1",
        "vehicle_occup_2",
        "vehicle_occup_3.5",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame()

    long_df = pl.concat(
        [
            rd.tours.select(
                pl.lit("1").alias("occupancy"),
                pl.col("vehicle_occup_1").alias("allocated_vehicle_type"),
                pl.col("finalweight"),
            ),
            rd.tours.select(
                pl.lit("2").alias("occupancy"),
                pl.col("vehicle_occup_2").alias("allocated_vehicle_type"),
                pl.col("finalweight"),
            ),
            rd.tours.select(
                pl.lit("3+").alias("occupancy"),
                pl.col("vehicle_occup_3.5").alias("allocated_vehicle_type"),
                pl.col("finalweight"),
            ),
        ],
        how="vertical",
    )

    return (
        long_df.filter(pl.col("allocated_vehicle_type").is_not_null())
        .with_columns(
            parts=pl.col("allocated_vehicle_type").cast(pl.Utf8).str.split("_"),
        )
        .with_columns(
            body_type=pl.col("parts").list.get(0).cast(pl.Utf8),
            age_raw=pl.col("parts").list.get(1).cast(pl.Int64, strict=False),
            fuel_type=pl.col("parts").list.get(2).cast(pl.Utf8),
        )
        .filter(
            pl.col("body_type").is_not_null()
            & pl.col("fuel_type").is_not_null()
            & pl.col("age_raw").is_not_null()
        )
        .with_columns(
            pl.when(pl.col("age_raw") >= 20)
            .then(pl.lit("20+"))
            .otherwise(pl.col("age_raw").cast(pl.Utf8))
            .alias("age")
        )
        .drop(["parts", "age_raw"])
    )


@summary_contract(
    schema={"age": pl.Utf8, "occupancy": pl.Utf8, "vehicle_count": pl.Float64},
    required_columns={
        "tours": (
            "vehicle_occup_1",
            "vehicle_occup_2",
            "vehicle_occup_3.5",
            "finalweight",
        )
    },
)
def allocated_vehicle_age(rd: RunData, config: Config) -> pl.DataFrame:
    vehicles = _prepared_allocated_vehicles_from_tours(rd)
    if vehicles.is_empty():
        return empty_summary_frame(allocated_vehicle_age)

    return (
        vehicles.group_by(["age", "occupancy"])
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("age").cast(pl.Utf8),
            pl.col("occupancy").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
            pl.when(pl.col("age") == "20+")
            .then(999)
            .otherwise(pl.col("age").cast(pl.Int64, strict=False))
            .alias("_sort_age"),
        )
        .sort(["_sort_age", "occupancy"])
        .select("age", "occupancy", "vehicle_count")
    )


@summary_contract(
    schema={"fuel_type": pl.Utf8, "occupancy": pl.Utf8, "vehicle_count": pl.Float64},
    required_columns={
        "tours": (
            "vehicle_occup_1",
            "vehicle_occup_2",
            "vehicle_occup_3.5",
            "finalweight",
        )
    },
)
def allocated_vehicle_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    vehicles = _prepared_allocated_vehicles_from_tours(rd)
    if vehicles.is_empty():
        return empty_summary_frame(allocated_vehicle_fuel)

    return (
        vehicles.group_by(["fuel_type", "occupancy"])
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("fuel_type").cast(pl.Utf8),
            pl.col("occupancy").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("fuel_type", "occupancy", "vehicle_count")
        .sort(["fuel_type", "occupancy"])
    )


@summary_contract(
    schema={"body_type": pl.Utf8, "occupancy": pl.Utf8, "vehicle_count": pl.Float64},
    required_columns={
        "tours": (
            "vehicle_occup_1",
            "vehicle_occup_2",
            "vehicle_occup_3.5",
            "finalweight",
        )
    },
)
def allocated_vehicle_body(rd: RunData, config: Config) -> pl.DataFrame:
    vehicles = _prepared_allocated_vehicles_from_tours(rd)
    if vehicles.is_empty():
        return empty_summary_frame(allocated_vehicle_body)

    return (
        vehicles.group_by(["body_type", "occupancy"])
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("body_type").cast(pl.Utf8),
            pl.col("occupancy").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("body_type", "occupancy", "vehicle_count")
        .sort(["body_type", "occupancy"])
    )
