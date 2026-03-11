"""Tour time-of-day profiles."""

from __future__ import annotations

import polars as pl

from ..models import RunData


def tod_profiles(rd: RunData) -> pl.DataFrame:
    """Departure, arrival, and duration profiles in either 24 or 48 time bins."""
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame()

    indiv = rd.tours.filter(pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"]))
    joint = rd.tours.filter(pl.col("tour_category") == "joint").with_columns((pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt"))

    purpose_groups: list[tuple[str, pl.DataFrame, pl.Expr]] = []
    if "primary_purpose" in rd.tours.columns:
        purposes = indiv["primary_purpose"].drop_nulls().unique().sort().to_list()
        for purpose in purposes:
            purpose_groups.append((purpose, indiv, pl.col("primary_purpose") == purpose))
        if len(joint) > 0:
            joint_purposes = joint["primary_purpose"].drop_nulls().unique().sort().to_list()
            for purpose in joint_purposes:
                purpose_groups.append((f"joint_{purpose}", joint, pl.col("primary_purpose") == purpose))
    else:
        purpose_groups.append(("all", rd.tours, pl.lit(True)))

    max_period = 48
    if "start_hour" in rd.tours.columns:
        try:
            max_period = int(rd.tours["start_hour"].max())
        except Exception:
            max_period = 48
    bins = list(range(1, 25 if max_period <= 24 else 49))

    def _hist(df: pl.DataFrame, col: str, weight_col: str, filt: pl.Expr) -> pl.DataFrame:
        if col not in df.columns:
            return pl.DataFrame({"bin": bins, "n": [0.0] * len(bins)})
        subset = (
            df.filter(filt)
            .select([col, weight_col])
            .with_columns(pl.col(col).cast(pl.Int32).alias("bin"))
            .filter(pl.col("bin").is_between(1, bins[-1]))
        )
        counts = subset.group_by("bin").agg(pl.col(weight_col).sum().alias("n"))
        return pl.DataFrame({"bin": bins}).join(counts, on="bin", how="left").fill_null(0)

    rows: list[dict[str, object]] = []
    for purpose_name, df, filt in purpose_groups:
        weight_col = "wgt" if "wgt" in df.columns else "finalweight"
        dep = _hist(df, "start_hour", weight_col, filt)
        arr = _hist(df, "end_hour", weight_col, filt)
        dur = _hist(df, "tourdur", weight_col, filt)
        for i, timebin in enumerate(bins):
            rows.append(
                {
                    "timebin": timebin,
                    "purpose": purpose_name,
                    "freq_dep": float(dep["n"][i]) if i < len(dep) else 0.0,
                    "freq_arr": float(arr["n"][i]) if i < len(arr) else 0.0,
                    "freq_dur": float(dur["n"][i]) if i < len(dur) else 0.0,
                }
            )

    if not rows:
        return pl.DataFrame()

    df_long = pl.DataFrame(rows)
    total = (
        df_long.group_by("timebin")
        .agg([pl.col("freq_dep").sum(), pl.col("freq_arr").sum(), pl.col("freq_dur").sum()])
        .with_columns(pl.lit("Total").alias("purpose"))
        .select(["timebin", "purpose", "freq_dep", "freq_arr", "freq_dur"])
    )
    return pl.concat([df_long, total]).sort(["timebin", "purpose"])
