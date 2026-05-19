"""Escort count and household summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.daily_travel_escort_shared import (
    _adult_escorted_tours_with_household,
    _adult_side_escorted_tours,
    _both_escort_labels_present,
    _escort_label_present,
    _escort_type_expr,
    _student_households,
    _student_school_tours,
    _student_school_tours_with_household,
)
from processor.summarize.summaries.summary_helpers import _summary_purpose_column
from runtime.config import Config


@summary_contract(
    schema={"tour_count": pl.Float64},
    required_columns={
        "tours": ("school_esc_outbound", "school_esc_inbound", "finalweight")
    },
)
def total_escorted_tours(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame({"tour_count": [0.0]}, schema={"tour_count": pl.Float64})

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return pl.DataFrame({"tour_count": [0.0]}, schema={"tour_count": pl.Float64})

    return escorted.select(
        pl.col("finalweight").sum().cast(pl.Float64).alias("tour_count")
    )


@summary_contract(
    schema={"escort_type": pl.Utf8, "direction": pl.Utf8, "tour_count": pl.Float64},
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
        school_tours.filter(_escort_label_present("school_esc_outbound"))
        .group_by("school_esc_outbound")
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({"school_esc_outbound": "escort_type"})
        .with_columns(pl.lit("outbound").alias("direction"))
    )
    inbound = (
        school_tours.filter(_escort_label_present("school_esc_inbound"))
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
                ).filter(_escort_label_present("escort_type")),
                school_tours.select(
                    pl.col("school_esc_inbound").alias("escort_type"),
                    pl.col("finalweight"),
                ).filter(_escort_label_present("escort_type")),
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
    schema={"tour_purpose": pl.Utf8, "direction": pl.Utf8, "tour_count": pl.Float64},
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
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(adult_escorted_tour_purposes_by_direction)

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(adult_escorted_tour_purposes_by_direction)

    purpose_col = _summary_purpose_column(escorted)
    if not purpose_col:
        return empty_summary_frame(adult_escorted_tour_purposes_by_direction)

    outbound = (
        escorted.filter(
            _escort_label_present("school_esc_outbound") & pl.col(purpose_col).is_not_null()
        )
        .group_by(purpose_col)
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
        .with_columns(pl.lit("outbound").alias("direction"))
    )
    inbound = (
        escorted.filter(
            _escort_label_present("school_esc_inbound") & pl.col(purpose_col).is_not_null()
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
                    & _escort_label_present("school_esc_outbound")
                )
                .select("tour_purpose", "finalweight"),
                escorted.select(
                    pl.col("school_esc_inbound"),
                    pl.col(purpose_col).alias("tour_purpose"),
                    pl.col("finalweight"),
                )
                .filter(
                    pl.col("tour_purpose").is_not_null()
                    & _escort_label_present("school_esc_inbound")
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
    schema={"person_type": pl.Utf8, "direction": pl.Utf8, "tour_count": pl.Float64},
    required_columns={
        "tours": ("school_esc_outbound", "school_esc_inbound", "finalweight")
    },
)
def adult_escorted_tours_by_person_type_and_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
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
        escorted.filter(_escort_label_present("school_esc_outbound"))
        .group_by("person_type")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(pl.lit("outbound").alias("direction"))
    )
    inbound = (
        escorted.filter(_escort_label_present("school_esc_inbound"))
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
    schema={"direction": pl.Utf8, "escort_type": pl.Utf8, "tour_count": pl.Float64},
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
    required = {"school_esc_outbound", "school_esc_inbound", "finalweight"}
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
    schema={"student_count": pl.Int64, "household_count": pl.Float64},
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
    schema={"student_count": pl.Int64, "direction": pl.Utf8, "household_count": pl.Float64},
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
        "tours": ("school_esc_outbound", "school_esc_inbound", "num_escortees", "finalweight"),
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

    def _aggregate_direction(direction: str, direction_filter: pl.Expr) -> pl.DataFrame:
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
                _aggregate_direction("outbound", _escort_label_present("school_esc_outbound")),
                _aggregate_direction("inbound", _escort_label_present("school_esc_inbound")),
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
