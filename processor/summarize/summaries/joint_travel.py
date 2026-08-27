"""Joint travel summaries."""

import polars as pl

from runtime.config import Config
from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    household_tour_weight_expr,
    joint_party_size_expr,
)


JTF_PURPOSE_ALIASES = (
    ("shopping", "shop", "joint_shopping"),
    ("othmaint", "maintenance", "maint", "other_maintenance", "joint_othmaint"),
    ("eatout", "eating_out", "eat", "joint_eatout"),
    ("social", "visiting", "visit", "joint_social"),
    (
        "othdiscr",
        "other_discretionary",
        "discretionary",
        "joint_othdiscr",
    ),
)

JTF_NAMES = (
    "No Joint Tours",
    "1 Shopping",
    "1 Maintenance",
    "1 Eating Out",
    "1 Visiting",
    "1 Other Discretionary",
    "2 Shopping",
    "1 Shopping / 1 Maintenance",
    "1 Shopping / 1 Eating Out",
    "1 Shopping / 1 Visiting",
    "1 Shopping / 1 Other Discretionary",
    "2 Maintenance",
    "1 Maintenance / 1 Eating Out",
    "1 Maintenance / 1 Visiting",
    "1 Maintenance / 1 Other Discretionary",
    "2 Eating Out",
    "1 Eating Out / 1 Visiting",
    "1 Eating Out / 1 Other Discretionary",
    "2 Visiting",
    "1 Visiting / 1 Other Discretionary",
    "2 Other Discretionary",
)

# Each tuple is (alternative code, minimum count in each fixed purpose slot).
JTF_ALTERNATIVES = (
    (2, 1, 0, 0, 0, 0),
    (3, 0, 1, 0, 0, 0),
    (4, 0, 0, 1, 0, 0),
    (5, 0, 0, 0, 1, 0),
    (6, 0, 0, 0, 0, 1),
    (7, 2, 0, 0, 0, 0),
    (8, 1, 1, 0, 0, 0),
    (9, 1, 0, 1, 0, 0),
    (10, 1, 0, 0, 1, 0),
    (11, 1, 0, 0, 0, 1),
    (12, 0, 2, 0, 0, 0),
    (13, 0, 1, 1, 0, 0),
    (14, 0, 1, 0, 1, 0),
    (15, 0, 1, 0, 0, 1),
    (16, 0, 0, 2, 0, 0),
    (17, 0, 0, 1, 1, 0),
    (18, 0, 0, 1, 0, 1),
    (19, 0, 0, 0, 2, 0),
    (20, 0, 0, 0, 1, 1),
    (21, 0, 0, 0, 0, 2),
)


def _has_multiday_household_history(rd: RunData) -> bool:
    """Return whether prepared days span multiple diary days per household."""
    required = {"household_id", "day_num"}
    if rd.day.is_empty() or not required.issubset(rd.day.columns):
        return False
    return not (
        rd.day.filter(
            pl.col("household_id").is_not_null() & pl.col("day_num").is_not_null()
        )
        .group_by("household_id")
        .agg(pl.col("day_num").n_unique().alias("_day_count"))
        .filter(pl.col("_day_count") > 1)
        .is_empty()
    )


def _valid_identifier(column: str) -> pl.Expr:
    text = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
    numeric = pl.col(column).cast(pl.Float64, strict=False)
    return (
        text.is_not_null()
        & (text != "")
        & (
            numeric.is_null()
            | (numeric.is_finite() & (numeric > 0) & (numeric != 995))
        )
    )


def _joint_identity_expr(df: pl.DataFrame, *, row_fallback: str | None = None) -> pl.Expr:
    candidates: list[pl.Expr] = []
    for prefix, column in (("joint:", "joint_tour_id"), ("tour:", "tour_id")):
        if column in df.columns:
            candidates.append(
                pl.when(_valid_identifier(column)).then(
                    pl.concat_str(pl.lit(prefix), pl.col(column).cast(pl.Utf8))
                )
            )
    if row_fallback is not None:
        candidates.append(
            pl.concat_str(pl.lit("row:"), pl.col(row_fallback).cast(pl.Utf8))
        )
    if not candidates:
        return pl.lit(None, dtype=pl.Utf8)
    return pl.coalesce(candidates)


