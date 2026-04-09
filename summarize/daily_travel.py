"""Daily Travel summaries."""

import polars as pl

from .reader import RunData, Config


def dap_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """DAP by person type. Columns: person_type, daily_activity_pattern, person_count"""
    ptype_col = config.col_ptype

    if ptype_col not in rd.per.columns or "cdap_activity" not in rd.per.columns:
        return pl.DataFrame(
            {
                "person_type": [],
                "daily_activity_pattern": [],
                "person_count": [],
            }
        )

    df = (
        rd.per.filter(pl.col("cdap_activity").is_not_null())
        .group_by([ptype_col, "cdap_activity"])
        .agg(person_count=pl.col("finalweight").sum())
        .rename(
            {
                ptype_col: "person_type",
                "cdap_activity": "daily_activity_pattern",
            }
        )
        .with_columns(pl.col("person_type").cast(pl.Utf8))
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


def mandatory_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, mandatory_tour_frequency, person_count."""
    ptype_col = config.col_ptype

    if ptype_col not in rd.per.columns or "imf_choice" not in rd.per.columns:
        return pl.DataFrame(
            {
                "person_type": [],
                "mandatory_tour_frequency": [],
                "person_count": [],
            }
        )

    df = (
        rd.per.filter(pl.col("imf_choice") > 0)
        .group_by([ptype_col, "imf_choice"])
        .agg(person_count=pl.col("finalweight").sum())
        .rename(
            {
                ptype_col: "person_type",
                "imf_choice": "mandatory_tour_frequency",
            }
        )
        .with_columns(pl.col("person_type").cast(pl.Utf8))
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


def indiv_nm_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: person_type, nonmandatory_tour_frequency, person_count."""
    per = rd.per
    ptype_col = config.col_ptype

    if ptype_col not in per.columns:
        return pl.DataFrame(
            {
                "person_type": [],
                "nonmandatory_tour_frequency": [],
                "person_count": [],
            }
        )

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
        per2.group_by([ptype_col, "nonmandatory_tour_frequency"])
        .agg(person_count=pl.col("finalweight").sum())
        .rename({ptype_col: "person_type"})
        .with_columns(pl.col("person_type").cast(pl.Utf8))
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


def total_escorted_tours(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def escorted_tours_to_from_school(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def tour_rate_per_person(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def trip_rate_per_person(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()
