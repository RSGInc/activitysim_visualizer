"""Stop location page: out-of-direction distance."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from summarize import stops
from summarize.reader import Config, RunData


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    loc_list = [(l, stops.stop_location(rd)) for l, rd in runs]

    # Collect purpose options from all runs and map run label to purpose column
    purposes_set = set()
    run_to_purpose_col = {}
    for run_label, df in loc_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                run_to_purpose_col[run_label] = cand
                break
        else:
            run_to_purpose_col[run_label] = None
        purpose_col = run_to_purpose_col[run_label]
        if purpose_col:
            purposes_set.update(df[purpose_col].drop_nulls().unique().to_list())

    purp_opts = sorted(purposes_set) if purposes_set else []

    charts = []
    all_data = [
        (label, df.group_by("distbin").agg(pl.col("freq").sum()).sort("distbin"))
        for label, df in loc_list
    ]
    charts.append(
        density_chart(
            all_data,
            "distbin",
            "freq",
            "Stop Out-of-Direction Distance - All Purposes",
            "Miles",
            normalize=False,
        )
    )
    for purp in purp_opts:
        data = [
            (
                l,
                df.filter(pl.col(run_to_purpose_col[l]) == purp).select(
                    ["distbin", "freq"]
                ),
            )
            for l, df in loc_list
        ]
        charts.append(
            density_chart(
                data,
                "distbin",
                "freq",
                f"Stop Out-of-Direction Distance — {purp}",
                "Miles",
                normalize=True,
            )
        )

    return pn.Column(
        pn.pane.Markdown("## Stop Location"),
        *charts,
        sizing_mode="stretch_width",
    )
