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

    loc_list = [(label, stops.stop_location(rd)) for label, rd in runs]
    first_df = next((df for _, df in loc_list if len(df) > 0), pl.DataFrame())
    if len(first_df) > 0 and "primary_purpose" in first_df.columns:
        purp_opts = sorted(first_df["primary_purpose"].drop_nulls().unique().to_list())
    else:
        purp_opts = []

    charts = []
    all_data = [(label, df.group_by("distbin").agg(pl.col("freq").sum()).sort("distbin")) for label, df in loc_list]
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
            (label, df.filter(pl.col("primary_purpose") == purp).select(["distbin", "freq"]))
            for label, df in loc_list
        ]
        charts.append(
            density_chart(
                data,
                "distbin",
                "freq",
                f"Stop Out-of-Direction Distance - {purp}",
                "Miles",
                normalize=False,
            )
        )

    return pn.Column(
        pn.pane.Markdown("## Stop Location"),
        *charts,
        sizing_mode="stretch_width",
    )
