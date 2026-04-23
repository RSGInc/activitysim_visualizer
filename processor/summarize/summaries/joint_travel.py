"""Joint travel summaries."""

import polars as pl

from runtime.config import Config
from processor.models import RunData


def joint_tour_freq(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Returns DataFrame: jtf_code, jtf_label, household_count."""
    result_schema = {
        "jtf_code": pl.Int32,
        "jtf_label": pl.Utf8,
        "household_count": pl.Float64,
    }
    JTF_NAMES = [
        "No Joint Tours",
        "1 Shopping",
        "1 Maintenance",
        "1 Eating Out",
        "1 Visiting",
        "1 Other Discretionary",
        "2 Shopping",
        "2 Maintenance",
        "2 Eating Out",
        "2 Visiting",
        "2 Other Discretionary",
        "1 Shopping / 1 Maintenance",
        "1 Shopping / 1 Eating Out",
        "1 Shopping / 1 Visiting",
        "1 Shopping / 1 Other Discretionary",
        "1 Maintenance / 1 Eating Out",
        "1 Maintenance / 1 Visiting",
        "1 Maintenance / 1 Other Discretionary",
        "1 Eating Out / 1 Visiting",
        "1 Eating Out / 1 Other Discretionary",
        "1 Visiting / 1 Other Discretionary",
    ]

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

    if "tour_category" not in rd.tours.columns:
        return jtf_lookup.with_columns(pl.lit(0.0).alias("household_count"))

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    # Map purpose strings to slot letters (a-e for up to 5 NM purposes)
    nm_purposes = (
        joint_tours["primary_purpose"].drop_nulls().unique().sort().to_list()
        if "primary_purpose" in joint_tours.columns
        else []
    )
    # Take up to 5 most common (for JTF coding)
    purpose_slots = {p: f"j{i}" for i, p in enumerate(nm_purposes[:5])}
    slot_cols = [f"j{i}" for i in range(len(purpose_slots))]

    hh_joint = pl.DataFrame({"household_id": rd.hh["household_id"]})

    for purp, slot in purpose_slots.items():
        counts = (
            joint_tours.filter(pl.col("primary_purpose") == purp)
            .group_by("household_id")
            .agg(pl.len().cast(pl.Int64).alias(slot))
        )
        hh_joint = hh_joint.join(counts, on="household_id", how="left").with_columns(
            pl.col(slot).fill_null(0)
        )

    for slot in slot_cols:
        if slot not in hh_joint.columns:
            hh_joint = hh_joint.with_columns(pl.lit(0).alias(slot))

    all_hh = rd.hh.select(["household_id", "finalweight"])
    hh_joint = all_hh.join(hh_joint, on="household_id", how="left")

    for slot in slot_cols:
        if slot in hh_joint.columns:
            hh_joint = hh_joint.with_columns(pl.col(slot).fill_null(0))

    # TODO: JTF coding is simplified; verify category assignment matches formal ActivitySim joint tour frequency definitions.

    # Code JTF (simplified: 1=none, 2-6=single, 7-11=two same, 12-21=two different)

    hh_joint = hh_joint.with_columns(pl.lit(1).alias("jtf"))

    codes = [
        (2, 1, 0, 0, 0, 0),
        (3, 0, 1, 0, 0, 0),
        (4, 0, 0, 1, 0, 0),
        (5, 0, 0, 0, 1, 0),
        (6, 0, 0, 0, 0, 1),
        (7, 2, 0, 0, 0, 0),
        (8, 0, 2, 0, 0, 0),
        (9, 0, 0, 2, 0, 0),
        (10, 0, 0, 0, 2, 0),
        (11, 0, 0, 0, 0, 2),
        (12, 1, 1, 0, 0, 0),
        (13, 1, 0, 1, 0, 0),
        (14, 1, 0, 0, 1, 0),
        (15, 1, 0, 0, 0, 1),
        (16, 0, 1, 1, 0, 0),
        (17, 0, 1, 0, 1, 0),
        (18, 0, 1, 0, 0, 1),
        (19, 0, 0, 1, 1, 0),
        (20, 0, 0, 1, 0, 1),
        (21, 0, 0, 0, 1, 1),
    ]

    for code, *vals in codes:
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


def joint_tours_hhsize(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Returns DataFrame: household_size, joint_tour_count."""
    result_schema = {
        "household_size": pl.Int32,
        "joint_tour_count": pl.Float64,
    }
    if "tour_category" not in rd.tours.columns or "HHSIZE" not in rd.hh.columns:
        return pl.DataFrame(schema=result_schema)

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")

    if joint_tours.is_empty():
        return pl.DataFrame(
            {
                "household_size": [],
                "joint_tour_count": [],
            }
        )

    return (
        joint_tours.join(
            rd.hh.select(["household_id", "HHSIZE"]),
            on="household_id",
            how="left",
        )
        .group_by("HHSIZE")
        .agg(joint_tour_count=pl.col("finalweight").sum())
        .rename({"HHSIZE": "household_size"})
        .sort("household_size")
    )


def joint_party_size(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Joint tour party size distribution (capped at 5+). Columns: party_size (1-5), joint_tour_count."""
    result_schema = {
        "party_size": pl.Int32,
        "joint_tour_count": pl.Float64,
    }
    if "tour_category" not in rd.tours.columns or "NUMBER_HH" not in rd.tours.columns:
        return pl.DataFrame(schema=result_schema)

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")

    if joint_tours.is_empty():
        return pl.DataFrame(schema=result_schema)

    df = (
        joint_tours.group_by("NUMBER_HH")
        .agg(joint_tour_count=pl.col("finalweight").sum())
        .sort("NUMBER_HH")
    )

    cap5 = df.filter(pl.col("NUMBER_HH") >= 5)["joint_tour_count"].sum()

    df = df.filter(pl.col("NUMBER_HH") < 5).with_columns(
        pl.col("NUMBER_HH").cast(pl.Int32)
    )

    cap_row = pl.DataFrame(
        {
            "NUMBER_HH": pl.Series([5], dtype=pl.Int32),
            "joint_tour_count": pl.Series([cap5 or 0.0], dtype=pl.Float64),
        }
    )

    return (
        pl.concat([df, cap_row])
        .sort("NUMBER_HH")
        .rename({"NUMBER_HH": "party_size"})
        .select(
            pl.col("party_size").cast(pl.Int32),
            pl.col("joint_tour_count").cast(pl.Float64),
        )
    )


def joint_composition(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Joint tour composition. Columns: tour_composition, joint_tour_count."""
    result_schema = {
        "tour_composition": pl.Utf8,
        "joint_tour_count": pl.Float64,
    }
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame(schema=result_schema)

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    # ActivitySim uses "composition"; fall back to "tour_composition" if somehow renamed
    comp_col = (
        "composition" if "composition" in joint_tours.columns else "tour_composition"
    )

    if comp_col not in joint_tours.columns:
        return pl.DataFrame(schema=result_schema)

    return (
        joint_tours.group_by(comp_col)
        .agg(joint_tour_count=pl.col("finalweight").sum())
        .rename({comp_col: "tour_composition"})
        .sort("tour_composition")
    )


def joint_composition_by_party_size(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def joint_participation_person_by_hhsize(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def jtf_by_hhsize(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Joint tour count category (0/1/2+) by HH size as proportions.
    Returns DataFrame: jtf, household_size, household_percent."""
    result_schema = {
        "jtf": pl.Utf8,
        "household_size": pl.Utf8,
        "household_percent": pl.Float64,
    }
    hh = rd.hh

    if "tour_category" not in rd.tours.columns or "HHSIZE" not in hh.columns:
        return pl.DataFrame(schema=result_schema)

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")

    jt_counts = joint_tours.group_by("household_id").agg(
        pl.len().cast(pl.Int64).alias("jtours")
    )

    hh2 = (
        hh.join(jt_counts, on="household_id", how="left")
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