def _household_observations(rd: RunData) -> tuple[pl.DataFrame, list[str]]:
    hhsize_col = "HHSIZE" if "HHSIZE" in rd.hh.columns else "hhsize"
    hh_columns = ["household_id", "finalweight"]
    if hhsize_col in rd.hh.columns:
        hh_columns.append(hhsize_col)
    households = rd.hh.select(hh_columns)
    if hhsize_col in households.columns and hhsize_col != "HHSIZE":
        households = households.rename({hhsize_col: "HHSIZE"})

    if _has_multiday_household_history(rd):
        keys = ["household_id", "day_num"]
        observations = (
            rd.day.filter(
                pl.col("household_id").is_not_null()
                & pl.col("day_num").is_not_null()
            )
            .select(keys)
            .unique()
            .join(households, on="household_id", how="inner")
        )
        return observations, keys
    return households, ["household_id"]


def _unique_joint_tours(rd: RunData, observation_keys: list[str]) -> pl.DataFrame:
    if not {"household_id", *observation_keys}.issubset(rd.tours.columns):
        return pl.DataFrame()
    if "tour_category" not in rd.tours.columns:
        return rd.tours.head(0)
    return (
        rd.tours.filter(
            pl.col("tour_category").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
            == "joint"
        )
        .with_row_index("_joint_row")
        .with_columns(
            _joint_identity_expr(rd.tours, row_fallback="_joint_row").alias(
                "_joint_identity"
            )
        )
        .unique([*observation_keys, "_joint_identity"], maintain_order=True)
    )


