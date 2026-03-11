"""System-wide KPI totals."""

from __future__ import annotations

import polars as pl

from ..models import Config, RunData


def system_totals(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Return a single-row KPI table for population, trips, VMT, and related totals."""
    population = rd.per["finalweight"].sum()
    households = rd.hh["finalweight"].sum()
    emp_col = next((col for col in ["EMPLOY_TOT", "TOTEMP", "total_employment", "employment"] if col in rd.land_use.columns), None)
    employment = rd.land_use[emp_col].sum() if emp_col else 0

    tours = rd.tours["finalweight"].sum()
    trips_total = rd.trips["finalweight"].sum()
    stops = rd.trips.filter(pl.col("stops") == 1)["finalweight"].sum() if "stops" in rd.trips.columns else 0.0
    pmt = (
        rd.trips.with_columns((pl.col("od_dist") * pl.col("finalweight")).alias("pmt_w"))["pmt_w"].sum()
        if "od_dist" in rd.trips.columns
        else 0.0
    )

    if "trip_mode" in rd.trips.columns:
        auto_modes: list[str] | None = None
        if config is not None and config.mode_groups and "Auto" in config.mode_groups:
            auto_modes = config.mode_groups["Auto"]
        if auto_modes is not None:
            auto_filter = pl.col("trip_mode").cast(pl.Utf8).is_in(auto_modes)
        else:
            auto_filter = pl.col("trip_mode").cast(pl.Utf8).str.to_uppercase().str.contains("DRIVE|SHARED|SOV|HOV|AUTO")
        auto_trips = rd.trips.filter(auto_filter)
    else:
        auto_trips = rd.trips.head(0)

    vmt = (
        auto_trips.with_columns(
            (pl.col("od_dist") * pl.col("finalweight") / pl.col("num_participants").fill_null(1)).alias("vmt_w")
        )["vmt_w"].sum()
        if {"od_dist", "num_participants"}.issubset(auto_trips.columns)
        else 0.0
    )
    vehicle_trips = auto_trips["finalweight"].sum()

    return pl.DataFrame(
        [
            {
                "population": float(population),
                "households": float(households),
                "employment": float(employment),
                "tours": float(tours),
                "trips": float(trips_total),
                "stops": float(stops),
                "pmt": float(pmt) if pmt else 0.0,
                "vmt": float(vmt) if vmt else 0.0,
                "vehicle_trips": float(vehicle_trips),
            }
        ]
    )
