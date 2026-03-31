"""Destination page: NM tour distance distributions."""
from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import _to_pandas, density_chart
from summarize.reader import Config, RunData


def _nm_dist_by_purpose(rd: RunData, purpose: str | None) -> pl.DataFrame:
    """Return (distbin 0-40, freq) for NM tours filtered by primary_purpose string."""
    tours = rd.tours
    if "tour_category" not in tours.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    indiv = tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork"]))
    joint = tours.filter(pl.col("tour_category") == "joint").with_columns(
        (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
    )
    joint = (
        joint.rename({"wgt": "finalweight"})
        if "finalweight" not in joint.columns
        else joint.with_columns(pl.col("wgt").alias("finalweight"))
    )

    if purpose is None or purpose == "All NM":
        combined = pl.concat(
            [
                indiv.select(["SKIMDIST", "finalweight"]) if "SKIMDIST" in indiv.columns else pl.DataFrame(),
                joint.select(["SKIMDIST", "finalweight"]) if "SKIMDIST" in joint.columns else pl.DataFrame(),
            ]
        )
    else:
        if "primary_purpose" not in tours.columns:
            return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})
        combined = pl.concat(
            [
                indiv.filter(pl.col("primary_purpose") == purpose).select(["SKIMDIST", "finalweight"])
                if "SKIMDIST" in indiv.columns
                else pl.DataFrame(),
                joint.filter(pl.col("primary_purpose") == purpose).select(["SKIMDIST", "finalweight"])
                if "SKIMDIST" in joint.columns
                else pl.DataFrame(),
            ]
        )

    if len(combined) == 0 or "SKIMDIST" not in combined.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    combined = combined.with_columns(pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin"))
    return (
        combined.group_by("distbin")
        .agg(pl.col("finalweight").sum().alias("freq"))
        .join(pl.DataFrame({"distbin": list(range(41))}), on="distbin", how="right")
        .fill_null(0)
        .sort("distbin")
    )


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    first_rd = runs[0][1]
    if "tour_category" in first_rd.tours.columns and "primary_purpose" in first_rd.tours.columns:
        nm_tours = first_rd.tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"]))
        purposes = sorted(nm_tours["primary_purpose"].drop_nulls().unique().to_list())
    else:
        purposes = []

    purp_opts = ["All NM"] + purposes
    purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value="All NM")

    @pn.depends(purp_sel)
    def dist_chart(purp):
        data = [(label, _nm_dist_by_purpose(rd, purp)) for label, rd in runs]
        return density_chart(
            data,
            "distbin",
            "freq",
            f"NM Tour Distance Distribution - {purp}",
            "Distance (miles)",
            normalize=False,
        )

    def avg_dist_table():
        rows = []
        for purp in purposes:
            row = {"Purpose": purp}
            for run_label, rd in runs:
                if "SKIMDIST" in rd.tours.columns and "primary_purpose" in rd.tours.columns:
                    sub = rd.tours.filter(pl.col("primary_purpose") == purp)
                    if len(sub) > 0:
                        wgt = sub["finalweight"].to_numpy()
                        dist = sub["SKIMDIST"].to_numpy()
                        mask = dist == dist
                        if mask.sum() > 0 and wgt[mask].sum() > 0:
                            row[run_label] = round(float((dist[mask] * wgt[mask]).sum() / wgt[mask].sum()), 2)
                            continue
                row[run_label] = None
            rows.append(row)
        return pl.DataFrame(rows) if rows else pl.DataFrame()

    avg_df = avg_dist_table()

    return pn.Column(
        pn.pane.Markdown("## Destination Choice (NM Tour Distances)"),
        pn.Row(pn.pane.Markdown("**Purpose:**"), purp_sel),
        dist_chart,
        pn.pane.Markdown("### Average Tour Distances (miles)"),
        pn.widgets.Tabulator(_to_pandas(avg_df), sizing_mode="stretch_width")
        if len(avg_df) > 0
        else pn.pane.Markdown("*(No distance data available)*"),
        sizing_mode="stretch_width",
    )
