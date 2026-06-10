"""Activity-pattern and rate daily travel summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.summary_helpers import (
    _all_person_types_rollup,
    _summary_purpose_column,
)
from runtime.config import Config


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "daily_activity_pattern": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "cdap_activity", "finalweight")},
)
def dap_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """DAP by person type. Columns: person_type, daily_activity_pattern, person_count"""
    if "person_type" not in rd.per.columns or "cdap_activity" not in rd.per.columns:
        return empty_summary_frame(dap_summary)

    df = (
        rd.per.filter(pl.col("cdap_activity").is_not_null())
        .group_by(["person_type", "cdap_activity"])
        .agg(person_count=pl.col("finalweight").sum())
        .rename({"cdap_activity": "daily_activity_pattern"})
        .with_columns(
            pl.col("person_type").cast(pl.Utf8).alias("person_type"),
            pl.col("daily_activity_pattern").cast(pl.Utf8),
        )
        .select("person_type", "daily_activity_pattern", "person_count")
    )

    total = _all_person_types_rollup(
        df,
        group_cols=["daily_activity_pattern"],
        value_col="person_count",
    ).select("person_type", "daily_activity_pattern", "person_count")

    return pl.concat([df, total], how="vertical").sort(
        ["person_type", "daily_activity_pattern"]
    )


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "mandatory_tour_frequency": pl.Int32,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "imf_choice", "finalweight")},
)
def mandatory_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, mandatory_tour_frequency, person_count."""
    if "person_type" not in rd.per.columns or "imf_choice" not in rd.per.columns:
        return empty_summary_frame(mandatory_tour_freq)

    df = (
        rd.per.filter(pl.col("imf_choice") > 0)
        .group_by(["person_type", "imf_choice"])
        .agg(person_count=pl.col("finalweight").sum())
        .rename({"imf_choice": "mandatory_tour_frequency"})
        .with_columns(pl.col("person_type").cast(pl.Utf8).alias("person_type"))
        .select("person_type", "mandatory_tour_frequency", "person_count")
    )

    total = _all_person_types_rollup(
        df,
        group_cols=["mandatory_tour_frequency"],
        value_col="person_count",
    ).select("person_type", "mandatory_tour_frequency", "person_count")

    return pl.concat([df, total], how="vertical").sort(
        ["person_type", "mandatory_tour_frequency"]
    )


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "nonmandatory_tour_frequency": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "person_type", "finalweight"),
        "tours": ("person_id", "tour_category"),
        "joint_participants": ("person_id",),
    },
)
def indiv_nm_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, nonmandatory_tour_frequency, person_count."""
    per = rd.per
    if "person_type" not in per.columns:
        return empty_summary_frame(indiv_nm_summary)

    if "tour_category" in rd.tours.columns:
        inm_counts = (
            rd.tours.filter(pl.col("tour_category") == "non_mandatory")
            .group_by("person_id")
            .agg(pl.len().alias("inmTours"))
        )
    else:
        inm_counts = per.select("person_id").with_columns(pl.lit(0).alias("inmTours"))

    if "person_id" in rd.joint_participants.columns:
        jnm_counts = rd.joint_participants.group_by("person_id").agg(
            pl.len().alias("jnumTours")
        )
    else:
        jnm_counts = per.select("person_id").with_columns(pl.lit(0).alias("jnumTours"))

    per2 = (
        per.join(inm_counts, on="person_id", how="left")
        .join(jnm_counts, on="person_id", how="left")
        .with_columns(
            [
                pl.col("inmTours").fill_null(0),
                pl.col("jnumTours").fill_null(0),
            ]
        )
        .with_columns((pl.col("inmTours") + pl.col("jnumTours")).alias("numTours"))
        .with_columns(
            pl.when(pl.col("numTours") == 0)
            .then(pl.lit("0"))
            .when(pl.col("numTours") == 1)
            .then(pl.lit("1"))
            .when(pl.col("numTours") == 2)
            .then(pl.lit("2"))
            .otherwise(pl.lit("3+"))
            .alias("nonmandatory_tour_frequency")
        )
    )

    df = (
        per2.group_by(["person_type", "nonmandatory_tour_frequency"])
        .agg(person_count=pl.col("finalweight").sum())
        .with_columns(pl.col("person_type").cast(pl.Utf8).alias("person_type"))
        .select("person_type", "nonmandatory_tour_frequency", "person_count")
    )

    total = _all_person_types_rollup(
        df,
        group_cols=["nonmandatory_tour_frequency"],
        value_col="person_count",
    ).select("person_type", "nonmandatory_tour_frequency", "person_count")

    return pl.concat([df, total], how="vertical").sort(
        ["person_type", "nonmandatory_tour_frequency"]
    )


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "tour_rate": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "person_type", "finalweight"),
        "tours": ("person_id", "tour_purpose"),
    },
)
def tour_rate_per_person(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"person_id", "person_type", "finalweight"}
    tour_required = {"person_id", "tour_purpose"}

    if not person_required.issubset(set(rd.per.columns)) or not tour_required.issubset(
        set(rd.tours.columns)
    ):
        return empty_summary_frame(tour_rate_per_person)

    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_rate_per_person)

    weighted_person_days = (
        rd.per.filter(
            pl.col("person_id").is_not_null()
            & pl.col("person_type").is_not_null()
            & pl.col("finalweight").is_not_null()
        )
        .select(
            "person_id",
            pl.col("person_type").cast(pl.Utf8),
            pl.col("finalweight").cast(pl.Float64).alias("person_weight"),
        )
        .group_by("person_type")
        .agg(weighted_person_days=pl.col("person_weight").sum())
    )

    weighted_tours = (
        rd.tours.filter(
            pl.col("person_id").is_not_null() & pl.col(purpose_col).is_not_null()
        )
        .join(
            rd.per.filter(
                pl.col("person_id").is_not_null()
                & pl.col("person_type").is_not_null()
                & pl.col("finalweight").is_not_null()
            ).select(
                "person_id",
                pl.col("person_type").cast(pl.Utf8),
                pl.col("finalweight").cast(pl.Float64).alias("person_weight"),
            ),
            on="person_id",
            how="inner",
        )
        .group_by(["person_type", purpose_col])
        .agg(weighted_tours=pl.col("person_weight").sum())
        .rename({purpose_col: "tour_purpose"})
        .with_columns(pl.col("tour_purpose").cast(pl.Utf8))
    )

    by_person_type = (
        weighted_tours.join(weighted_person_days, on="person_type", how="left")
        .with_columns(
            pl.when(pl.col("weighted_person_days") > 0)
            .then(pl.col("weighted_tours") / pl.col("weighted_person_days"))
            .otherwise(None)
            .alias("tour_rate")
        )
        .select(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_rate").cast(pl.Float64),
        )
        .sort(["person_type", "tour_purpose"])
    )

    total_person_days = float(weighted_person_days["weighted_person_days"].sum())
    all_person_types = (
        weighted_tours.group_by("tour_purpose")
        .agg(weighted_tours=pl.col("weighted_tours").sum())
        .with_columns(
            pl.lit("all_person_types").alias("person_type"),
            pl.when(pl.lit(total_person_days) > 0)
            .then(pl.col("weighted_tours") / pl.lit(total_person_days))
            .otherwise(None)
            .alias("tour_rate"),
        )
        .select(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_rate").cast(pl.Float64),
        )
        .sort(["person_type", "tour_purpose"])
    )

    return pl.concat([by_person_type, all_person_types], how="vertical").sort(
        ["person_type", "tour_purpose"]
    )


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "trip_purpose": pl.Utf8,
        "trip_rate": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "person_type", "finalweight"),
        "trips": ("person_id", "trip_purpose", "finalweight"),
    },
)
def trip_rate_per_person(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"person_id", "person_type", "finalweight"}
    trip_required = {"person_id", "trip_purpose", "finalweight"}

    if not person_required.issubset(set(rd.per.columns)) or not trip_required.issubset(
        set(rd.trips.columns)
    ):
        return empty_summary_frame(trip_rate_per_person)

    person_totals = (
        rd.per.filter(pl.col("person_type").is_not_null())
        .group_by("person_type")
        .agg(person_count=pl.col("finalweight").sum())
        .with_columns(pl.col("person_type").cast(pl.Utf8))
    )

    trip_totals = (
        rd.trips.filter(
            pl.col("person_id").is_not_null() & pl.col("trip_purpose").is_not_null()
        )
        .join(
            rd.per.select("person_id", "person_type"),
            on="person_id",
            how="inner",
        )
        .filter(pl.col("person_type").is_not_null())
        .group_by(["person_type", "trip_purpose"])
        .agg(trip_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("trip_purpose").cast(pl.Utf8),
        )
    )

    by_person_type = (
        trip_totals.join(person_totals, on="person_type", how="left")
        .with_columns(
            pl.when(pl.col("person_count") > 0)
            .then(pl.col("trip_count") / pl.col("person_count"))
            .otherwise(None)
            .alias("trip_rate")
        )
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("trip_purpose").cast(pl.Utf8),
            pl.col("trip_rate").cast(pl.Float64),
        )
        .select("person_type", "trip_purpose", "trip_rate")
        .sort(["person_type", "trip_purpose"])
    )

    total_person_count = float(person_totals["person_count"].sum())
    all_person_types = (
        trip_totals.group_by("trip_purpose")
        .agg(trip_count=pl.col("trip_count").sum())
        .with_columns(
            pl.lit("all_person_types").alias("person_type"),
            pl.when(pl.lit(total_person_count) > 0)
            .then(pl.col("trip_count") / pl.lit(total_person_count))
            .otherwise(None)
            .alias("trip_rate"),
        )
        .select(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("trip_purpose").cast(pl.Utf8),
            pl.col("trip_rate").cast(pl.Float64),
        )
        .sort(["person_type", "trip_purpose"])
    )

    return pl.concat([by_person_type, all_person_types], how="vertical").sort(
        ["person_type", "trip_purpose"]
    )
