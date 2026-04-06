"""Stop frequency page."""

from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart
from summarize.reader import RunData, Config
from summarize import stops


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    stop_list = [(l, stops.stop_freq(rd)) for l, rd in runs]
    purp_by_tp = [(l, stops.stop_purpose_by_tour_purpose(rd)) for l, rd in runs]

    # Collect all valid non-numeric purpose columns from all runs
    purposes_set = set()
    purpose_col = dict()
    for l, df in stop_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                purpose_col[l] = cand
                purposes_set.update(df[cand].drop_nulls().unique().to_list())
                break

    if purposes_set:
        purp_opts = ["Total"] + sorted(purposes_set)
    else:
        purp_opts = ["Total"]

    purp_sel = pn.widgets.Select(
        name="Tour Purpose", options=purp_opts, value=purp_opts[0]
    )

    @pn.depends(purp_sel)
    def freq_charts(purp):
        if len(purpose_col) == 0 or purp == "Total":
            # fallback to original logic if no valid purpose_col found
            ob_data = [
                (
                    l,
                    df.group_by("ob_stops")
                    .agg(pl.col("freq").sum())
                    .sort("ob_stops")
                    .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
                )
                for l, df in stop_list
            ]
            ib_data = [
                (
                    l,
                    df.group_by("ib_stops")
                    .agg(pl.col("freq").sum())
                    .sort("ib_stops")
                    .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
                )
                for l, df in stop_list
            ]
            tot_data = [
                (
                    l,
                    df.group_by("tot_stops")
                    .agg(pl.col("freq").sum())
                    .sort("tot_stops")
                    .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
                )
                for l, df in stop_list
            ]
        else:
            ob_data = [
                (
                    l,
                    df.filter(pl.col(purpose_col[l]) == purp)
                    .group_by("ob_stops")
                    .agg(pl.col("freq").sum())
                    .sort("ob_stops")
                    .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
                )
                for l, df in stop_list
            ]
            ib_data = [
                (
                    l,
                    df.filter(pl.col(purpose_col[l]) == purp)
                    .group_by("ib_stops")
                    .agg(pl.col("freq").sum())
                    .sort("ib_stops")
                    .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
                )
                for l, df in stop_list
            ]
            tot_data = [
                (
                    l,
                    df.filter(pl.col(purpose_col[l]) == purp)
                    .group_by("tot_stops")
                    .agg(pl.col("freq").sum())
                    .sort("tot_stops")
                    .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
                )
                for l, df in stop_list
            ]

        return pn.Row(
            bar_chart(ob_data, "stops", "freq", f"Outbound Stops — {purp}", "Stops"),
            bar_chart(ib_data, "stops", "freq", f"Inbound Stops — {purp}", "Stops"),
            bar_chart(tot_data, "stops", "freq", f"Total Stops — {purp}", "Stops"),
        )

    @pn.depends(purp_sel)
    def purp_by_tp_chart(purp):
        if len(purpose_col) == 0 or purp == "Total":
            data = [
                (l, df.group_by("purpose").agg(pl.col("freq").sum()))
                for l, df in purp_by_tp
            ]
        else:
            data = [
                (l, df.filter(pl.col(purpose_col[l]) == purp)) for l, df in purp_by_tp
            ]
        return bar_chart(
            data, "purpose", "freq", f"Stop Purpose — tour={purp}", "Stop Purpose"
        )

    return pn.Column(
        pn.pane.Markdown("## Stop Frequency"),
        pn.Row(pn.pane.Markdown("**Tour Purpose:**"), purp_sel),
        freq_charts,
        purp_by_tp_chart,
        sizing_mode="stretch_width",
    )
