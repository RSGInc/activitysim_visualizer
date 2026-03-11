"""Tour-level summaries: DAP, mandatory tour frequency, non-mandatory tours, and joint tours."""

from __future__ import annotations

import polars as pl

from ..models import Config, RunData


def dap_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """Daily activity pattern by person type."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.per.columns or "cdap_activity" not in rd.per.columns:
        return pl.DataFrame({"ptype": [], "DAP": [], "freq": []})

    df = (
        rd.per.filter(pl.col("cdap_activity").is_not_null())
        .group_by([ptype_col, "cdap_activity"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .rename({ptype_col: "ptype", "cdap_activity": "DAP"})
        .with_columns(pl.col("ptype").cast(pl.Utf8))
    )

    total = (
        df.group_by("DAP")
        .agg(pl.col("freq").sum())
        .with_columns(pl.lit("Total").alias("ptype"))
        .select(["ptype", "DAP", "freq"])
    )
    return pl.concat([df, total])


def mandatory_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Mandatory tour frequency by person type."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.per.columns or "imf_choice" not in rd.per.columns:
        return pl.DataFrame({"ptype": [], "MTF": [], "freq": []})

    df = (
        rd.per.filter(pl.col("imf_choice") > 0)
        .group_by([ptype_col, "imf_choice"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .rename({ptype_col: "ptype", "imf_choice": "MTF"})
        .with_columns(pl.col("ptype").cast(pl.Utf8))
    )

    total = (
        df.group_by("MTF")
        .agg(pl.col("freq").sum())
        .with_columns(pl.lit("Total").alias("ptype"))
        .select(["ptype", "MTF", "freq"])
    )
    return pl.concat([df, total])


def indiv_nm_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """Individual non-mandatory tour frequency distribution by person type."""
    ptype_col = config.col_ptype

    if "tour_category" in rd.tours.columns:
        inm_counts = (
            rd.tours.filter(pl.col("tour_category") == "non-mandatory")
            .group_by("person_id")
            .agg(pl.len().alias("inmTours"))
        )
    else:
        inm_counts = rd.tours.head(0).select(["person_id"]).with_columns(pl.lit(0).alias("inmTours"))

    jnm_counts = rd.joint_participants.group_by("person_id").agg(pl.len().alias("jnumTours"))

    per2 = (
        rd.per.join(inm_counts, on="person_id", how="left")
        .join(jnm_counts, on="person_id", how="left")
        .with_columns([pl.col("inmTours").fill_null(0), pl.col("jnumTours").fill_null(0)])
        .with_columns((pl.col("inmTours") + pl.col("jnumTours")).alias("numTours"))
    )

    per2 = per2.with_columns(
        pl.when(pl.col("numTours") == 0)
        .then(pl.lit("0"))
        .when(pl.col("numTours") == 1)
        .then(pl.lit("1"))
        .when(pl.col("numTours") == 2)
        .then(pl.lit("2"))
        .otherwise(pl.lit("3pl"))
        .alias("nmtours")
    )

    df = (
        per2.group_by([ptype_col, "nmtours"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .rename({ptype_col: "ptype"})
        .with_columns(pl.col("ptype").cast(pl.Utf8))
    )
    total = (
        df.group_by("nmtours")
        .agg(pl.col("freq").sum())
        .with_columns(pl.lit("Total").alias("ptype"))
        .select(["ptype", "nmtours", "freq"])
    )
    return pl.concat([df, total])


def nm_tour_rates(rd: RunData, config: Config) -> pl.DataFrame:
    """Non-mandatory tour rates per person by person type and purpose."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.tours.columns or "tour_category" not in rd.tours.columns or "primary_purpose" not in rd.tours.columns:
        return pl.DataFrame({"ptype": [], "tour_purp": [], "tour_rate": []})

    nm_tours = rd.tours.filter(pl.col("tour_category") == "non-mandatory")
    purposes = nm_tours["primary_purpose"].drop_nulls().unique().to_list()
    purposes.sort()

    per_counts = rd.per.group_by(ptype_col).agg(pl.col("finalweight").sum().alias("n_per"))
    total_per = rd.per["finalweight"].sum()
    ptypes = rd.per[ptype_col].drop_nulls().unique().to_list()
    nm_grouped = nm_tours.group_by([ptype_col, "primary_purpose"]).agg(pl.col("finalweight").sum().alias("n_tours"))

    rows: list[dict[str, object]] = []
    for ptype in ptypes:
        n_per_row = per_counts.filter(pl.col(ptype_col) == ptype)["n_per"]
        n_per = float(n_per_row[0]) if len(n_per_row) > 0 else 0.0
        for purpose in purposes:
            n_row = nm_grouped.filter((pl.col(ptype_col) == ptype) & (pl.col("primary_purpose") == purpose))["n_tours"]
            count = float(n_row[0]) if len(n_row) > 0 else 0.0
            rows.append({"ptype": str(ptype), "tour_purp": purpose, "tour_rate": (count / n_per) if n_per > 0 else 0.0})

    for purpose in purposes:
        n_row = nm_grouped.filter(pl.col("primary_purpose") == purpose)["n_tours"]
        count = float(n_row.sum()) if len(n_row) > 0 else 0.0
        rows.append({"ptype": "All", "tour_purp": purpose, "tour_rate": (count / float(total_per)) if total_per and total_per > 0 else 0.0})

    return pl.DataFrame(rows)


