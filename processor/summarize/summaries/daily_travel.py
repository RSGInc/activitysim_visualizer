"""Daily Travel summaries."""

import polars as pl

from processor.models import RunData
from processor.tour_purpose import purpose_column
from processor.summarize.contracts import empty_summary_frame, summary_contract
from runtime.config import Config

_CHILD_PERSON_TYPES = {"6", "7", "8"}
_STUDENT_SCHOOL_ESCORT_TYPES = ("not_escorted", "pure_escort", "ride_share")
_EXPLICIT_ESCORT_TYPES = ("pure_escort", "ride_share")


def _parent_only_escorted_tours(rd: RunData) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame()

    tours = rd.tours
    if "person_type" not in tours.columns and {"person_id", "person_type"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "person_type"),
            on="person_id",
            how="left",
        )

    if "person_type" not in tours.columns:
        return tours

    return tours.filter(
        ~pl.col("person_type").cast(pl.Utf8).is_in(sorted(_CHILD_PERSON_TYPES))
    )


def _adult_side_escorted_tours(rd: RunData) -> pl.DataFrame:
    tours = _parent_only_escorted_tours(rd)
    if tours.is_empty():
        return tours

    escorted = tours.filter(
        pl.col("school_esc_outbound").is_not_null()
        | pl.col("school_esc_inbound").is_not_null()
    ).filter(
        (pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase() != "none")
        | (pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase() != "none")
    )

    if escorted.is_empty():
        return escorted

    purpose_col = purpose_column(escorted)
    if purpose_col is None:
        return escorted

    adult_escort = escorted.filter(
        pl.col(purpose_col).cast(pl.Utf8).str.to_lowercase() == "escort"
    )
    return adult_escort if not adult_escort.is_empty() else escorted


def _escort_type_matches(column: str, escort_type: str) -> pl.Expr:
    normalized = pl.col(column).cast(pl.Utf8).str.to_lowercase()
    if escort_type == "ride_share":
        return normalized.is_in(["ride_share", "rideshare", "ride share"])
    return normalized == escort_type


def _explicit_escort_label_present(column: str) -> pl.Expr:
    return _escort_type_matches(column, "pure_escort") | _escort_type_matches(
        column, "ride_share"
    )


def _adult_side_explicit_escorted_tours(rd: RunData) -> pl.DataFrame:
    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return escorted
    return escorted.filter(
        _explicit_escort_label_present("school_esc_outbound")
        | _explicit_escort_label_present("school_esc_inbound")
    )


def _student_school_tours(rd: RunData) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame()

    tours = rd.tours
    if "person_type" not in tours.columns and {"person_id", "person_type"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "person_type"),
            on="person_id",
            how="left",
        )

    if "person_type" not in tours.columns:
        return pl.DataFrame()

    purpose_col = purpose_column(tours)
    if purpose_col is None:
        return pl.DataFrame()

    return tours.filter(
        pl.col("person_type").cast(pl.Utf8).is_in(sorted(_CHILD_PERSON_TYPES))
        & (pl.col(purpose_col).cast(pl.Utf8).str.to_lowercase() == "school")
    )


def _student_households(rd: RunData) -> pl.DataFrame:
    hh_required = {"household_id", "finalweight"}
    per_required = {"household_id", "person_type"}
    if not hh_required.issubset(set(rd.hh.columns)) or not per_required.issubset(
        set(rd.per.columns)
    ):
        return pl.DataFrame()

    student_counts = (
        rd.per.filter(
            pl.col("household_id").is_not_null()
            & pl.col("person_type").cast(pl.Utf8).is_in(sorted(_CHILD_PERSON_TYPES))
        )
        .group_by("household_id")
        .agg(student_count=pl.len().cast(pl.Int64))
    )

    return (
        rd.hh.select("household_id", "finalweight")
        .join(student_counts, on="household_id", how="left")
        .with_columns(
            pl.col("student_count").fill_null(0).cast(pl.Int64),
            pl.col("finalweight").cast(pl.Float64),
        )
        .filter(pl.col("student_count") > 0)
    )


