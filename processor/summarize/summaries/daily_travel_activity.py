"""Activity-pattern and rate daily travel summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    _all_person_types_rollup,
    _summary_purpose_column,
    joint_participant_weight_expr,
)
from runtime.config import Config


def _person_exposure_records(rd: RunData) -> pl.DataFrame:
    persons = rd.per.filter(
        pl.col("person_id").is_not_null()
        & pl.col("person_type").is_not_null()
        & pl.col("finalweight").is_not_null()
    )
    if "surveyable" in persons.columns:
        surveyable = (
            pl.col("surveyable")
            .cast(pl.Utf8)
            .str.strip_chars()
            .str.to_lowercase()
            .is_in(["1", "true", "yes", "y"])
        )
        persons = persons.filter(pl.col("surveyable").is_null() | surveyable)
    persons = persons.select(
        "person_id",
        pl.col("person_type").cast(pl.Utf8),
        pl.col("finalweight").cast(pl.Float64).alias("person_weight"),
    )

    if not rd.day.is_empty() and "person_id" in rd.day.columns:
        day_weight = (
            pl.col("finalweight").cast(pl.Float64).alias("_day_weight")
            if "finalweight" in rd.day.columns
            else pl.lit(None, dtype=pl.Float64).alias("_day_weight")
        )
        return (
            rd.day.filter(pl.col("person_id").is_not_null())
            .select("person_id", day_weight)
            .join(persons, on="person_id", how="inner")
            .with_columns(
                pl.coalesce("_day_weight", "person_weight").alias("person_weight")
            )
            .select("person_id", "person_type", "person_weight")
        )

    return persons


def _day_person_records(rd: RunData, *day_columns: str) -> pl.DataFrame:
    """Return every attributable day row with its day or person weight."""
    person_columns = rd.per.select(
        "person_id",
        pl.col("person_type").cast(pl.Utf8),
        pl.col("finalweight").cast(pl.Float64).alias("_person_weight"),
    )
    day_weight = (
        pl.col("finalweight").cast(pl.Float64).alias("_day_weight")
        if "finalweight" in rd.day.columns
        else pl.lit(None, dtype=pl.Float64).alias("_day_weight")
    )
    return (
        rd.day.filter(pl.col("person_id").is_not_null())
        .select("person_id", *day_columns, day_weight)
        .join(person_columns, on="person_id", how="inner")
        .with_columns(pl.coalesce("_day_weight", "_person_weight").alias("finalweight"))
        .select("person_id", "person_type", *day_columns, "finalweight")
    )


def _weighted_activity_by_person_type(
    rd: RunData,
    activity: pl.DataFrame,
    *,
    purpose_col: str,
    participant_col: str,
) -> pl.DataFrame:
    base = activity.filter(
        pl.col(purpose_col).is_not_null() & pl.col("finalweight").is_not_null()
    )

    def _scalar_rows(rows: pl.DataFrame) -> pl.DataFrame:
        return rows.with_columns(
            pl.col("person_id").alias("_rate_person_id"),
            joint_participant_weight_expr(
                rows,
                participant_col=participant_col,
                output_col="activity_weight",
            ),
        ).select(
            "_rate_person_id",
            pl.col(purpose_col).cast(pl.Utf8).alias("activity_purpose"),
            "activity_weight",
        )

    weighted_rows = _scalar_rows(base)
    participant_required = {"tour_id", "person_id"}
    can_attribute_participants = (
        "tour_id" in base.columns
        and "tour_category" in base.columns
        and participant_required.issubset(rd.joint_participants.columns)
        and not rd.joint_participants.is_empty()
    )
    if can_attribute_participants:
        participants = (
            rd.joint_participants.filter(
                pl.col("tour_id").is_not_null() & pl.col("person_id").is_not_null()
            )
            .select(
                "tour_id",
                pl.col("person_id").alias("_rate_person_id"),
            )
            .join(
                rd.per.filter(pl.col("person_id").is_not_null()).select(
                    pl.col("person_id").alias("_rate_person_id"),
                    pl.col("finalweight").cast(pl.Float64).alias("_participant_weight"),
                ),
                on="_rate_person_id",
                how="left",
            )
        )
        participant_tour_ids = participants.select("tour_id")
        category = (
            pl.col("tour_category").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        )
        joint_record = (
            pl.col("tour_category").is_not_null() & (category == "joint")
        ).fill_null(False)
        participant_rows = (
            base.filter(joint_record)
            .join(participants, on="tour_id", how="inner")
            .select(
                "_rate_person_id",
                pl.col(purpose_col).cast(pl.Utf8).alias("activity_purpose"),
                pl.coalesce(
                    pl.col("_participant_weight"),
                    pl.col("finalweight").cast(pl.Float64),
                ).alias("activity_weight"),
            )
        )
        scalar_rows = pl.concat(
            [
                base.filter(~joint_record),
                base.filter(joint_record).join(
                    participant_tour_ids,
                    on="tour_id",
                    how="anti",
                ),
            ],
            how="vertical",
        )
        weighted_rows = pl.concat(
            [_scalar_rows(scalar_rows), participant_rows],
            how="vertical",
        )

    eligible_people = _person_exposure_records(rd).select(
        pl.col("person_id").alias("_rate_person_id")
    ).unique()
    return (
        weighted_rows.join(eligible_people, on="_rate_person_id", how="semi")
        .join(
            rd.per.filter(
                pl.col("person_id").is_not_null() & pl.col("person_type").is_not_null()
            ).select(
                pl.col("person_id").alias("_rate_person_id"),
                pl.col("person_type").cast(pl.Utf8),
            ),
            on="_rate_person_id",
            how="inner",
        )
        .group_by(["person_type", "activity_purpose"])
        .agg(activity_count=pl.col("activity_weight").sum())
    )


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

    sources: list[pl.DataFrame] = []
    person_choice_ids: pl.DataFrame | None = None
    if person_activity_required.issubset(rd.per.columns):
        person_choices = rd.per.filter(pl.col("cdap_activity").is_not_null())
        if not person_choices.is_empty():
            sources.append(
                person_choices.select("person_type", "cdap_activity", "finalweight")
            )
            if "person_id" in rd.per.columns:
                person_choice_ids = person_choices.filter(
                    pl.col("person_id").is_not_null()
                ).select("person_id")

    can_use_days = (
        not rd.day.is_empty()
        and day_required.issubset(rd.day.columns)
        and person_required.issubset(rd.per.columns)
    )
    if can_use_days:
        day_choices = _day_person_records(rd, "cdap_activity").filter(
            pl.col("cdap_activity").is_not_null()
        )
        if person_choice_ids is not None:
            day_choices = day_choices.join(
                person_choice_ids, on="person_id", how="anti"
            )
        sources.append(
            day_choices.select("person_type", "cdap_activity", "finalweight")
        )

    if not sources:
        return dap_summary.empty()
    source = pl.concat(sources, how="vertical_relaxed")

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
    person_required = {"person_id", "person_type", "finalweight"}
    day_required = {"person_id", "day_id"}
    tour_required = {"person_id", "day_id"}
    purpose_col = _summary_purpose_column(rd.tours)

    sources: list[pl.DataFrame] = []
    person_choice_ids: pl.DataFrame | None = None
    if person_choice_required.issubset(rd.per.columns):
        person_choices = rd.per.filter(pl.col("imf_choice").is_not_null())
        if not person_choices.is_empty():
            sources.append(
                person_choices.select(
                    "person_type",
                    pl.col("imf_choice").cast(pl.Int32, strict=False),
                    "finalweight",
                )
            )
            if "person_id" in rd.per.columns:
                person_choice_ids = person_choices.filter(
                    pl.col("person_id").is_not_null()
                ).select("person_id")

    can_derive_days = (
        person_required.issubset(rd.per.columns)
        and day_required.issubset(rd.day.columns)
        and tour_required.issubset(rd.tours.columns)
        and purpose_col is not None
    )
    if can_derive_days:
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

        day_choices = (
            _day_person_records(rd, "day_id")
            .filter(pl.col("day_id").is_not_null())
            .join(tour_counts, on=["person_id", "day_id"], how="left")
            .with_columns(
                pl.col("_work_tours").fill_null(0),
                pl.col("_school_tours").fill_null(0),
            )
            .with_columns(
                pl.when((pl.col("_work_tours") == 0) & (pl.col("_school_tours") == 0))
                .then(pl.lit(0))
                .when((pl.col("_work_tours") == 1) & (pl.col("_school_tours") == 0))
                .then(pl.lit(1))
                .when((pl.col("_work_tours") == 2) & (pl.col("_school_tours") == 0))
                .then(pl.lit(2))
                .when((pl.col("_work_tours") == 0) & (pl.col("_school_tours") == 1))
                .then(pl.lit(3))
                .when((pl.col("_work_tours") == 0) & (pl.col("_school_tours") == 2))
                .then(pl.lit(4))
                .when((pl.col("_work_tours") == 1) & (pl.col("_school_tours") == 1))
                .then(pl.lit(5))
                .otherwise(None)
                .alias("imf_choice")
            )
        )
        if person_choice_ids is not None:
            day_choices = day_choices.join(
                person_choice_ids, on="person_id", how="anti"
            )
        sources.append(day_choices.select("person_type", "imf_choice", "finalweight"))

    if not sources:
        return mandatory_tour_freq.empty()
    source = pl.concat(sources, how="vertical_relaxed")

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
    """Return nonmandatory frequency by person-day when day keys are safe.

    Multi-day data falls back to the legacy person-level calculation when any
    joint-participant row cannot be assigned to a day without guessing.
    """
    per = rd.per
    if "person_type" not in per.columns:
        return indiv_nm_summary.empty()

    if "tour_category" in rd.tours.columns:
        individual_tours = rd.tours.filter(pl.col("tour_category") == "non_mandatory")
    else:
        individual_tours = rd.tours.head(0)

    day_required = {"person_id", "day_id"}
    has_multiday_people = False
    if day_required.issubset(rd.day.columns):
        has_multiday_people = not (
            rd.day.filter(
                pl.col("person_id").is_not_null() & pl.col("day_id").is_not_null()
            )
            .group_by("person_id")
            .agg(pl.col("day_id").n_unique().alias("_day_count"))
            .filter(pl.col("_day_count") > 1)
            .is_empty()
        )

    person_days: pl.DataFrame | None = None
    participant_days: pl.DataFrame | None = None
    can_use_person_days = (
        has_multiday_people
        and day_required.issubset(individual_tours.columns)
        and {"person_id", "person_type", "finalweight"}.issubset(per.columns)
    )
    if can_use_person_days:
        person_days = _day_person_records(rd, "day_id").filter(
            pl.col("day_id").is_not_null()
        )
        valid_day_keys = person_days.select("person_id", "day_id").unique()
        keyed_individual_tours = individual_tours.filter(
            pl.col("person_id").is_not_null()
        )
        can_use_person_days = (
            keyed_individual_tours.filter(pl.col("day_id").is_null()).is_empty()
            and keyed_individual_tours.join(
                valid_day_keys, on=["person_id", "day_id"], how="anti"
            ).is_empty()
        )

    participant_rows = rd.joint_participants
    if can_use_person_days and "person_id" in participant_rows.columns:
        participant_rows = participant_rows.filter(pl.col("person_id").is_not_null())
        if participant_rows.is_empty():
            participant_days = participant_rows.select("person_id").with_columns(
                pl.lit(None, dtype=pl.Int64).alias("day_id")
            )
        elif "day_id" in participant_rows.columns:
            participant_days = participant_rows.select("person_id", "day_id")
            can_use_person_days = (
                participant_days.filter(pl.col("day_id").is_null()).is_empty()
                and participant_days.join(
                    valid_day_keys, on=["person_id", "day_id"], how="anti"
                ).is_empty()
            )
        elif "tour_id" in participant_rows.columns and {"tour_id", "day_id"}.issubset(
            rd.tours.columns
        ):
            missing_tour_ids = participant_rows.filter(pl.col("tour_id").is_null())
            keyed_participant_rows = participant_rows.filter(
                pl.col("tour_id").is_not_null()
            )
            tour_day_rows = (
                rd.tours.filter(
                    pl.col("tour_id").is_not_null() & pl.col("day_id").is_not_null()
                )
                .select("tour_id", "day_id")
                .join(
                    keyed_participant_rows.select("tour_id").unique(),
                    on="tour_id",
                    how="semi",
                )
            )
            ambiguous_tour_ids = (
                tour_day_rows.group_by("tour_id")
                .agg(pl.col("day_id").n_unique().alias("_day_count"))
                .filter(pl.col("_day_count") != 1)
            )
            tour_day_map = tour_day_rows.unique()
            participant_days = keyed_participant_rows.join(
                tour_day_map, on="tour_id", how="left"
            ).select("person_id", "day_id")
            can_use_person_days = (
                missing_tour_ids.is_empty()
                and ambiguous_tour_ids.is_empty()
                and keyed_participant_rows.height == participant_days.height
                and participant_days.filter(pl.col("day_id").is_null()).is_empty()
                and participant_days.join(
                    valid_day_keys, on=["person_id", "day_id"], how="anti"
                ).is_empty()
            )
        else:
            can_use_person_days = participant_rows.is_empty()
    elif can_use_person_days:
        can_use_person_days = participant_rows.is_empty()
        participant_days = pl.DataFrame(
            schema={"person_id": pl.Int64, "day_id": pl.Int64}
        )

    if can_use_person_days and person_days is not None:
        inm_counts = individual_tours.group_by(["person_id", "day_id"]).agg(
            pl.len().alias("inmTours")
        )
        jnm_counts = (
            participant_days.group_by(["person_id", "day_id"]).agg(
                pl.len().alias("jnumTours")
            )
            if participant_days is not None
            else pl.DataFrame(
                schema={
                    "person_id": pl.Int64,
                    "day_id": pl.Int64,
                    "jnumTours": pl.UInt32,
                }
            )
        )
        source = person_days
        count_keys = ["person_id", "day_id"]
    else:
        if "person_id" in individual_tours.columns:
            inm_counts = individual_tours.group_by("person_id").agg(
                pl.len().alias("inmTours")
            )
        else:
            inm_counts = per.select("person_id").with_columns(
                pl.lit(0).alias("inmTours")
            )

        if "person_id" in rd.joint_participants.columns:
            jnm_counts = rd.joint_participants.group_by("person_id").agg(
                pl.len().alias("jnumTours")
            )
        else:
            jnm_counts = per.select("person_id").with_columns(
                pl.lit(0).alias("jnumTours")
            )
        source = per
        count_keys = ["person_id"]

    per2 = (
        source.join(inm_counts, on=count_keys, how="left")
        .join(jnm_counts, on=count_keys, how="left")
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

    tours = rd.tours
    if "tour_category" in tours.columns:
        category = (
            pl.col("tour_category").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        )
        tours = tours.filter(pl.col("tour_category").is_null() | (category != "atwork"))

    weighted_tours = (
        _weighted_activity_by_person_type(
            rd,
            tours,
            purpose_col=purpose_col,
            participant_col="NUMBER_HH",
        )
        .rename(
            {
                "activity_purpose": "tour_purpose",
                "activity_count": "weighted_tours",
            }
        )
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
        _weighted_activity_by_person_type(
            rd,
            rd.trips,
            purpose_col="trip_purpose",
            participant_col="num_participants",
        )
        .rename(
            {
                "activity_purpose": "trip_purpose",
                "activity_count": "trip_count",
            }
        )
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
