"""Household and person demographic summaries."""

import polars as pl
from runtime.config import Config
from processor.models import RunData
from processor.summarize.contracts import summary


@summary(
    id="household_size_distribution",
    schema={
        "household_size": pl.Int64,
        "household_count": pl.Float64,
    },
    required_columns={"hh": ("HHSIZE", "finalweight")},
)
def hh_size(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Returns DataFrame: household_size (1-5+), household_count."""
    return (
        rd.hh.group_by("HHSIZE")
        .agg(household_count=pl.col("finalweight").sum())
        .rename({"HHSIZE": "household_size"})
        .with_columns(pl.col("household_size").cast(pl.Int64))
        .sort("household_size")
    )


@summary(
    id="person_type_distribution",
    schema={
        "person_type": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "finalweight")},
)
def person_type(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, person_type_label, person_count."""
    if "person_type" not in rd.per.columns:
        return person_type.empty()
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
        .select("person_type", "person_type_label", "person_count")
        .sort("person_type")
    )


@summary(
    id="population_totals",
    schema={
        "person_count": pl.Float64,
        "household_count": pl.Float64,
        "tour_count": pl.Float64,
        "trip_count": pl.Float64,
        "stop_count": pl.Float64,
    },
    required_columns={
        "per": ("finalweight",),
        "hh": ("finalweight",),
        "tours": ("finalweight",),
        "trips": ("finalweight", "stops"),
    },
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
