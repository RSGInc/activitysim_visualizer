"""Prepare helpers for optional day and vehicle tables."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.types import _PrepareState


def _prepare_day(state: _PrepareState) -> _PrepareState:
    day = state.day
    if day.is_empty() or "person_id" not in day.columns:
        state.day = day
        return state

    if "person_type" not in day.columns and {
        "person_id",
        "person_type",
    }.issubset(set(state.per.columns)):
        day = day.join(
            state.per.select("person_id", "person_type").unique(),
            on="person_id",
            how="left",
        )

    state.day = day
    return state


def _prepare_vehicles(state: _PrepareState) -> _PrepareState:
    vehicles = state.vehicles
    if vehicles.is_empty() or "vehicle_type" not in vehicles.columns:
        state.vehicles = vehicles
        return state

    vehicles = vehicles.with_columns(
        pl.col("vehicle_type").cast(pl.Utf8).str.split("_").alias("_vehicle_type_parts")
    ).with_columns(
        pl.col("_vehicle_type_parts").list.get(0).cast(pl.Utf8).alias("body_type"),
        pl.col("_vehicle_type_parts").list.get(1).cast(pl.Int64, strict=False).alias(
            "vehicle_age"
        ),
        pl.col("_vehicle_type_parts").list.get(2).cast(pl.Utf8).alias("fuel_type"),
    ).drop("_vehicle_type_parts")

    state.vehicles = vehicles
    return state