def _student_school_tours_with_household(rd: RunData) -> pl.DataFrame:
    tours = _student_school_tours(rd)
    if tours.is_empty():
        return tours

    if "household_id" not in tours.columns and {"person_id", "household_id"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "household_id"),
            on="person_id",
            how="left",
        )

    if "household_id" not in tours.columns:
        return pl.DataFrame()

    return tours.filter(pl.col("household_id").is_not_null())


def _adult_escorted_tours_with_household(rd: RunData) -> pl.DataFrame:
    tours = _adult_side_escorted_tours(rd)
    if tours.is_empty():
        return tours

    if "household_id" not in tours.columns and {"person_id", "household_id"}.issubset(
        set(rd.per.columns)
    ):
        tours = tours.join(
            rd.per.select("person_id", "household_id"),
            on="person_id",
            how="left",
        )

    if "household_id" not in tours.columns:
        return pl.DataFrame()

    return tours.filter(pl.col("household_id").is_not_null())


def _escort_type_expr(column: str) -> pl.Expr:
    normalized = pl.col(column).cast(pl.Utf8).str.to_lowercase()
    return (
        pl.when(pl.col(column).is_null() | (normalized == "none"))
        .then(pl.lit("not_escorted"))
        .when(normalized == "pure_escort")
        .then(pl.lit("pure_escort"))
        .when(normalized.is_in(["ride_share", "rideshare", "ride share"]))
        .then(pl.lit("ride_share"))
        .otherwise(pl.lit("ride_share"))
    )


def _escort_label_present(column: str) -> pl.Expr:
    return pl.col(column).is_not_null() & (
        pl.col(column).cast(pl.Utf8).str.to_lowercase() != "none"
    )


def _both_escort_labels_present() -> pl.Expr:
    return _escort_label_present("school_esc_outbound") & _escort_label_present(
        "school_esc_inbound"
    )


def _both_explicit_escort_labels_present() -> pl.Expr:
    return _explicit_escort_label_present(
        "school_esc_outbound"
    ) & _explicit_escort_label_present("school_esc_inbound")


def _distance_bin_expr(column: str) -> pl.Expr:
    rounded = pl.col(column).cast(pl.Float64).round(0)
    return (
        pl.when(rounded >= 40)
        .then(pl.lit("40+"))
        .otherwise(rounded.cast(pl.Int64, strict=False).cast(pl.Utf8))
        .alias("distance_bin")
    )


def _trip_direction_expr(df: pl.DataFrame) -> pl.Expr | None:
    if "inbound" in df.columns:
        return (
            pl.when(
                pl.col("inbound").cast(pl.Utf8).str.to_lowercase().is_in(["1", "true"])
            )
            .then(pl.lit("inbound"))
            .otherwise(pl.lit("outbound"))
            .alias("direction")
        )
    if "outbound" in df.columns:
        return (
            pl.when(
                pl.col("outbound")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["false", "0"])
            )
            .then(pl.lit("inbound"))
            .otherwise(pl.lit("outbound"))
            .alias("direction")
        )
    return None


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

    escorted = _adult_side_escorted_tours(rd)

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

    school_tours = _adult_side_escorted_tours(rd)

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
        "tour_purpose": pl.Utf8,
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
def adult_escorted_tour_purposes_by_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    required = {
        "school_esc_outbound",
        "school_esc_inbound",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(adult_escorted_tour_purposes_by_direction)

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(adult_escorted_tour_purposes_by_direction)

    purpose_col = purpose_column(escorted)
    if purpose_col is None:
        return empty_summary_frame(adult_escorted_tour_purposes_by_direction)

    outbound = (
        escorted.filter(
            pl.col("school_esc_outbound").is_not_null()
            & (pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase() != "none")
            & pl.col(purpose_col).is_not_null()
        )
        .group_by(purpose_col)
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
        .with_columns(pl.lit("outbound").alias("direction"))
    )

    inbound = (
        escorted.filter(
            pl.col("school_esc_inbound").is_not_null()
            & (pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase() != "none")
            & pl.col(purpose_col).is_not_null()
        )
        .group_by(purpose_col)
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
        .with_columns(pl.lit("inbound").alias("direction"))
    )

    all_directions = (
        pl.concat(
            [
                escorted.select(
                    pl.col("school_esc_outbound"),
                    pl.col(purpose_col).alias("tour_purpose"),
                    pl.col("finalweight"),
                )
                .filter(
                    pl.col("tour_purpose").is_not_null()
                    & pl.col("school_esc_outbound").is_not_null()
                    & (
                        pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase()
                        != "none"
                    )
                )
                .select("tour_purpose", "finalweight"),
                escorted.select(
                    pl.col("school_esc_inbound"),
                    pl.col(purpose_col).alias("tour_purpose"),
                    pl.col("finalweight"),
                )
                .filter(
                    pl.col("tour_purpose").is_not_null()
                    & pl.col("school_esc_inbound").is_not_null()
                    & (
                        pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase()
                        != "none"
                    )
                )
                .select("tour_purpose", "finalweight"),
            ],
            how="vertical",
        )
        .group_by("tour_purpose")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("all_directions").alias("direction"))
    )

    return (
        pl.concat([outbound, inbound, all_directions], how="vertical")
        .with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("tour_purpose", "direction", "tour_count")
        .sort(["tour_purpose", "direction"])
    )


