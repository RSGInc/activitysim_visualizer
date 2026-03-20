"""Tour-level summaries: DAP, mandatory tour freq, NM tours, joint tours.

Uses string values directly from ActivitySim outputs:
- tour_category: "mandatory", "non-mandatory", "joint", "atwork"
- primary_purpose: raw string from ActivitySim
- ptype column: as specified in config.col_ptype
"""
import polars as pl
from .reader import RunData, Config


def dap_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """DAP by person type. Columns: ptype, DAP, freq."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.per.columns or "cdap_activity" not in rd.per.columns:
        return pl.DataFrame({"ptype": [], "DAP": [], "freq": []})

    df = (rd.per
          .filter(pl.col("cdap_activity").is_not_null())
          .group_by([ptype_col, "cdap_activity"])
          .agg(pl.col("finalweight").sum().alias("freq"))
          .rename({ptype_col: "ptype", "cdap_activity": "DAP"})
          .with_columns(pl.col("ptype").cast(pl.Utf8)))

    total = (df.group_by("DAP")
               .agg(pl.col("freq").sum())
               .with_columns(pl.lit("Total").alias("ptype"))
               .select(["ptype", "DAP", "freq"]))

    return pl.concat([df, total])


def mandatory_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Mandatory tour frequency by person type. Columns: ptype, MTF, freq."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.per.columns or "imf_choice" not in rd.per.columns:
        return pl.DataFrame({"ptype": [], "MTF": [], "freq": []})

    df = (rd.per
          .filter(pl.col("imf_choice") > 0)
          .group_by([ptype_col, "imf_choice"])
          .agg(pl.col("finalweight").sum().alias("freq"))
          .rename({ptype_col: "ptype", "imf_choice": "MTF"})
          .with_columns(pl.col("ptype").cast(pl.Utf8)))

    total = (df.group_by("MTF")
               .agg(pl.col("freq").sum())
               .with_columns(pl.lit("Total").alias("ptype"))
               .select(["ptype", "MTF", "freq"]))

    return pl.concat([df, total])


def indiv_nm_summary(rd: RunData, config: Config) -> pl.DataFrame:
    """Individual NM tour frequency distribution by person type.

    Columns: ptype, nmtours (0/1/2/3pl), freq.
    NM tours = non-mandatory individual + joint participant.
    """
    per = rd.per
    ptype_col = config.col_ptype

    if "tour_category" in rd.tours.columns:
        inm_counts = (rd.tours
                      .filter(pl.col("tour_category") == "non-mandatory")
                      .group_by("person_id")
                      .agg(pl.len().alias("inmTours")))
    else:
        inm_counts = rd.tours.head(0).select(["person_id"]).with_columns(pl.lit(0).alias("inmTours"))

    jnm_counts = (rd.joint_participants
                  .group_by("person_id")
                  .agg(pl.len().alias("jnumTours")))

    per2 = (per
            .join(inm_counts, on="person_id", how="left")
            .join(jnm_counts, on="person_id", how="left")
            .with_columns([
                pl.col("inmTours").fill_null(0),
                pl.col("jnumTours").fill_null(0),
            ])
            .with_columns((pl.col("inmTours") + pl.col("jnumTours")).alias("numTours")))

    per2 = per2.with_columns(
        pl.when(pl.col("numTours") == 0).then(pl.lit("0"))
        .when(pl.col("numTours") == 1).then(pl.lit("1"))
        .when(pl.col("numTours") == 2).then(pl.lit("2"))
        .otherwise(pl.lit("3pl"))
        .alias("nmtours")
    )

    df = (per2.group_by([ptype_col, "nmtours"])
          .agg(pl.col("finalweight").sum().alias("freq"))
          .rename({ptype_col: "ptype"})
          .with_columns(pl.col("ptype").cast(pl.Utf8)))
    total = (df.group_by("nmtours")
               .agg(pl.col("freq").sum())
               .with_columns(pl.lit("Total").alias("ptype"))
               .select(["ptype", "nmtours", "freq"]))
    return pl.concat([df, total])


def nm_tour_rates(rd: RunData, config: Config) -> pl.DataFrame:
    """NM tour rates per person by person type and purpose.

    Columns: ptype, tour_purp, tour_rate.
    Purposes are the raw primary_purpose strings from NM tours.
    """
    ptype_col = config.col_ptype
    if (
        "tour_category" not in rd.tours.columns
        or "primary_purpose" not in rd.tours.columns
        or ptype_col not in rd.tours.columns
        or ptype_col not in rd.per.columns
    ):
        return pl.DataFrame({"ptype": [], "tour_purp": [], "tour_rate": []})

    nm_tours = rd.tours.filter(pl.col("tour_category") == "non-mandatory")
    purposes = nm_tours["primary_purpose"].drop_nulls().unique().to_list()
    purposes.sort()

    per_counts = (rd.per
                  .group_by(ptype_col)
                  .agg(pl.col("finalweight").sum().alias("n_per")))
    total_per = rd.per["finalweight"].sum()
    ptypes = rd.per[ptype_col].drop_nulls().unique().to_list()

    nm_grouped = (nm_tours
                  .group_by([ptype_col, "primary_purpose"])
                  .agg(pl.col("finalweight").sum().alias("n_tours")))

    result = []
    for ptype in ptypes:
        n_per_row = per_counts.filter(pl.col(ptype_col) == ptype)["n_per"]
        n_per = float(n_per_row[0]) if len(n_per_row) > 0 else 0
        for purp in purposes:
            n_row = nm_grouped.filter(
                (pl.col(ptype_col) == ptype) & (pl.col("primary_purpose") == purp)
            )["n_tours"]
            n = float(n_row[0]) if len(n_row) > 0 else 0
            result.append({"ptype": str(ptype), "tour_purp": purp,
                            "tour_rate": (n / n_per) if n_per > 0 else 0})

    for purp in purposes:
        n_row = nm_grouped.filter(pl.col("primary_purpose") == purp)["n_tours"]
        n = float(n_row.sum()) if len(n_row) > 0 else 0
        result.append({"ptype": "All", "tour_purp": purp,
                        "tour_rate": (n / float(total_per)) if total_per and total_per > 0 else 0})

    return pl.DataFrame(result)


def joint_tour_freq(rd: RunData) -> pl.DataFrame:
    """Joint tour frequency (21 alternatives). Columns: jtf_code, alt_name, freq.

    Uses primary_purpose strings directly — groups NM joint tour purposes.
    """
    JTF_NAMES = [
        "No Joint Tours",
        "1 Shopping", "1 Maintenance", "1 Eating Out", "1 Visiting", "1 Other Discretionary",
        "2 Shopping", "2 Maintenance", "2 Eating Out", "2 Visiting", "2 Other Discretionary",
        "1 Shopping / 1 Maintenance", "1 Shopping / 1 Eating Out", "1 Shopping / 1 Visiting",
        "1 Shopping / 1 Other Discretionary", "1 Maintenance / 1 Eating Out",
        "1 Maintenance / 1 Visiting", "1 Maintenance / 1 Other Discretionary",
        "1 Eating Out / 1 Visiting", "1 Eating Out / 1 Other Discretionary",
        "1 Visiting / 1 Other Discretionary",
    ]

    if "tour_category" not in rd.tours.columns:
        jtf_df = pl.DataFrame({"jtf_code": list(range(1, 22)), "alt_name": JTF_NAMES})
        return jtf_df.with_columns(pl.lit(0.0).alias("freq"))

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")

    # Map purpose strings to slot letters (a-e for up to 5 NM purposes)
    nm_purposes = (joint_tours["primary_purpose"].drop_nulls().unique().sort().to_list()
                   if "primary_purpose" in joint_tours.columns else [])
    # Take up to 5 most common (for JTF coding)
    purpose_slots = {p: f"j{i}" for i, p in enumerate(nm_purposes[:5])}
    slot_cols = [f"j{i}" for i in range(len(purpose_slots))]

    hh_joint = pl.DataFrame({"household_id": rd.hh["household_id"]})

    for purp, slot in purpose_slots.items():
        counts = (joint_tours.filter(pl.col("primary_purpose") == purp)
                  .group_by("household_id")
                  .agg(pl.len().cast(pl.Int64).alias(slot)))
        hh_joint = (hh_joint
                    .join(counts, on="household_id", how="left")
                    .with_columns(pl.col(slot).fill_null(0)))

    for slot in slot_cols:
        if slot not in hh_joint.columns:
            hh_joint = hh_joint.with_columns(pl.lit(0).alias(slot))

    all_hh = rd.hh.select(["household_id", "finalweight"])
    hh_joint = all_hh.join(hh_joint, on="household_id", how="left")
    # Fill nulls per column to avoid type conflicts (slot cols are Int64, finalweight is Float64)
    for slot in slot_cols:
        if slot in hh_joint.columns:
            hh_joint = hh_joint.with_columns(pl.col(slot).fill_null(0))

    # Code JTF (simplified: 1=none, 2-6=single, 7-11=two same, 12-21=two different)
    hh_joint = hh_joint.with_columns(pl.lit(1).alias("jtf"))
    codes = [(2,1,0,0,0,0),(3,0,1,0,0,0),(4,0,0,1,0,0),(5,0,0,0,1,0),(6,0,0,0,0,1),
             (7,2,0,0,0,0),(8,0,2,0,0,0),(9,0,0,2,0,0),(10,0,0,0,2,0),(11,0,0,0,0,2),
             (12,1,1,0,0,0),(13,1,0,1,0,0),(14,1,0,0,1,0),(15,1,0,0,0,1),
             (16,0,1,1,0,0),(17,0,1,0,1,0),(18,0,1,0,0,1),
             (19,0,0,1,1,0),(20,0,0,1,0,1),(21,0,0,0,1,1)]

    for (code, *vals) in codes:
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

    summary = (hh_joint.group_by("jtf")
               .agg(pl.col("finalweight").sum().alias("freq")))

    jtf_df = pl.DataFrame({"jtf_code": list(range(1, 22)), "alt_name": JTF_NAMES})
    result = (jtf_df.join(summary.rename({"jtf": "jtf_code"}),
                          on="jtf_code", how="left").fill_null(0))
    return result


def joint_composition(rd: RunData) -> pl.DataFrame:
    """Joint tour composition. Columns: tour_composition, freq."""
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame({"tour_composition": [], "freq": []})
    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    # ActivitySim uses "composition"; fall back to "tour_composition" if somehow renamed
    comp_col = "composition" if "composition" in joint_tours.columns else "tour_composition"
    if comp_col not in joint_tours.columns:
        return pl.DataFrame({"tour_composition": [], "freq": []})
    return (joint_tours
            .group_by(comp_col)
            .agg(pl.col("finalweight").sum().alias("freq"))
            .rename({comp_col: "tour_composition"}))


def joint_party_size(rd: RunData) -> pl.DataFrame:
    """Joint tour party size distribution (capped at 5+). Columns: NUMBER_HH (1-5), freq."""
    if "tour_category" not in rd.tours.columns or "NUMBER_HH" not in rd.tours.columns:
        return pl.DataFrame({"NUMBER_HH": [], "freq": []})
    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    df = (joint_tours
          .group_by("NUMBER_HH")
          .agg(pl.col("finalweight").sum().alias("freq"))
          .sort("NUMBER_HH"))
    cap5 = df.filter(pl.col("NUMBER_HH") >= 5)["freq"].sum()
    df = df.filter(pl.col("NUMBER_HH") < 5).with_columns(pl.col("NUMBER_HH").cast(pl.Int32))
    cap_row = pl.DataFrame({
        "NUMBER_HH": pl.Series([5], dtype=pl.Int32),
        "freq": pl.Series([cap5 or 0.0], dtype=pl.Float64),
    })
    return pl.concat([df, cap_row]).sort("NUMBER_HH")


def joint_tours_hhsize(rd: RunData) -> pl.DataFrame:
    """Joint tour count category (0/1/2+) by HH size as proportions.

    Columns: jointTours, hhsize, freq.
    """
    hh = rd.hh
    if "tour_category" not in rd.tours.columns or "HHSIZE" not in hh.columns:
        return pl.DataFrame({"jointTours": [], "hhsize": [], "freq": []})

    joint_tours = rd.tours.filter(pl.col("tour_category") == "joint")
    jt_counts = (joint_tours
                 .group_by("household_id")
                 .agg(pl.len().cast(pl.Int64).alias("jtours")))

    hh2 = (hh.join(jt_counts, on="household_id", how="left")
           .with_columns(pl.col("jtours").fill_null(0))
           .with_columns(
                pl.when(pl.col("jtours") == 0).then(0)
                .when(pl.col("jtours") == 1).then(1)
               .otherwise(2).alias("jointCat")
           )
           .filter((pl.col("HHSIZE") >= 2) & pl.col("jointCat").is_not_null()))

    pivot = (hh2.group_by(["HHSIZE", "jointCat"])
             .agg(pl.col("finalweight").sum().alias("freq"))
             .pivot(on="HHSIZE", index="jointCat", values="freq", aggregate_function="sum")
             .fill_null(0))

    hhsizes = sorted([c for c in pivot.columns if c != "jointCat"])
    for sz in hhsizes:
        sz_col = str(sz) if str(sz) in pivot.columns else sz
        col_total = float(pivot[sz_col].sum())
        if col_total > 0:
            pivot = pivot.with_columns((pl.col(sz_col) / col_total * 100).alias(sz_col))

    pivot = pivot.with_columns(
        pl.when(pl.col("jointCat") == 0).then(pl.lit("0"))
        .when(pl.col("jointCat") == 1).then(pl.lit("1"))
        .otherwise(pl.lit("2+"))
        .alias("jointCat")
    )
    result = pivot.unpivot(index="jointCat", variable_name="hhsize", value_name="freq")
    return result.rename({"jointCat": "jointTours"}).with_columns(pl.col("hhsize").cast(pl.Utf8))


def tours_by_pertype_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    """Individual NM tours by person type and purpose.

    Columns: ptype, primary_purpose, freq.
    """
    ptype_col = config.col_ptype
    if ("tour_category" not in rd.tours.columns or "primary_purpose" not in rd.tours.columns
            or ptype_col not in rd.tours.columns):
        return pl.DataFrame({"ptype": [], "primary_purpose": [], "freq": []})

    return (rd.tours
            .filter((pl.col("tour_category") == "non-mandatory") &
                    (pl.col("tour_category") != "joint"))
            .group_by([ptype_col, "primary_purpose"])
            .agg(pl.col("finalweight").sum().alias("freq"))
            .rename({ptype_col: "ptype"})
            .sort(["ptype", "primary_purpose"]))


