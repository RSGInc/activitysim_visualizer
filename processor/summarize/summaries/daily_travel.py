"""Daily Travel summaries."""

import polars as pl

from runtime.config import Config
from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.tour_purpose_helpers import (
    purpose_column,
)


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

    total = (
        df.group_by("daily_activity_pattern")
        .agg(person_count=pl.col("person_count").sum())
        .with_columns(pl.lit("all_person_types").alias("person_type"))
        .select("person_type", "daily_activity_pattern", "person_count")
    )

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

    total = (
        df.group_by("mandatory_tour_frequency")
        .agg(person_count=pl.col("person_count").sum())
        .with_columns(pl.lit("all_person_types").alias("person_type"))
        .select("person_type", "mandatory_tour_frequency", "person_count")
    )

    return pl.concat([df, total], how="vertical").sort(
        ["person_type", "mandatory_tour_frequency"]
    )


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "nonmandatory_tour_frequency": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_id", "person_type", "finalweight")},
)
def indiv_nm_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, nonmandatory_tour_frequency, person_count."""
    per = rd.per
    if "person_type" not in per.columns:
        return empty_summary_frame(indiv_nm_summary)

    if "tour_category" in rd.tours.columns:
        inm_counts = (
            rd.tours.filter(pl.col("tour_category") == "non-mandatory")
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

    total = (
        df.group_by("nonmandatory_tour_frequency")
        .agg(person_count=pl.col("person_count").sum())
        .with_columns(pl.lit("all_person_types").alias("person_type"))
        .select("person_type", "nonmandatory_tour_frequency", "person_count")
    )

    return pl.concat([df, total], how="vertical").sort(
        ["person_type", "nonmandatory_tour_frequency"]
    )


@summary_contract(
    schema={
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": ("school_esc_outbound", "school_esc_inbound", "finalweight")
    },
)
def total_escorted_tours(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame(
            {"tour_count": [0.0]},
            schema={"tour_count": pl.Float64},
        )

    escorted = rd.tours.filter(
        pl.col("school_esc_outbound").is_not_null()
        | pl.col("school_esc_inbound").is_not_null()
    ).filter(
        (pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase() != "none")
        | (pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase() != "none")
    )

    if escorted.is_empty():
        return pl.DataFrame(
            {"tour_count": [0.0]},
            schema={"tour_count": pl.Float64},
        )

    return escorted.select(
        pl.col("finalweight").sum().cast(pl.Float64).alias("tour_count")
    )


# TODO: Verify how unescorted tours are tracked in tables
@summary_contract(
    schema={
        "escort_type": pl.Utf8,
        "direction": pl.Utf8,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "tour_purpose",
            "school_esc_outbound",
            "school_esc_inbound",
            "finalweight",
        )
    },
)
def escorted_tours_to_from_school(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "tour_purpose",
        "school_esc_outbound",
        "school_esc_inbound",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(escorted_tours_to_from_school)

    school_tours = rd.tours.filter(
        pl.col("tour_purpose").cast(pl.Utf8).str.to_lowercase() == "school"
    )

    if school_tours.is_empty():
        return empty_summary_frame(escorted_tours_to_from_school)

    outbound = (
        school_tours.filter(
            pl.col("school_esc_outbound").is_not_null()
            & (pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase() != "none")
        )
        .group_by("school_esc_outbound")
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({"school_esc_outbound": "escort_type"})
        .with_columns(pl.lit("outbound").alias("direction"))
    )

    inbound = (
        school_tours.filter(
            pl.col("school_esc_inbound").is_not_null()
            & (pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase() != "none")
        )
        .group_by("school_esc_inbound")
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({"school_esc_inbound": "escort_type"})
        .with_columns(pl.lit("inbound").alias("direction"))
    )

    all_directions = (
        pl.concat(
            [
                school_tours.select(
                    pl.col("school_esc_outbound").alias("escort_type"),
                    pl.col("finalweight"),
                ).filter(
                    pl.col("escort_type").is_not_null()
                    & (pl.col("escort_type").cast(pl.Utf8).str.to_lowercase() != "none")
                ),
                school_tours.select(
                    pl.col("school_esc_inbound").alias("escort_type"),
                    pl.col("finalweight"),
                ).filter(
                    pl.col("escort_type").is_not_null()
                    & (pl.col("escort_type").cast(pl.Utf8).str.to_lowercase() != "none")
                ),
            ],
            how="vertical",
        )
        .group_by("escort_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("all_directions").alias("direction"))
    )

    return (
        pl.concat([outbound, inbound, all_directions], how="vertical")
        .with_columns(
            pl.col("escort_type").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("escort_type", "direction", "tour_count")
        .sort(["escort_type", "direction"])
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

    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_rate_per_person)

    # Denominator:
    # Weighted person-days by person type.
    #
    # This assumes each row in rd.per represents one observed person-day.
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

    # Numerator:
    # Weighted tours by person type and tour purpose.
    #
    # Each tour contributes the person's weight once.
    # This preserves the intended person-day expansion logic.
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

    return (
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

    return (
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