@summary_contract(
    schema={
        "person_type": pl.Utf8,
        "direction": pl.Utf8,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "school_esc_outbound",
            "school_esc_inbound",
            "finalweight",
        )
    },
)
def adult_escorted_tours_by_person_type_and_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    required = {
        "school_esc_outbound",
        "school_esc_inbound",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(adult_escorted_tours_by_person_type_and_direction)

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty() or "person_type" not in escorted.columns:
        return empty_summary_frame(adult_escorted_tours_by_person_type_and_direction)

    escorted = escorted.filter(pl.col("person_type").is_not_null()).with_columns(
        pl.col("person_type").cast(pl.Utf8)
    )
    if escorted.is_empty():
        return empty_summary_frame(adult_escorted_tours_by_person_type_and_direction)

    outbound = (
        escorted.filter(
            pl.col("school_esc_outbound").is_not_null()
            & (pl.col("school_esc_outbound").cast(pl.Utf8).str.to_lowercase() != "none")
        )
        .group_by("person_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("outbound").alias("direction"))
    )

    inbound = (
        escorted.filter(
            pl.col("school_esc_inbound").is_not_null()
            & (pl.col("school_esc_inbound").cast(pl.Utf8).str.to_lowercase() != "none")
        )
        .group_by("person_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("inbound").alias("direction"))
    )

    both = (
        escorted.filter(_both_escort_labels_present())
        .group_by("person_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("both").alias("direction"))
    )

    return (
        pl.concat([outbound, inbound, both], how="vertical")
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("person_type", "direction", "tour_count")
        .sort(["person_type", "direction"])
    )


@summary_contract(
    schema={
        "direction": pl.Utf8,
        "escort_type": pl.Utf8,
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
def student_school_escort_status_by_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    required = {
        "school_esc_outbound",
        "school_esc_inbound",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(student_school_escort_status_by_direction)

    student_school_tours = _student_school_tours(rd)
    if student_school_tours.is_empty():
        return empty_summary_frame(student_school_escort_status_by_direction)

    base = student_school_tours.with_columns(
        pl.col("finalweight").cast(pl.Float64),
        _escort_type_expr("school_esc_outbound").alias("_outbound_escort_type"),
        _escort_type_expr("school_esc_inbound").alias("_inbound_escort_type"),
    )

    outbound = (
        base.group_by("_outbound_escort_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({"_outbound_escort_type": "escort_type"})
        .with_columns(pl.lit("outbound").alias("direction"))
    )

    inbound = (
        base.group_by("_inbound_escort_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({"_inbound_escort_type": "escort_type"})
        .with_columns(pl.lit("inbound").alias("direction"))
    )

    both = (
        base.filter(
            _escort_label_present("school_esc_outbound")
            & _escort_label_present("school_esc_inbound")
        )
        .with_columns(
            pl.when(pl.col("_outbound_escort_type") == pl.col("_inbound_escort_type"))
            .then(pl.col("_outbound_escort_type"))
            .otherwise(pl.lit("ride_share"))
            .alias("escort_type")
        )
        .group_by("escort_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("both").alias("direction"))
    )

    return (
        pl.concat([outbound, inbound, both], how="vertical")
        .with_columns(
            pl.col("direction").cast(pl.Utf8),
            pl.col("escort_type").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("direction", "escort_type", "tour_count")
        .sort(["direction", "escort_type"])
    )


@summary_contract(
    schema={
        "student_count": pl.Int64,
        "household_count": pl.Float64,
    },
    required_columns={
        "hh": ("household_id", "finalweight"),
        "per": ("household_id", "person_type"),
    },
)
def student_households_by_student_count(rd: RunData, config: Config) -> pl.DataFrame:
    households = _student_households(rd)
    if households.is_empty():
        return empty_summary_frame(student_households_by_student_count)

    return (
        households.group_by("student_count")
        .agg(household_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("student_count").cast(pl.Int64),
            pl.col("household_count").cast(pl.Float64),
        )
        .sort("student_count")
    )


@summary_contract(
    schema={
        "student_count": pl.Int64,
        "direction": pl.Utf8,
        "household_count": pl.Float64,
    },
    required_columns={
        "hh": ("household_id", "finalweight"),
        "per": ("household_id", "person_type"),
        "tours": (
            "tour_purpose",
            "school_esc_outbound",
            "school_esc_inbound",
            "finalweight",
        ),
    },
)
def households_with_school_escorting_by_student_count_and_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    households = _student_households(rd)
    if households.is_empty():
        return empty_summary_frame(
            households_with_school_escorting_by_student_count_and_direction
        )

    student_tours = _student_school_tours_with_household(rd)
    direction_frames: list[pl.DataFrame] = []
    all_counts = households.select("student_count").unique().sort("student_count")

    if not student_tours.is_empty():
        outbound_households = (
            student_tours.filter(_escort_label_present("school_esc_outbound"))
            .select("household_id")
            .unique()
        )
        inbound_households = (
            student_tours.filter(_escort_label_present("school_esc_inbound"))
            .select("household_id")
            .unique()
        )
        both_households = (
            student_tours.filter(
                _escort_label_present("school_esc_outbound")
                & _escort_label_present("school_esc_inbound")
            )
            .select("household_id")
            .unique()
        )
    else:
        outbound_households = pl.DataFrame(
            {"household_id": []}, schema={"household_id": pl.Int64}
        )
        inbound_households = pl.DataFrame(
            {"household_id": []}, schema={"household_id": pl.Int64}
        )
        both_households = pl.DataFrame(
            {"household_id": []}, schema={"household_id": pl.Int64}
        )

    for direction, household_ids in (
        ("outbound", outbound_households),
        ("inbound", inbound_households),
        ("both", both_households),
    ):
        counts = (
            households.join(household_ids, on="household_id", how="inner")
            .group_by("student_count")
            .agg(household_count=pl.col("finalweight").sum())
        )
        direction_frames.append(
            all_counts.join(counts, on="student_count", how="left")
            .with_columns(
                pl.lit(direction).alias("direction"),
                pl.col("household_count").fill_null(0.0).cast(pl.Float64),
            )
            .select("student_count", "direction", "household_count")
        )

    return (
        pl.concat(direction_frames, how="vertical")
        .with_columns(
            pl.col("student_count").cast(pl.Int64),
            pl.col("direction").cast(pl.Utf8),
            pl.col("household_count").cast(pl.Float64),
        )
        .sort(["direction", "student_count"])
    )


@summary_contract(
    schema={
        "student_count": pl.Int64,
        "direction": pl.Utf8,
        "avg_schoolkids_per_tour": pl.Float64,
        "tour_count": pl.Float64,
    },
    required_columns={
        "hh": ("household_id", "finalweight"),
        "per": ("household_id", "person_type"),
        "tours": (
            "school_esc_outbound",
            "school_esc_inbound",
            "num_escortees",
            "finalweight",
        ),
    },
)
def schoolkids_per_escorted_tour_by_student_count_and_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    households = _student_households(rd)
    if households.is_empty():
        return empty_summary_frame(
            schoolkids_per_escorted_tour_by_student_count_and_direction
        )

    escorted_tours = _adult_escorted_tours_with_household(rd)
    if escorted_tours.is_empty() or "num_escortees" not in escorted_tours.columns:
        return empty_summary_frame(
            schoolkids_per_escorted_tour_by_student_count_and_direction
        )

    base = (
        escorted_tours.filter(pl.col("num_escortees").is_not_null())
        .join(
            households.select("household_id", "student_count"),
            on="household_id",
            how="inner",
        )
        .with_columns(
            pl.col("student_count").cast(pl.Int64),
            pl.col("finalweight").cast(pl.Float64),
            pl.col("num_escortees").cast(pl.Float64),
        )
    )
    if base.is_empty():
        return empty_summary_frame(
            schoolkids_per_escorted_tour_by_student_count_and_direction
        )

    def _aggregate_direction(
        direction: str,
        direction_filter: pl.Expr,
    ) -> pl.DataFrame:
        filtered = base.filter(direction_filter)
        if filtered.is_empty():
            return pl.DataFrame(
                schema={
                    "student_count": pl.Int64,
                    "direction": pl.Utf8,
                    "avg_schoolkids_per_tour": pl.Float64,
                    "tour_count": pl.Float64,
                }
            )
        return (
            filtered.group_by("student_count")
            .agg(
                weighted_schoolkids=(
                    pl.col("num_escortees") * pl.col("finalweight")
                ).sum(),
                tour_count=pl.col("finalweight").sum(),
            )
            .with_columns(
                pl.lit(direction).alias("direction"),
                pl.when(pl.col("tour_count") > 0)
                .then(pl.col("weighted_schoolkids") / pl.col("tour_count"))
                .otherwise(0.0)
                .alias("avg_schoolkids_per_tour"),
            )
            .select(
                "student_count", "direction", "avg_schoolkids_per_tour", "tour_count"
            )
        )

    return (
        pl.concat(
            [
                _aggregate_direction(
                    "outbound",
                    _escort_label_present("school_esc_outbound"),
                ),
                _aggregate_direction(
                    "inbound",
                    _escort_label_present("school_esc_inbound"),
                ),
                _aggregate_direction(
                    "both",
                    _escort_label_present("school_esc_outbound")
                    & _escort_label_present("school_esc_inbound"),
                ),
            ],
            how="vertical",
        )
        .with_columns(
            pl.col("student_count").cast(pl.Int64),
            pl.col("direction").cast(pl.Utf8),
            pl.col("avg_schoolkids_per_tour").cast(pl.Float64),
            pl.col("tour_count").cast(pl.Float64),
        )
        .sort(["direction", "student_count"])
    )


@summary_contract(
    schema={
        "distance_bin": pl.Utf8,
        "direction": pl.Utf8,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "SKIMDIST",
            "school_esc_outbound",
            "school_esc_inbound",
            "finalweight",
        )
    },
)
def adult_escorted_tour_distance_distribution_by_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    required = {
        "SKIMDIST",
        "school_esc_outbound",
        "school_esc_inbound",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(
            adult_escorted_tour_distance_distribution_by_direction
        )

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(
            adult_escorted_tour_distance_distribution_by_direction
        )

    base = escorted.filter(pl.col("SKIMDIST").is_not_null()).with_columns(
        _distance_bin_expr("SKIMDIST")
    )
    if base.is_empty():
        return empty_summary_frame(
            adult_escorted_tour_distance_distribution_by_direction
        )

    outbound = (
        base.filter(_explicit_escort_label_present("school_esc_outbound"))
        .group_by("distance_bin")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("outbound").alias("direction"))
    )

    inbound = (
        base.filter(_explicit_escort_label_present("school_esc_inbound"))
        .group_by("distance_bin")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("inbound").alias("direction"))
    )

    both = (
        base.filter(_both_explicit_escort_labels_present())
        .group_by("distance_bin")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("both").alias("direction"))
    )

    return (
        pl.concat([outbound, inbound, both], how="vertical")
        .with_columns(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
            pl.when(pl.col("distance_bin") == "40+")
            .then(999)
            .otherwise(pl.col("distance_bin").cast(pl.Int64, strict=False))
            .alias("_sort_distance"),
        )
        .select("distance_bin", "direction", "tour_count", "_sort_distance")
        .sort(["direction", "_sort_distance"])
        .select("distance_bin", "direction", "tour_count")
    )


@summary_contract(
    schema={
        "distance_bin": pl.Utf8,
        "direction": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={
        "tours": ("tour_id", "school_esc_outbound", "school_esc_inbound"),
        "trips": ("tour_id", "od_dist", "finalweight"),
    },
)
def adult_escorted_trip_distance_distribution_by_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    if "tour_id" not in rd.tours.columns or "tour_id" not in rd.trips.columns:
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    direction_expr = _trip_direction_expr(rd.trips)
    if direction_expr is None:
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    escorted_tours = _adult_side_explicit_escorted_tours(rd)
    if escorted_tours.is_empty():
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    escorted_trip_ids = escorted_tours.select(
        "tour_id", "school_esc_outbound", "school_esc_inbound"
    ).unique()
    trips = rd.trips.join(escorted_trip_ids, on="tour_id", how="inner")
    if (
        trips.is_empty()
        or "od_dist" not in trips.columns
        or "finalweight" not in trips.columns
    ):
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    base = trips.filter(pl.col("od_dist").is_not_null()).with_columns(
        direction_expr,
        _distance_bin_expr("od_dist"),
    )
    if base.is_empty():
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    outbound = (
        base.filter(
            (pl.col("direction") == "outbound")
            & _explicit_escort_label_present("school_esc_outbound")
        )
        .group_by("distance_bin")
        .agg(trip_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("outbound").alias("direction"))
        .select("distance_bin", "direction", "trip_count")
    )

    inbound = (
        base.filter(
            (pl.col("direction") == "inbound")
            & _explicit_escort_label_present("school_esc_inbound")
        )
        .group_by("distance_bin")
        .agg(trip_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("inbound").alias("direction"))
        .select("distance_bin", "direction", "trip_count")
    )

    both = (
        base.filter(_both_explicit_escort_labels_present())
        .group_by("distance_bin")
        .agg(trip_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("both").alias("direction"))
        .select("distance_bin", "direction", "trip_count")
    )

    return (
        pl.concat([outbound, inbound, both], how="vertical")
        .with_columns(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
            pl.when(pl.col("distance_bin") == "40+")
            .then(999)
            .otherwise(pl.col("distance_bin").cast(pl.Int64, strict=False))
            .alias("_sort_distance"),
        )
        .select("distance_bin", "direction", "trip_count", "_sort_distance")
        .sort(["direction", "_sort_distance"])
        .select("distance_bin", "direction", "trip_count")
    )

@summary_contract(
    schema={
        "segment": pl.Utf8,
        "stop_count": pl.Int32,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": ("tour_id", "school_esc_outbound", "school_esc_inbound"),
        "trips": (
            "tour_id",
            "escort_event_role",
            "escort_stops_before_event",
            "escort_stops_after_event",
            "finalweight",
        ),
    },
)
def adult_escort_event_stop_distribution(rd: RunData, config: Config) -> pl.DataFrame:
    if "tour_id" not in rd.tours.columns or "tour_id" not in rd.trips.columns:
        return empty_summary_frame(adult_escort_event_stop_distribution)

    escorted = _adult_side_explicit_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    required_trip_cols = {
        "tour_id",
        "escort_event_role",
        "escort_stops_before_event",
        "escort_stops_after_event",
        "finalweight",
    }
    if not required_trip_cols.issubset(set(rd.trips.columns)):
        return empty_summary_frame(adult_escort_event_stop_distribution)

    escorted_trip_ids = escorted.select(
        "tour_id", "school_esc_outbound", "school_esc_inbound"
    ).unique()
    trips = rd.trips.join(escorted_trip_ids, on="tour_id", how="inner")
    if trips.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    events = (
        trips.filter(pl.col("escort_event_role").is_not_null())
        .with_columns(
            pl.col("escort_event_role").cast(pl.Utf8).str.to_lowercase(),
            pl.col("escort_stops_before_event").cast(pl.Int32),
            pl.col("escort_stops_after_event").cast(pl.Int32),
            pl.col("finalweight").cast(pl.Float64),
        )
        .filter(pl.col("escort_event_role").is_in(["dropoff", "pickup"]))
        .filter(
            (
                (pl.col("escort_event_role") == "dropoff")
                & _explicit_escort_label_present("school_esc_outbound")
            )
            | (
                (pl.col("escort_event_role") == "pickup")
                & _explicit_escort_label_present("school_esc_inbound")
            )
        )
    )
    if events.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    empty_segment_schema = {
        "segment": pl.Utf8,
        "stop_count": pl.Int32,
        "tour_count": pl.Float64,
    }

    def _segment_counts(segment: str, stop_col: str, role: str) -> pl.DataFrame:
        filtered = events.filter(pl.col("escort_event_role") == role)
        if filtered.is_empty():
            return pl.DataFrame(schema=empty_segment_schema)
        return (
            filtered.group_by(stop_col)
            .agg(tour_count=pl.col("finalweight").sum())
            .rename({stop_col: "stop_count"})
            .with_columns(pl.lit(segment).alias("segment"))
            .select("segment", "stop_count", "tour_count")
        )

    result = pl.concat(
        [
            _segment_counts(
                "outbound_before_dropoff", "escort_stops_before_event", "dropoff"
            ),
            _segment_counts(
                "outbound_after_dropoff", "escort_stops_after_event", "dropoff"
            ),
            _segment_counts(
                "inbound_before_pickup", "escort_stops_before_event", "pickup"
            ),
            _segment_counts(
                "inbound_after_pickup", "escort_stops_after_event", "pickup"
            ),
        ],
        how="vertical",
    )
    if result.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    return (
        result.with_columns(
            pl.col("segment").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Int32),
            pl.col("tour_count").cast(pl.Float64),
        )
        .sort(["segment", "stop_count"])
        .select("segment", "stop_count", "tour_count")
    )


@summary_contract(
    schema={
        "tour_purpose": pl.Utf8,
        "outbound_stop_count": pl.Int32,
        "inbound_stop_count": pl.Int32,
        "total_stop_count": pl.Int32,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "tour_purpose",
            "school_esc_outbound",
            "school_esc_inbound",
            "num_ob_stops",
            "num_ib_stops",
            "num_tot_stops",
            "finalweight",
        )
    },
)
def adult_escort_trip_stop_frequency(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "school_esc_outbound",
        "school_esc_inbound",
        "num_ob_stops",
        "num_ib_stops",
        "num_tot_stops",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(adult_escort_trip_stop_frequency)

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(adult_escort_trip_stop_frequency)

    purpose_col = purpose_column(escorted)
    if not purpose_col:
        return empty_summary_frame(adult_escort_trip_stop_frequency)

    return (
        escorted.filter(pl.col(purpose_col).is_not_null())
        .with_columns(
            [
                pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
                pl.col("num_ob_stops")
                .clip(0, 3)
                .cast(pl.Int32)
                .alias("outbound_stop_count"),
                pl.col("num_ib_stops")
                .clip(0, 3)
                .cast(pl.Int32)
                .alias("inbound_stop_count"),
                pl.col("num_tot_stops")
                .clip(0, 6)
                .cast(pl.Int32)
                .alias("total_stop_count"),
            ]
        )
        .group_by(
            [
                "tour_purpose",
                "outbound_stop_count",
                "inbound_stop_count",
                "total_stop_count",
            ]
        )
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.col("tour_count").cast(pl.Float64))
        .select(
            "tour_purpose",
            "outbound_stop_count",
            "inbound_stop_count",
            "total_stop_count",
            "tour_count",
        )
        .sort(
            [
                "tour_purpose",
                "outbound_stop_count",
                "inbound_stop_count",
                "total_stop_count",
            ]
        )
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
