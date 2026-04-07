"""Trip mode by tour mode cross-tab page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from summarize import trips
from summarize.reader import Config, RunData


def discover_options(
    trip_list: list[tuple[str, pl.DataFrame]],
) -> tuple[list[str], list[str], dict[str, str | None]]:
    """Discover trip mode selector options from summary tables."""
    run_to_purpose_col: dict[str, str | None] = {}
    purposes_set = set()
    tmode_set = set()
    for label, df in trip_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                run_to_purpose_col[label] = cand
                purposes_set.update(df[cand].drop_nulls().unique().to_list())
                break
        else:
            run_to_purpose_col[label] = None
        if "tour_mode" in df.columns:
            tmode_set.update(df["tour_mode"].drop_nulls().unique().to_list())

    purp_opts = sorted(purposes_set) if purposes_set else ["work"]
    purp_opts = ["Total"] + [p for p in purp_opts if p != "Total"]
    tmode_opts = sorted(tmode_set) if tmode_set else []
    return purp_opts, tmode_opts, run_to_purpose_col


def chart_data(
    trip_list: list[tuple[str, pl.DataFrame]],
    purp: str,
    tmode: str,
    run_to_purpose_col: dict[str, str | None],
) -> list[tuple[str, pl.DataFrame]]:
    """Build trip mode chart data for the selected purpose and tour mode."""

    def apply_filter(df: pl.DataFrame, label: str) -> pl.DataFrame:
        purpose_col = run_to_purpose_col.get(label)
        if purpose_col and purp != "Total" and purpose_col in df.columns:
            df = df.filter(pl.col(purpose_col) == purp)
        if tmode != "All" and "tour_mode" in df.columns:
            df = df.filter(pl.col("tour_mode") == tmode)
        return df.group_by("trip_mode").agg(pl.col("freq").sum()).sort("trip_mode")

    return [(label, apply_filter(df, label)) for label, df in trip_list]


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    trip_list = [(label, trips.trip_mode_profile(rd, config)) for label, rd in runs]
    purp_opts, tmode_opts, run_to_purpose_col = discover_options(trip_list)

    purp_sel = pn.widgets.Select(name="Tour Purpose", options=purp_opts, value="Total")
    tmode_sel = pn.widgets.Select(
        name="Tour Mode", options=["All"] + tmode_opts, value="All"
    )

    @pn.depends(purp_sel, tmode_sel)
    def trip_mode_chart(purp, tmode):
        return bar_chart(
            chart_data(trip_list, purp, tmode, run_to_purpose_col),
            "trip_mode",
            "freq",
            f"Trip Mode - {purp} / Tour Mode: {tmode}",
            "Trip Mode",
        )

    return pn.Column(
        pn.pane.Markdown("## Trip Mode Choice"),
        pn.Row(purp_sel, tmode_sel),
        trip_mode_chart,
        sizing_mode="stretch_width",
    )