@summary(
    id="jtf_distribution",
    schema={
        "jtf_code": pl.Int32,
        "jtf_label": pl.Utf8,
        "household_count": pl.Float64,
    },
    required_columns={"hh": ("household_id", "finalweight")},
)
def joint_tour_freq(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Returns DataFrame: jtf_code, jtf_label, household_count."""
    jtf_lookup = pl.DataFrame(
        {
            "jtf_code": list(range(1, 22)),
            "jtf_label": JTF_NAMES,
        },
        schema={
            "jtf_code": pl.Int32,
            "jtf_label": pl.Utf8,
        },
    )

    observations, observation_keys = _household_observations(rd)
    joint_tours = _unique_joint_tours(rd, observation_keys)
    if joint_tours.width == 0 and _has_multiday_household_history(rd):
        return joint_tour_freq.empty()
    hh_joint = observations.select(observation_keys)
    normalized_purpose = (
        pl.col("tour_purpose").cast(pl.Utf8).str.strip_chars().str.to_lowercase()
    )
    slot_cols = [f"j{i}" for i in range(len(JTF_PURPOSE_ALIASES))]
    for slot, aliases in zip(slot_cols, JTF_PURPOSE_ALIASES, strict=True):
        if "tour_purpose" in joint_tours.columns:
            counts = (
                joint_tours.filter(normalized_purpose.is_in(aliases))
                .group_by(observation_keys)
                .agg(pl.len().cast(pl.Int64).alias(slot))
            )
            hh_joint = hh_joint.join(
                counts, on=observation_keys, how="left"
            ).with_columns(pl.col(slot).fill_null(0))
        else:
            hh_joint = hh_joint.with_columns(pl.lit(0).alias(slot))

    hh_joint = observations.join(hh_joint, on=observation_keys, how="left")
    hh_joint = hh_joint.with_columns(pl.col(slot).fill_null(0) for slot in slot_cols)

    hh_joint = hh_joint.with_columns(pl.lit(1).alias("jtf"))

    for code, *vals in JTF_ALTERNATIVES:
        conds = []
        for i, v in enumerate(vals):
            col = f"j{i}"
            if col in hh_joint.columns:
                if v == 1:
                    conds.append(pl.col(col) >= 1)
                elif v == 2:
                    conds.append(pl.col(col) >= 2)

        if conds:
            cond = conds[0]
            for c in conds[1:]:
                cond = cond & c

            hh_joint = hh_joint.with_columns(
                pl.when(cond).then(code).otherwise(pl.col("jtf")).alias("jtf")
            )

    summary = (
        hh_joint.group_by("jtf")
        .agg(household_count=pl.col("finalweight").sum())
        .rename({"jtf": "jtf_code"})
    )

    return (
        jtf_lookup.join(summary, on="jtf_code", how="left")
        .with_columns(pl.col("household_count").fill_null(0.0))
        .select(
            pl.col("jtf_code").cast(pl.Int32),
            pl.col("jtf_label").cast(pl.Utf8),
            pl.col("household_count").cast(pl.Float64),
        )
    )


@summary(
    id="joint_tours_by_household_size",
    schema={
        "household_size": pl.Int32,
        "household_count": pl.Float64,
        "joint_tour_hh_count": pl.Float64,
    },
    required_columns={
        "tours": ("tour_category", "household_id"),
        "hh": ("household_id", "HHSIZE", "finalweight"),
    },
)
def joint_tours_hhsize(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Returns DataFrame: household_size, household_count, joint_tour_hh_count."""
    if (
        "tour_category" not in rd.tours.columns
        or "household_id" not in rd.tours.columns
        or "HHSIZE" not in rd.hh.columns
        or "household_id" not in rd.hh.columns
        or "finalweight" not in rd.hh.columns
    ):
        return joint_tours_hhsize.empty()

    observations, observation_keys = _household_observations(rd)
    if not set(observation_keys).issubset(rd.tours.columns):
        return joint_tours_hhsize.empty()
    joint_tour_hhs = (
        _unique_joint_tours(rd, observation_keys)
        .select(observation_keys)
        .unique()
        .with_columns(has_joint_tour=pl.lit(True))
    )

    return (
        observations.join(joint_tour_hhs, on=observation_keys, how="left")
        .with_columns(has_joint_tour=pl.col("has_joint_tour").fill_null(False))
        .group_by("HHSIZE")
        .agg(
            household_count=pl.col("finalweight").sum(),
            joint_tour_hh_count=pl.when(pl.col("has_joint_tour"))
            .then(pl.col("finalweight"))
            .otherwise(0.0)
            .sum(),
        )
        .rename({"HHSIZE": "household_size"})
        .sort("household_size")
    )


@summary(
    id="joint_tour_party_size_distribution",
    schema={
        "party_size": pl.Int32,
        "joint_tour_count": pl.Float64,
    },
    required_columns={"tours": ("tour_category", "NUMBER_HH", "finalweight")},
)
def joint_party_size(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Joint tour party size distribution, with sizes of 5 or more capped at 5."""
    if "tour_category" not in rd.tours.columns or "NUMBER_HH" not in rd.tours.columns:
        return joint_party_size.empty()

    joint_tours = (
        rd.tours.filter(
            pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint"
        )
        .with_columns(
            joint_party_size_expr(rd.tours).alias("_party_size"),
            household_tour_weight_expr(
                rd.tours,
                output_col="_household_tour_weight",
            ),
        )
        .filter(pl.col("_party_size").is_not_null())
    )

    if joint_tours.is_empty():
        return joint_party_size.empty()

    df = (
        joint_tours.group_by("_party_size")
        .agg(joint_tour_count=pl.col("_household_tour_weight").sum())
        .sort("_party_size")
    )

    cap5 = df.filter(pl.col("_party_size") >= 5)["joint_tour_count"].sum()

    df = df.filter(pl.col("_party_size") < 5).with_columns(
        pl.col("_party_size").cast(pl.Int32)
    )

    cap_row = pl.DataFrame(
        {
            "_party_size": pl.Series([5], dtype=pl.Int32),
            "joint_tour_count": pl.Series([cap5 or 0.0], dtype=pl.Float64),
        }
    )

    return (
        pl.concat([df, cap_row])
        .sort("_party_size")
        .rename({"_party_size": "party_size"})
        .select(
            pl.col("party_size").cast(pl.Int32),
            pl.col("joint_tour_count").cast(pl.Float64),
        )
    )


@summary(
    id="joint_tour_composition_distribution",
    schema={
        "tour_composition": pl.Utf8,
        "joint_tour_count": pl.Float64,
    },
    required_columns={"tours": ("tour_category", "finalweight")},
)
def joint_composition(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Joint tour composition. Columns: tour_composition, joint_tour_count."""
    if "tour_category" not in rd.tours.columns:
        return joint_composition.empty()

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    # ActivitySim uses "composition"; fall back to "tour_composition" if somehow renamed
    comp_col = (
        "composition" if "composition" in joint_tours.columns else "tour_composition"
    )

    if comp_col not in joint_tours.columns:
        return joint_composition.empty()

    return (
        joint_tours.with_columns(
            household_tour_weight_expr(
                joint_tours,
                output_col="_household_tour_weight",
            )
        )
        .group_by(comp_col)
        .agg(joint_tour_count=pl.col("_household_tour_weight").sum())
        .rename({comp_col: "tour_composition"})
        .sort("tour_composition")
    )


@summary(
    id="joint_tour_composition_by_party_size",
    schema={
        "tour_composition": pl.Utf8,
        "party_size": pl.Int64,
        "joint_tour_count": pl.Float64,
    },
    required_columns={
        "tours": ("tour_category", "finalweight")
    },
)
def joint_composition_by_party_size(rd: RunData, config: Config) -> pl.DataFrame:
    if not {"tour_category", "finalweight"}.issubset(rd.tours.columns):
        return joint_composition_by_party_size.empty()

    joint_tours = rd.tours.filter(
        pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint"
    )
    comp_col = (
        "composition" if "composition" in joint_tours.columns else "tour_composition"
    )
    if comp_col not in joint_tours.columns:
        return joint_composition_by_party_size.empty()
    return (
        joint_tours.with_columns(
            joint_party_size_expr(joint_tours).alias("_party_size"),
            household_tour_weight_expr(
                joint_tours,
                output_col="_household_tour_weight",
            ),
        )
        .filter(
            pl.col(comp_col).is_not_null()
            & pl.col("_party_size").is_not_null()
        )
        .group_by([comp_col, "_party_size"])
        .agg(joint_tour_count=pl.col("_household_tour_weight").sum())
        .rename(
            {
                comp_col: "tour_composition",
                "_party_size": "party_size",
            }
        )
        .with_columns(
            pl.col("tour_composition").cast(pl.Utf8),
            pl.col("party_size").cast(pl.Int64),
            pl.col("joint_tour_count").cast(pl.Float64),
        )
        .select("tour_composition", "party_size", "joint_tour_count")
        .sort(["tour_composition", "party_size"])
    )


@summary(
    id="person_jtp_by_household_size",
    schema={
        "household_size": pl.Int64,
        "joint_tour_person_count": pl.Float64,
        "total_person_count": pl.Float64,
    },
    required_columns={
        "per": ("household_id", "person_id", "finalweight"),
        "hh": ("household_id",),
    },
)
def joint_participation_person_by_hhsize(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"household_id", "person_id", "finalweight"}
    hhsize_col = "HHSIZE" if "HHSIZE" in rd.hh.columns else "hhsize"
    if not person_required.issubset(rd.per.columns) or hhsize_col not in rd.hh.columns:
        return joint_participation_person_by_hhsize.empty()

    if _has_multiday_household_history(rd) and {
        "household_id",
        "person_id",
        "day_num",
    }.issubset(rd.day.columns):
        person_weights = rd.per.select(
            "person_id",
            pl.col("finalweight").cast(pl.Float64).alias("_person_weight"),
        ).unique("person_id")
        day_weight = (
            pl.col("finalweight").cast(pl.Float64).alias("_day_weight")
            if "finalweight" in rd.day.columns
            else pl.lit(None, dtype=pl.Float64).alias("_day_weight")
        )
        persons_with_hhsize = (
            rd.day.select("household_id", "person_id", "day_num", day_weight)
            .filter(
                pl.col("person_id").is_not_null() & pl.col("day_num").is_not_null()
            )
            .unique(["person_id", "day_num"])
            .join(person_weights, on="person_id", how="inner")
            .with_columns(
                pl.coalesce("_day_weight", "_person_weight").alias("finalweight")
            )
            .join(
                rd.hh.select(
                    "household_id", pl.col(hhsize_col).alias("hhsize")
                ),
                on="household_id",
                how="left",
            )
        )

        tour_days = _unique_joint_tours(rd, ["household_id", "day_num"])
        if "_joint_identity" not in tour_days.columns:
            return joint_participation_person_by_hhsize.empty()
        tour_days = tour_days.select("_joint_identity", "day_num").unique()
        if (
            tour_days.group_by("_joint_identity")
            .agg(pl.col("day_num").n_unique().alias("_day_count"))
            .filter(pl.col("_day_count") != 1)
            .height
        ):
            return joint_participation_person_by_hhsize.empty()
        participants = (
            rd.joint_participants.with_columns(
                _joint_identity_expr(rd.joint_participants).alias("_joint_identity")
            )
            .filter(
                pl.col("person_id").is_not_null()
                & pl.col("_joint_identity").is_not_null()
            )
            .join(tour_days, on="_joint_identity", how="inner")
            .select("person_id", "day_num")
            .unique()
            .with_columns(_has_joint_tour=pl.lit(True))
        )
        persons_with_hhsize = persons_with_hhsize.join(
            participants, on=["person_id", "day_num"], how="left"
        ).with_columns(pl.col("_has_joint_tour").fill_null(False))
    else:
        if "num_joint_tours" in rd.per.columns:
            participation = (pl.col("num_joint_tours") > 0).fill_null(False)
        elif "person_id" in rd.joint_participants.columns:
            participation = pl.col("person_id").is_in(
                rd.joint_participants.select("person_id").drop_nulls().to_series()
            )
        else:
            participation = pl.lit(False)
        persons_with_hhsize = (
            rd.per.join(
                rd.hh.select(
                    "household_id", pl.col(hhsize_col).alias("hhsize")
                ),
                on="household_id",
                how="left",
            )
            .with_columns(
                participation.alias("_has_joint_tour")
            )
        )

    persons_with_hhsize = persons_with_hhsize.filter(pl.col("hhsize").is_not_null())

    if persons_with_hhsize.is_empty():
        return joint_participation_person_by_hhsize.empty()

    total_people = persons_with_hhsize.group_by("hhsize").agg(
        total_person_weight=pl.col("finalweight").sum()
    )

    joint_tour_people = (
        persons_with_hhsize.filter(pl.col("_has_joint_tour"))
        .group_by("hhsize")
        .agg(joint_tour_person_weight=pl.col("finalweight").sum())
    )

    return (
        total_people.join(joint_tour_people, on="hhsize", how="left")
        .with_columns(
            pl.col("joint_tour_person_weight").fill_null(0.0),
        )
        .rename({"hhsize": "household_size"})
        .with_columns(
            pl.col("household_size").cast(pl.Int64),
            pl.col("joint_tour_person_weight")
            .cast(pl.Float64)
            .alias("joint_tour_person_count"),
            pl.col("total_person_weight").cast(pl.Float64).alias("total_person_count"),
        )
        .select("household_size", "joint_tour_person_count", "total_person_count")
        .sort("household_size")
    )


@summary(
    id="household_jtp_by_household_size_and_jtf",
    schema={
        "jtf": pl.Utf8,
        "household_size": pl.Utf8,
        "household_percent": pl.Float64,
    },
    required_columns={
        "hh": ("household_id", "HHSIZE", "finalweight"),
        "tours": ("tour_category", "household_id"),
    },
)
def jtf_by_hhsize(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Joint tour count category (0/1/2+) by HH size as proportions.
    Returns DataFrame: jtf, household_size, household_percent."""
    if "tour_category" not in rd.tours.columns or "HHSIZE" not in rd.hh.columns:
        return jtf_by_hhsize.empty()

    observations, observation_keys = _household_observations(rd)
    if not set(observation_keys).issubset(rd.tours.columns):
        return jtf_by_hhsize.empty()
    joint_tours = _unique_joint_tours(rd, observation_keys)

    jt_counts = joint_tours.group_by(observation_keys).agg(
        pl.len().cast(pl.Int64).alias("jtours")
    )

    hh2 = (
        observations.join(jt_counts, on=observation_keys, how="left")
        .with_columns(pl.col("jtours").fill_null(0))
        .with_columns(
            pl.when(pl.col("jtours") == 0)
            .then(pl.lit("0"))
            .when(pl.col("jtours") == 1)
            .then(pl.lit("1"))
            .otherwise(pl.lit("2+"))
            .alias("jtf"),
            pl.col("HHSIZE").cast(pl.Utf8).alias("household_size"),
        )
        .filter(pl.col("HHSIZE") >= 2)
    )

    grouped = hh2.group_by(["household_size", "jtf"]).agg(
        household_count=pl.col("finalweight").sum()
    )

    totals = grouped.group_by("household_size").agg(
        total_households=pl.col("household_count").sum()
    )

    return (
        grouped.join(totals, on="household_size", how="left")
        .with_columns(
            (pl.col("household_count") / pl.col("total_households") * 100).alias(
                "household_percent"
            )
        )
        .select(
            pl.col("jtf").cast(pl.Utf8),
            pl.col("household_size").cast(pl.Utf8),
            pl.col("household_percent").cast(pl.Float64),
        )
        .sort(["household_size", "jtf"])
    )
