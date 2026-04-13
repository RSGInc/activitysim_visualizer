"""Tour time-of-day profiles.

Uses primary_purpose string directly from ActivitySim outputs.
Purposes are discovered from data, not hardcoded.
"""

import polars as pl
from runtime.config import Config
from runtime.models import RunData


def tod_profiles(rd: RunData) -> pl.DataFrame:
    """Departure, arrival, and duration profiles in 48 half-hour bins.

    Returns DataFrame: timebin (1-48), purpose, freq_dep, freq_arr, freq_dur.
    Purposes are taken from primary_purpose strings in the data, plus "Total".
    """
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame()

    indiv = rd.tours.filter(
        pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"])
    )
    joint = rd.tours.filter(pl.col("tour_category") == "joint").with_columns(
        (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
    )

    purpose_col = "tour_purpose" if "tour_purpose" in rd.tours.columns else None

    purpose_groups = []
    if purpose_col:
        purps = indiv[purpose_col].drop_nulls().unique().sort().to_list()
        for p in purps:
            purpose_groups.append((p, indiv, pl.col(purpose_col) == p))
        if len(joint) > 0:
            j_purps = joint[purpose_col].drop_nulls().unique().sort().to_list()
            for p in j_purps:
                purpose_groups.append((f"joint_{p}", joint, pl.col(purpose_col) == p))
    else:
        purpose_groups.append(("all", rd.tours, pl.lit(True)))

    # Support both 24 one-hour bins and 48 half-hour bins.
    max_period = 48
    if "start_hour" in rd.tours.columns:
        try:
            max_period = int(rd.tours["start_hour"].max())
        except Exception:
            max_period = 48
    bins = list(range(1, 25 if max_period <= 24 else 49))

    def _hist(df: pl.DataFrame, col: str, wgt_col: str, filt) -> pl.DataFrame:
        if col not in df.columns:
            return pl.DataFrame({"bin": bins, "n": [0.0] * len(bins)})
        sub = (
            df.filter(filt)
            .select([col, wgt_col])
            .with_columns(pl.col(col).cast(pl.Int32).alias("bin"))
            .filter(pl.col("bin").is_between(1, bins[-1]))
        )
        counts = sub.group_by("bin").agg(pl.col(wgt_col).sum().alias("n"))
        base = pl.DataFrame({"bin": bins})
        return base.join(counts, on="bin", how="left").fill_null(0)

    all_rows = []
    for purp_name, df, filt in purpose_groups:
        wgt = "wgt" if "wgt" in df.columns else "finalweight"
        dep = _hist(df, "start_hour", wgt, filt)
        arr = _hist(df, "end_hour", wgt, filt)
        dur = _hist(df, "tourdur", wgt, filt)
        for i, tb in enumerate(bins):
            all_rows.append(
                {
                    "timebin": tb,
                    "purpose": purp_name,
                    "freq_dep": float(dep["n"][i]) if i < len(dep) else 0.0,
                    "freq_arr": float(arr["n"][i]) if i < len(arr) else 0.0,
                    "freq_dur": float(dur["n"][i]) if i < len(dur) else 0.0,
                }
            )

    if not all_rows:
        return pl.DataFrame()

    df_long = pl.DataFrame(all_rows, infer_schema_length=None)
    total = (
        df_long.group_by("timebin")
        .agg(
            [
                pl.col("freq_dep").sum(),
                pl.col("freq_arr").sum(),
                pl.col("freq_dur").sum(),
            ]
        )
        .with_columns(pl.lit("Total").alias("purpose"))
        .select(["timebin", "purpose", "freq_dep", "freq_arr", "freq_dur"])
    )

    return pl.concat([df_long, total]).sort(["timebin", "purpose"])
