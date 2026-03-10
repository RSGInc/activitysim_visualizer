"""Trip mode by tour mode cross-tab page."""
from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart
from summarize.reader import RunData, Config
from summarize import trips


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    trip_list = [(l, trips.trip_mode_profile(rd, config)) for l, rd in runs]

    # Discover purposes and tour modes from first non-empty run
    first_df = next((df for _, df in trip_list if len(df) > 0), pl.DataFrame())
    if len(first_df) > 0:
        purp_opts  = sorted(first_df["primary_purpose"].drop_nulls().unique().to_list()) \
                     if "primary_purpose" in first_df.columns else ["work"]
        tmode_opts = sorted(first_df["tour_mode"].drop_nulls().unique().to_list()) \
                     if "tour_mode" in first_df.columns else []
    else:
        purp_opts = ["work"]
        tmode_opts = []

    purp_opts = ["Total"] + [p for p in purp_opts if p != "Total"]
    purp_sel  = pn.widgets.Select(name="Tour Purpose", options=purp_opts, value="Total")
    tmode_sel = pn.widgets.Select(name="Tour Mode", options=["All"] + tmode_opts, value="All")

    @pn.depends(purp_sel, tmode_sel)
    def trip_mode_chart(purp, tmode):
        def apply_filter(df):
            if purp != "Total" and "primary_purpose" in df.columns:
                df = df.filter(pl.col("primary_purpose") == purp)
            if tmode != "All" and "tour_mode" in df.columns:
                df = df.filter(pl.col("tour_mode") == tmode)
            return (df.group_by("trip_mode")
                    .agg(pl.col("freq").sum())
                    .sort("trip_mode"))

        data = [(l, apply_filter(df)) for l, df in trip_list]
        return bar_chart(data, "trip_mode", "freq",
                         f"Trip Mode — {purp} / Tour Mode: {tmode}", "Trip Mode")

    return pn.Column(
        pn.pane.Markdown("## Trip Mode Choice"),
        pn.Row(purp_sel, tmode_sel),
        trip_mode_chart,
        sizing_mode="stretch_width",
    )
