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

    # Discover valid non-numeric purpose column for each df and gather options from all dataframes
    run_to_purpose_col = {}
    purposes_set = set()
    tmode_set = set()
    for l, df in trip_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                run_to_purpose_col[l] = cand
                purposes_set.update(df[cand].drop_nulls().unique().to_list())
                break
        else:
            run_to_purpose_col[l] = None
        if "tour_mode" in df.columns:
            tmode_set.update(df["tour_mode"].drop_nulls().unique().to_list())

    purp_opts = sorted(purposes_set) if purposes_set else ["work"]
    purp_opts = ["Total"] + [p for p in purp_opts if p != "Total"]
    tmode_opts = sorted(tmode_set) if tmode_set else []
    purp_sel = pn.widgets.Select(name="Tour Purpose", options=purp_opts, value="Total")
    tmode_sel = pn.widgets.Select(
        name="Tour Mode", options=["All"] + tmode_opts, value="All"
    )

    @pn.depends(purp_sel, tmode_sel)
    def trip_mode_chart(purp, tmode):
        def apply_filter(df, l):
            purpose_col = run_to_purpose_col.get(l)
            if purpose_col and purp != "Total" and purpose_col in df.columns:
                df = df.filter(pl.col(purpose_col) == purp)
            if tmode != "All" and "tour_mode" in df.columns:
                df = df.filter(pl.col("tour_mode") == tmode)
            return df.group_by("trip_mode").agg(pl.col("freq").sum()).sort("trip_mode")

        data = [(l, apply_filter(df, l)) for l, df in trip_list]
        return bar_chart(
            data,
            "trip_mode",
            "freq",
            f"Trip Mode — {purp} / Tour Mode: {tmode}",
            "Trip Mode",
        )

    return pn.Column(
        pn.pane.Markdown("## Trip Mode Choice"),
        pn.Row(purp_sel, tmode_sel),
        trip_mode_chart,
        sizing_mode="stretch_width",
    )
