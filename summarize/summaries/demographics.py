"""Household and person demographic summaries."""

import polars as pl
from runtime.config import Config
from runtime.models import RunData


def hh_size(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Returns DataFrame: household_size (1-5+), household_count."""
    return (
        rd.hh.group_by("HHSIZE")
        .agg(household_count=pl.col("finalweight").sum())
        .rename({"HHSIZE": "household_size"})
        .sort("household_size")
    )


def person_type(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, person_type_label, person_count."""
    result_schema = {
        "person_type": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    }
    if "person_type" not in rd.per.columns:
        return pl.DataFrame(schema=result_schema)
    return (
        rd.per.select(
            [
                pl.col("person_type").cast(pl.Utf8).alias("person_type"),
                pl.col("finalweight"),
            ]
        )
        .group_by("person_type")
        .agg(person_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("person_type")
            .map_elements(
                lambda v: config.person_type_label(v),
                return_dtype=pl.Utf8,
            )
            .alias("person_type_label")
        )
        .sort("person_type")
    )


def population_totals(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "person_count": float(rd.per["finalweight"].sum()),
                "household_count": float(rd.hh["finalweight"].sum()),
                "tour_count": float(rd.tours["finalweight"].sum()),
                "trip_count": float(rd.trips["finalweight"].sum()),
                "stop_count": float(
                    rd.trips.filter(pl.col("stops") == 1)["finalweight"].sum()
                ),
            }
        ]
    )
