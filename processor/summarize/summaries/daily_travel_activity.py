"""Activity-pattern and rate daily travel summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    _all_person_types_rollup,
    _summary_purpose_column,
)
from runtime.config import Config


def _person_exposure_records(rd: RunData) -> pl.DataFrame:
    persons = rd.per.filter(
        pl.col("person_id").is_not_null()
        & pl.col("person_type").is_not_null()
        & pl.col("finalweight").is_not_null()
    ).select(
        "person_id",
        pl.col("person_type").cast(pl.Utf8),
        pl.col("finalweight").cast(pl.Float64).alias("person_weight"),
    )

    if not rd.day.is_empty() and "person_id" in rd.day.columns:
        day_people = rd.day.filter(pl.col("person_id").is_not_null()).select(
            "person_id"
        )
        if day_people.height > day_people["person_id"].n_unique():
            return day_people.join(persons, on="person_id", how="inner")

    return persons


@summary(
    id="daily_activity_pattern_by_person_type",
    schema={
        "person_type": pl.Utf8,
        "daily_activity_pattern": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "finalweight")},
)
def dap_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """DAP by person type. Columns: person_type, daily_activity_pattern, person_count"""
    person_activity_required = {"person_type", "cdap_activity", "finalweight"}
    day_required = {"person_id", "cdap_activity"}
    person_required = {"person_id", "person_type", "finalweight"}
    if person_activity_required.issubset(rd.per.columns) and rd.per.select(
        pl.col("cdap_activity").is_not_null().any()
    ).item():
        source = rd.per
    elif (
        not rd.day.is_empty()
        and day_required.issubset(rd.day.columns)
        and person_required.issubset(rd.per.columns)
    ):
        source = (
            rd.day.filter(pl.col("cdap_activity").is_not_null())
            .select("person_id", "cdap_activity")
            .join(
                rd.per.select("person_id", "person_type", "finalweight"),
                on="person_id",
                how="inner",
            )
        )
    else:
        return dap_summary.empty()

    df = (
        source.filter(pl.col("cdap_activity").is_not_null())
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


@summary(
    id="mandatory_tour_frequency_by_person_type",
    schema={
        "person_type": pl.Utf8,
        "mandatory_tour_frequency": pl.Int32,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_id", "person_type", "finalweight")},
)
def mandatory_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, mandatory_tour_frequency, person_count."""
    person_choice_required = {"person_type", "imf_choice", "finalweight"}
    if person_choice_required.issubset(rd.per.columns) and rd.per.select(
        pl.col("imf_choice").is_not_null().any()
    ).item():
        source = rd.per.select("person_type", "imf_choice", "finalweight")
    else:
        person_required = {"person_id", "person_type", "finalweight"}
        day_required = {"person_id", "day_id"}
        tour_required = {"person_id", "day_id"}
        purpose_col = _summary_purpose_column(rd.tours)
        if (
            not person_required.issubset(rd.per.columns)
            or not day_required.issubset(rd.day.columns)
            or not tour_required.issubset(rd.tours.columns)
            or not purpose_col
        ):
            return mandatory_tour_freq.empty()

        mandatory_tours = rd.tours.filter(
            pl.col("person_id").is_not_null()
            & pl.col("day_id").is_not_null()
            & pl.col(purpose_col).is_not_null()
        )
        if "tour_category" in mandatory_tours.columns:
            mandatory_tours = mandatory_tours.filter(
                pl.col("tour_category") == "mandatory"
            )

        tour_counts = mandatory_tours.group_by(["person_id", "day_id"]).agg(
            (pl.col(purpose_col).cast(pl.Utf8).str.to_lowercase() == "work")
            .sum()
            .alias("_work_tours"),
            (pl.col(purpose_col).cast(pl.Utf8).str.to_lowercase() == "school")
            .sum()
            .alias("_school_tours"),
        )

        source = (
            rd.day.filter(
                pl.col("person_id").is_not_null() & pl.col("day_id").is_not_null()
            )
            .select("person_id", "day_id")
            .join(
                rd.per.select("person_id", "person_type", "finalweight"),
                on="person_id",
                how="inner",
            )
            .join(tour_counts, on=["person_id", "day_id"], how="left")
            .with_columns(
                pl.col("_work_tours").fill_null(0),
                pl.col("_school_tours").fill_null(0),
            )
            .with_columns(
                pl.when(
                    (pl.col("_work_tours") == 0)
                    & (pl.col("_school_tours") == 0)
                )
                .then(pl.lit(0))
                .when(
                    (pl.col("_work_tours") == 1)
                    & (pl.col("_school_tours") == 0)
                )
                .then(pl.lit(1))
                .when(
                    (pl.col("_work_tours") == 2)
                    & (pl.col("_school_tours") == 0)
                )
                .then(pl.lit(2))
                .when(
                    (pl.col("_work_tours") == 0)
                    & (pl.col("_school_tours") == 1)
                )
                .then(pl.lit(3))
                .when(
                    (pl.col("_work_tours") == 0)
                    & (pl.col("_school_tours") == 2)
                )
                .then(pl.lit(4))
                .when(
                    (pl.col("_work_tours") == 1)
                    & (pl.col("_school_tours") == 1)
                )
                .then(pl.lit(5))
                .otherwise(None)
                .alias("imf_choice")
            )
            .select("person_type", "imf_choice", "finalweight")
        )

    df = (
        source.filter(pl.col("imf_choice") > 0)
        .group_by(["person_type", "imf_choice"])
        .agg(person_count=pl.col("finalweight").sum())
        .rename({"imf_choice": "mandatory_tour_frequency"})
        .with_columns(
            pl.col("person_type").cast(pl.Utf8).alias("person_type"),
            pl.col("mandatory_tour_frequency").cast(pl.Int32),
        )
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


@summary(
    id="nonmandatory_tour_frequency_by_person_type",
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
        return indiv_nm_summary.empty()

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


@summary(
    id="tour_rates_by_person_type_and_tour_purpose",
    schema={
        "person_type": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "tour_rate": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "person_type", "finalweight"),
        "tours": ("person_id", "tour_purpose", "finalweight"),
    },
)
def tour_rate_per_person(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"person_id", "person_type", "finalweight"}
    tour_required = {"person_id", "tour_purpose", "finalweight"}

    if not person_required.issubset(set(rd.per.columns)) or not tour_required.issubset(
        set(rd.tours.columns)
    ):
        return tour_rate_per_person.empty()

    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return tour_rate_per_person.empty()

    weighted_person_days = (
        _person_exposure_records(rd)
        .group_by("person_type")
        .agg(weighted_person_days=pl.col("person_weight").sum())
    )

    weighted_tours = (
        rd.tours.filter(
            pl.col("person_id").is_not_null()
            & pl.col(purpose_col).is_not_null()
            & pl.col("finalweight").is_not_null()
        )
        .join(
            rd.per.filter(
                pl.col("person_id").is_not_null()
                & pl.col("person_type").is_not_null()
            ).select(
                "person_id",
                pl.col("person_type").cast(pl.Utf8),
            ),
            on="person_id",
            how="inner",
        )
        .group_by(["person_type", purpose_col])
        .agg(weighted_tours=pl.col("finalweight").cast(pl.Float64).sum())
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


@summary(
    id="trip_rates_by_person_type_and_trip_purpose",
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
        return trip_rate_per_person.empty()

    person_totals = (
        _person_exposure_records(rd)
        .group_by("person_type")
        .agg(person_count=pl.col("person_weight").sum())
        .with_columns(pl.col("person_type").cast(pl.Utf8))
    )

    trip_totals = (
        rd.trips.filter(
            pl.col("person_id").is_not_null()
            & pl.col("trip_purpose").is_not_null()
            & pl.col("finalweight").is_not_null()
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
