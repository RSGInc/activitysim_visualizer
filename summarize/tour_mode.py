"""Tour mode choice by auto sufficiency.

Uses tour_mode string directly from ActivitySim outputs.
Supports optional mode ordering (config.mode_order) and grouping (config.mode_groups).
"""
import polars as pl
from .reader import RunData, Config


def tour_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Tour mode by auto sufficiency level (0, 1, 2) and total, by tour purpose/category.

    Returns DataFrame: tour_mode, purpose_group, freq_as0, freq_as1, freq_as2, freq_all.
    Purpose groups are derived from tour_category and primary_purpose string values.
    """
    if "tour_mode" not in rd.tours.columns:
        return pl.DataFrame()

    indiv = rd.tours.filter(
        pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"])
    ) if "tour_category" in rd.tours.columns else rd.tours
    joint = (rd.tours.filter(pl.col("tour_category") == "joint")
             .with_columns((pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt"))
             ) if "tour_category" in rd.tours.columns else rd.tours.head(0)

    # Build purpose group filter pairs: (label, df, filter_expr)
    purpose_groups = []
    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.tours.columns:
            purpose_col = cand
            break
    if purpose_col:
        purposes = indiv[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
        for p in purposes:
            purpose_groups.append((p, indiv, pl.col(purpose_col).cast(pl.Utf8) == p))
        if len(joint) > 0:
            j_purposes = joint[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
            for p in j_purposes:
                purpose_groups.append((f"joint_{p}", joint, pl.col(purpose_col).cast(pl.Utf8) == p))
    else:
        purpose_groups.append(("all", rd.tours, pl.lit(True)))

    all_modes = rd.tours["tour_mode"].drop_nulls().unique().to_list()
    all_modes = config.ordered_modes(all_modes)

    result_rows = []
    for purp_name, df, purp_filter in purpose_groups:
        wgt_col = "wgt" if "wgt" in df.columns else "finalweight"
        for as_val in range(3):
            as_filter = (pl.col("AUTOSUFF") == as_val) if "AUTOSUFF" in df.columns else pl.lit(True)
            sub = df.filter(purp_filter & as_filter)
            counts = (sub.group_by("tour_mode")
                      .agg(pl.col(wgt_col).sum().alias("n")))
            for mode in all_modes:
                n_row = counts.filter(pl.col("tour_mode") == mode)["n"]
                n = float(n_row[0]) if len(n_row) > 0 else 0.0
                result_rows.append({"tour_mode": mode, "purpose": purp_name,
                                    "autosuff": as_val, "freq": n})

    if not result_rows:
        return pl.DataFrame()

    df_result = pl.DataFrame(result_rows)
    pivot = (df_result
             .pivot(on="autosuff", index=["tour_mode", "purpose"],
                    values="freq", aggregate_function="sum")
             .fill_null(0))

    for as_val in range(3):
        col = str(as_val)
        if col in pivot.columns:
            pivot = pivot.rename({col: f"freq_as{as_val}"})
    for col in ["freq_as0", "freq_as1", "freq_as2"]:
        if col not in pivot.columns:
            pivot = pivot.with_columns(pl.lit(0.0).alias(col))

    pivot = pivot.with_columns(
        (pl.col("freq_as0") + pl.col("freq_as1") + pl.col("freq_as2")).alias("freq_all")
    )

    cols = ["tour_mode", "purpose", "freq_as0", "freq_as1", "freq_as2", "freq_all"]
    pivot = pivot.select(cols)
    total = (pivot
             .group_by("tour_mode")
             .agg([pl.col("freq_as0").sum(), pl.col("freq_as1").sum(),
                   pl.col("freq_as2").sum(), pl.col("freq_all").sum()])
             .with_columns(pl.lit("Total").alias("purpose"))
             .select(cols))

    return pl.concat([pivot, total])


def grouped_tour_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Tour mode grouped by config.mode_groups, by auto sufficiency and purpose.

    Returns DataFrame: mode_group, purpose, freq_as0, freq_as1, freq_as2, freq_all.
    Returns empty DataFrame if mode_groups not configured.
    """
    if not config.mode_groups:
        return pl.DataFrame()

    detail = tour_mode_profile(rd, config)
    if len(detail) == 0:
        return pl.DataFrame()

    mode_to_group = {}
    for grp, modes in config.mode_groups.items():
        for m in modes:
            mode_to_group[m] = grp

    group_map = pl.DataFrame({
        "tour_mode": list(mode_to_group.keys()),
        "mode_group": list(mode_to_group.values()),
    })

    result = (detail.join(group_map, on="tour_mode", how="left")
              .filter(pl.col("mode_group").is_not_null())
              .group_by(["mode_group", "purpose"])
              .agg([pl.col("freq_as0").sum(), pl.col("freq_as1").sum(),
                    pl.col("freq_as2").sum(), pl.col("freq_all").sum()]))
    return result