def joint_tour_freq(rd: RunData) -> pl.DataFrame:
    """Joint tour frequency across the 21 standard alternatives."""
    jtf_names = [
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

    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame({"jtf_code": list(range(1, 22)), "alt_name": jtf_names, "freq": [0.0] * 21})

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    nm_purposes = (
        joint_tours["primary_purpose"].drop_nulls().unique().sort().to_list()
        if "primary_purpose" in joint_tours.columns
        else []
    )
    purpose_slots = {purpose: f"j{i}" for i, purpose in enumerate(nm_purposes[:5])}
    slot_cols = [f"j{i}" for i in range(len(purpose_slots))]

    hh_joint = pl.DataFrame({"household_id": rd.hh["household_id"]})
    for purpose, slot in purpose_slots.items():
        counts = (
            joint_tours.filter(pl.col("primary_purpose") == purpose)
            .group_by("household_id")
            .agg(pl.len().cast(pl.Int64).alias(slot))
        )
        hh_joint = hh_joint.join(counts, on="household_id", how="left").with_columns(pl.col(slot).fill_null(0))

    for slot in slot_cols:
        if slot not in hh_joint.columns:
            hh_joint = hh_joint.with_columns(pl.lit(0).alias(slot))

    hh_joint = rd.hh.select(["household_id", "finalweight"]).join(hh_joint, on="household_id", how="left")
    for slot in slot_cols:
        if slot in hh_joint.columns:
            hh_joint = hh_joint.with_columns(pl.col(slot).fill_null(0))

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
        conditions = []
        for i, val in enumerate(vals):
            col = f"j{i}"
            if col in hh_joint.columns:
                if val == 1:
                    conditions.append(pl.col(col) >= 1)
                elif val == 2:
                    conditions.append(pl.col(col) >= 2)
        if conditions:
            condition = conditions[0]
            for extra in conditions[1:]:
                condition = condition & extra
            hh_joint = hh_joint.with_columns(pl.when(condition).then(code).otherwise(pl.col("jtf")).alias("jtf"))

    summary = hh_joint.group_by("jtf").agg(pl.col("finalweight").sum().alias("freq"))
    jtf_df = pl.DataFrame({"jtf_code": list(range(1, 22)), "alt_name": jtf_names})
    return jtf_df.join(summary.rename({"jtf": "jtf_code"}), on="jtf_code", how="left").fill_null(0)


def joint_composition(rd: RunData) -> pl.DataFrame:
    """Joint tour composition counts."""
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame({"tour_composition": [], "freq": []})
    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    comp_col = "composition" if "composition" in joint_tours.columns else "tour_composition"
    if comp_col not in joint_tours.columns:
        return pl.DataFrame({"tour_composition": [], "freq": []})
    return joint_tours.group_by(comp_col).agg(pl.col("finalweight").sum().alias("freq")).rename({comp_col: "tour_composition"})


def joint_party_size(rd: RunData) -> pl.DataFrame:
    """Joint tour party size distribution capped at 5+."""
    if "tour_category" not in rd.tours.columns or "NUMBER_HH" not in rd.tours.columns:
        return pl.DataFrame({"NUMBER_HH": [], "freq": []})
    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    df = joint_tours.group_by("NUMBER_HH").agg(pl.col("finalweight").sum().alias("freq")).sort("NUMBER_HH")
    cap5 = df.filter(pl.col("NUMBER_HH") >= 5)["freq"].sum()
    df = df.filter(pl.col("NUMBER_HH") < 5).with_columns(pl.col("NUMBER_HH").cast(pl.Int32))
    cap_row = pl.DataFrame({"NUMBER_HH": pl.Series([5], dtype=pl.Int32), "freq": pl.Series([cap5 or 0.0], dtype=pl.Float64)})
    return pl.concat([df, cap_row]).sort("NUMBER_HH")


def joint_tours_hhsize(rd: RunData) -> pl.DataFrame:
    """Joint tour count category by household size as proportions."""
    if "tour_category" not in rd.tours.columns or "HHSIZE" not in rd.hh.columns:
        return pl.DataFrame({"jointTours": [], "hhsize": [], "freq": []})

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    jt_counts = joint_tours.group_by("household_id").agg(pl.len().cast(pl.Int64).alias("jtours"))

    hh2 = (
        rd.hh.join(jt_counts, on="household_id", how="left")
        .with_columns(pl.col("jtours").fill_null(0))
        .with_columns(
            pl.when(pl.col("jtours") == 0)
            .then(0)
            .when(pl.col("jtours") == 1)
            .then(1)
            .otherwise(2)
            .alias("jointCat")
        )
        .filter((pl.col("HHSIZE") >= 2) & pl.col("jointCat").is_not_null())
    )

    pivot = (
        hh2.group_by(["HHSIZE", "jointCat"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .pivot(on="HHSIZE", index="jointCat", values="freq", aggregate_function="sum")
        .fill_null(0)
    )
    hhsizes = sorted([col for col in pivot.columns if col != "jointCat"])
    for hhsize in hhsizes:
        hh_col = str(hhsize) if str(hhsize) in pivot.columns else hhsize
        total = float(pivot[hh_col].sum())
        if total > 0:
            pivot = pivot.with_columns((pl.col(hh_col) / total * 100).alias(hh_col))

    pivot = pivot.with_columns(
        pl.when(pl.col("jointCat") == 0)
        .then(pl.lit("0"))
        .when(pl.col("jointCat") == 1)
        .then(pl.lit("1"))
        .otherwise(pl.lit("2+"))
        .alias("jointCat")
    )
    result = pivot.unpivot(index="jointCat", variable_name="hhsize", value_name="freq")
    return result.rename({"jointCat": "jointTours"}).with_columns(pl.col("hhsize").cast(pl.Utf8))


def tours_by_pertype_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    """Individual non-mandatory tours by person type and purpose."""
    ptype_col = config.col_ptype
    if "tour_category" not in rd.tours.columns or "primary_purpose" not in rd.tours.columns or ptype_col not in rd.tours.columns:
        return pl.DataFrame({"ptype": [], "primary_purpose": [], "freq": []})

    return (
        rd.tours.filter((pl.col("tour_category") == "non-mandatory") & (pl.col("tour_category") != "joint"))
        .group_by([ptype_col, "primary_purpose"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .rename({ptype_col: "ptype"})
        .sort(["ptype", "primary_purpose"])
    )
