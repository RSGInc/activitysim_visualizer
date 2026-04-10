"""Destination choice summaries used by the dashboard cache layer."""

from __future__ import annotations

import polars as pl

from runtime.models import RunData


def _combined_nm_tours(rd: RunData, purpose: str | None = None) -> pl.DataFrame:
    tours = rd.tours
    if "tour_category" not in tours.columns:
        return pl.DataFrame({"SKIMDIST": [], "finalweight": []})

    indiv = tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork"]))
    joint = tours.filter(pl.col("tour_category") == "joint")
    if len(joint) > 0:
        joint = joint.with_columns(
            (pl.col("finalweight") * pl.col("NUMBER_HH").fill_null(1)).alias(
                "finalweight"
            )
        )

    if purpose and purpose != "All NM":
        if "primary_purpose" not in tours.columns:
            return pl.DataFrame({"SKIMDIST": [], "finalweight": []})
        indiv = indiv.filter(pl.col("primary_purpose") == purpose)
        joint = joint.filter(pl.col("primary_purpose") == purpose)

    parts: list[pl.DataFrame] = []
    for df in (indiv, joint):
        if len(df) > 0 and "SKIMDIST" in df.columns and "finalweight" in df.columns:
            parts.append(df.select(["SKIMDIST", "finalweight"]))

    if not parts:
        return pl.DataFrame({"SKIMDIST": [], "finalweight": []})
    return pl.concat(parts)


def distance_distribution(rd: RunData) -> pl.DataFrame:
    """NM destination distance distribution by purpose.

    Columns: purpose, distbin, freq
    """
    tours = rd.tours
    if "tour_category" in tours.columns and "primary_purpose" in tours.columns:
        purposes = sorted(
            tours.filter(
                pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"])
            )["primary_purpose"]
            .drop_nulls()
            .unique()
            .to_list()
        )
    else:
        purposes = []

    labels = ["All NM"] + purposes
    bins = list(range(41))
    rows: list[dict[str, object]] = []
    for purpose in labels:
        combined = _combined_nm_tours(rd, purpose)
        if len(combined) > 0 and "SKIMDIST" in combined.columns:
            combined = combined.with_columns(
                pl.col("SKIMDIST").cast(pl.Float64).fill_null(0.0).clip(0, 999.0)
            ).with_columns(
                pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin")
            )
            counts = combined.group_by("distbin").agg(
                pl.col("finalweight").sum().alias("freq")
            )
            freq_map = {
                int(row["distbin"]): float(row["freq"])
                for row in counts.iter_rows(named=True)
            }
        else:
            freq_map = {}

        for distbin in bins:
            rows.append(
                {
                    "purpose": purpose,
                    "distbin": distbin,
                    "freq": freq_map.get(distbin, 0.0),
                }
            )

    return pl.DataFrame(rows)


def average_distance(rd: RunData) -> pl.DataFrame:
    """Average NM tour distance by purpose.

    Columns: purpose, avg_distance
    """
    tours = rd.tours
    if "tour_category" in tours.columns and "primary_purpose" in tours.columns:
        purposes = sorted(
            tours.filter(
                pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"])
            )["primary_purpose"]
            .drop_nulls()
            .unique()
            .to_list()
        )
    else:
        purposes = []

    rows: list[dict[str, object]] = []
    for purpose in purposes:
        combined = _combined_nm_tours(rd, purpose)
        if len(combined) == 0:
            avg_distance = None
        else:
            valid = combined.filter(
                pl.col("SKIMDIST").is_not_null() & pl.col("finalweight").is_not_null()
            )
            if len(valid) == 0:
                avg_distance = None
            else:
                weights = valid["finalweight"].to_numpy()
                distances = valid["SKIMDIST"].to_numpy()
                total_weight = float(weights.sum())
                avg_distance = (
                    float((distances * weights).sum() / total_weight)
                    if total_weight > 0
                    else None
                )
        rows.append({"purpose": purpose, "avg_distance": avg_distance})

    return pl.DataFrame(rows or {"purpose": [], "avg_distance": []})
