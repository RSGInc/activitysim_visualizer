"""Tour mode choice summaries by auto sufficiency and grouped mode."""

from __future__ import annotations

import polars as pl

from ..models import Config, RunData


def tour_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Tour mode by auto sufficiency level and purpose."""
    if "tour_mode" not in rd.tours.columns:
        return pl.DataFrame()

    indiv = rd.tours.filter(pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"])) if "tour_category" in rd.tours.columns else rd.tours
    joint = (
        rd.tours.filter(pl.col("tour_category") == "joint").with_columns((pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt"))
        if "tour_category" in rd.tours.columns
        else rd.tours.head(0)
    )

    purpose_groups: list[tuple[str, pl.DataFrame, pl.Expr]] = []
    purpose_col = next((cand for cand in ("primary_purpose", "tour_type", "purpose") if cand in rd.tours.columns), None)
    if purpose_col:
        purposes = indiv[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
        for purpose in purposes:
            purpose_groups.append((purpose, indiv, pl.col(purpose_col).cast(pl.Utf8) == purpose))
        if len(joint) > 0:
            joint_purposes = joint[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
            for purpose in joint_purposes:
                purpose_groups.append((f"joint_{purpose}", joint, pl.col(purpose_col).cast(pl.Utf8) == purpose))
    else:
        purpose_groups.append(("all", rd.tours, pl.lit(True)))

    all_modes = config.ordered_modes(rd.tours["tour_mode"].drop_nulls().unique().to_list())
    rows: list[dict[str, object]] = []
    for purpose_name, df, purpose_filter in purpose_groups:
        weight_col = "wgt" if "wgt" in df.columns else "finalweight"
        for autosuff in range(3):
            autosuff_filter = (pl.col("AUTOSUFF") == autosuff) if "AUTOSUFF" in df.columns else pl.lit(True)
            subset = df.filter(purpose_filter & autosuff_filter)
            counts = subset.group_by("tour_mode").agg(pl.col(weight_col).sum().alias("n"))
            for mode in all_modes:
                n_row = counts.filter(pl.col("tour_mode") == mode)["n"]
                rows.append({"tour_mode": mode, "purpose": purpose_name, "autosuff": autosuff, "freq": float(n_row[0]) if len(n_row) > 0 else 0.0})

    if not rows:
        return pl.DataFrame()

    df_result = pl.DataFrame(rows)
    pivot = df_result.pivot(on="autosuff", index=["tour_mode", "purpose"], values="freq", aggregate_function="sum").fill_null(0)
    for autosuff in range(3):
        col = str(autosuff)
        if col in pivot.columns:
            pivot = pivot.rename({col: f"freq_as{autosuff}"})
    for col in ["freq_as0", "freq_as1", "freq_as2"]:
        if col not in pivot.columns:
            pivot = pivot.with_columns(pl.lit(0.0).alias(col))

    cols = ["tour_mode", "purpose", "freq_as0", "freq_as1", "freq_as2", "freq_all"]
    pivot = pivot.with_columns((pl.col("freq_as0") + pl.col("freq_as1") + pl.col("freq_as2")).alias("freq_all")).select(cols)
    total = (
        pivot.group_by("tour_mode")
        .agg([pl.col("freq_as0").sum(), pl.col("freq_as1").sum(), pl.col("freq_as2").sum(), pl.col("freq_all").sum()])
        .with_columns(pl.lit("Total").alias("purpose"))
        .select(cols)
    )
    return pl.concat([pivot, total])


def grouped_tour_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Grouped tour mode profile using config.mode_groups."""
    if not config.mode_groups:
        return pl.DataFrame()

    detail = tour_mode_profile(rd, config)
    if len(detail) == 0:
        return pl.DataFrame()

    mode_to_group: dict[str, str] = {}
    for group, modes in config.mode_groups.items():
        for mode in modes:
            mode_to_group[mode] = group

    group_map = pl.DataFrame({"tour_mode": list(mode_to_group.keys()), "mode_group": list(mode_to_group.values())})
    return (
        detail.join(group_map, on="tour_mode", how="left")
        .filter(pl.col("mode_group").is_not_null())
        .group_by(["mode_group", "purpose"])
        .agg([pl.col("freq_as0").sum(), pl.col("freq_as1").sum(), pl.col("freq_as2").sum(), pl.col("freq_all").sum()])
    )
