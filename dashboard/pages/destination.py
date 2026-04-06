"""Destination page: NM tour distance distributions."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import _to_pandas, density_chart
from summarize.reader import Config, RunData


def _nm_dist_by_purpose(
    rd: RunData, purpose: str | None, col_name: str
) -> pl.DataFrame:
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
                (
                    indiv.select(["SKIMDIST", "finalweight"])
                    if "SKIMDIST" in indiv.columns
                    else pl.DataFrame()
                ),
                (
                    joint.select(["SKIMDIST", "finalweight"])
                    if "SKIMDIST" in joint.columns
                    else pl.DataFrame()
                ),
            ]
        )
    else:
        if "primary_purpose" not in tours.columns:
            return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})
        combined = pl.concat(
            [
                indiv.filter(pl.col(col_name) == purpose).select(
                    ["SKIMDIST", "finalweight"]
                )
                if "SKIMDIST" in indiv.columns
                else pl.DataFrame(),
                joint.filter(pl.col(col_name) == purpose).select(
                    ["SKIMDIST", "finalweight"]
                )
                if "SKIMDIST" in joint.columns
                else pl.DataFrame(),
            ]
        )

    if len(combined) == 0 or "SKIMDIST" not in combined.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    combined = combined.with_columns(
        pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin")
    )
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

    # Collect NM purpose options from all runs and map run label to purpose column
    purposes_set = set()
    run_to_purpose_col = {}
    for run_label, rd in runs:
        if "tour_category" in rd.tours.columns:
            for cand in ("primary_purpose", "tour_type", "purpose"):
                if cand in rd.tours.columns and not rd.tours[cand].dtype.is_numeric():
                    run_to_purpose_col[run_label] = cand
                    break
            else:
                run_to_purpose_col[run_label] = None
            purpose_col = run_to_purpose_col[run_label]
            if purpose_col:
                nm_tours = rd.tours.filter(
                    pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"])
                )
                purposes_set.update(
                    nm_tours[purpose_col].drop_nulls().unique().to_list()
                )
        else:
            run_to_purpose_col[run_label] = None

    purposes = sorted(purposes_set) if purposes_set else []

    purp_opts = ["All NM"] + purposes
    purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value="All NM")

    @pn.depends(purp_sel)
    def dist_chart(purp):
        data = [
            (l, _nm_dist_by_purpose(rd, purp, run_to_purpose_col[l])) for l, rd in runs
        ]
        return density_chart(
            data,
            "distbin",
            "freq",
            f"NM Tour Distance Distribution — {purp}",
            "Distance (miles)",
            normalize=True,
        )

    # Average distance table by purpose
    def avg_dist_table():
        rows = []
        for purp in purposes:
            row = {"Purpose": purp}
            for run_label, rd in runs:
                purpose_col = run_to_purpose_col.get(run_label)
                if not purpose_col:
                    row[run_label] = None
                    continue
                df = _nm_dist_by_purpose(rd, purp, purpose_col)
                if "SKIMDIST" in rd.tours.columns and purpose_col in rd.tours.columns:
                    sub = rd.tours.filter(pl.col(purpose_col) == purp)
                    if len(sub) > 0:
                        wgt = sub["finalweight"].to_numpy()
                        dist = sub["SKIMDIST"].to_numpy()
                        mask = dist == dist
                        if mask.sum() > 0 and wgt[mask].sum() > 0:
                            row[run_label] = round(
                                float((dist[mask] * wgt[mask]).sum() / wgt[mask].sum()),
                                2,
                            )
                            continue
                row[run_label] = None
            rows.append(row)
        return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()

    avg_df = avg_dist_table()

    return pn.Column(
        pn.pane.Markdown("## Destination Choice (NM Tour Distances)"),
        pn.Row(pn.pane.Markdown("**Purpose:**"), purp_sel),
        dist_chart,
        pn.pane.Markdown("### Average Tour Distances (miles)"),
        (
            pn.widgets.Tabulator(_to_pandas(avg_df), sizing_mode="stretch_width")
            if len(avg_df) > 0
            else pn.pane.Markdown("*(No distance data available)*")
        ),
        sizing_mode="stretch_width",
    )
