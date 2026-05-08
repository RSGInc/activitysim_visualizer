"""Optional summaries for skim-enriched prepared tables."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from runtime.config import Config


def _skim_component_columns(df: pl.DataFrame) -> list[str]:
    return [
        column
        for column in df.columns
        if "skim_" in column and df.schema.get(column) is not None
    ]


@summary_contract(
    schema={
        "trip_mode": pl.Utf8,
        "skim_component": pl.Utf8,
        "mean_value": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "finalweight")},
)
def trip_skim_component_means(rd: RunData, config: Config) -> pl.DataFrame:
    skim_columns = _skim_component_columns(rd.trips)
    if not skim_columns or {"trip_mode", "finalweight"} - set(rd.trips.columns):
        return empty_summary_frame(trip_skim_component_means)

    frames: list[pl.DataFrame] = []
    for column in skim_columns:
        frame = (
            rd.trips.filter(
                pl.col("trip_mode").is_not_null() & pl.col(column).is_not_null()
            )
            .group_by("trip_mode")
            .agg(
                (
                    (pl.col(column) * pl.col("finalweight")).sum()
                    / pl.col("finalweight").sum()
                ).alias("mean_value")
            )
            .with_columns(
                pl.lit(column).alias("skim_component"),
                pl.col("trip_mode").cast(pl.Utf8),
                pl.col("mean_value").cast(pl.Float64),
            )
            .select("trip_mode", "skim_component", "mean_value")
        )
        frames.append(frame)

    if not frames:
        return empty_summary_frame(trip_skim_component_means)
    return pl.concat(frames, how="vertical").sort(["trip_mode", "skim_component"])


@summary_contract(
    schema={
        "tour_mode": pl.Utf8,
        "skim_component": pl.Utf8,
        "mean_value": pl.Float64,
    },
    required_columns={"tours": ("tour_mode", "finalweight")},
)
def tour_skim_component_means(rd: RunData, config: Config) -> pl.DataFrame:
    skim_columns = _skim_component_columns(rd.tours)
    if not skim_columns or {"tour_mode", "finalweight"} - set(rd.tours.columns):
        return empty_summary_frame(tour_skim_component_means)

    frames: list[pl.DataFrame] = []
    for column in skim_columns:
        frame = (
            rd.tours.filter(
                pl.col("tour_mode").is_not_null() & pl.col(column).is_not_null()
            )
            .group_by("tour_mode")
            .agg(
                (
                    (pl.col(column) * pl.col("finalweight")).sum()
                    / pl.col("finalweight").sum()
                ).alias("mean_value")
            )
            .with_columns(
                pl.lit(column).alias("skim_component"),
                pl.col("tour_mode").cast(pl.Utf8),
                pl.col("mean_value").cast(pl.Float64),
            )
            .select("tour_mode", "skim_component", "mean_value")
        )
        frames.append(frame)

    if not frames:
        return empty_summary_frame(tour_skim_component_means)
    return pl.concat(frames, how="vertical").sort(["tour_mode", "skim_component"])
