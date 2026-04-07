"""Stop frequency page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from summarize import stops
from summarize.reader import Config, RunData


def discover_purpose_columns(
    stop_list: list[tuple[str, pl.DataFrame]],
) -> tuple[list[str], dict[str, str]]:
    """Collect non-numeric purpose options and source columns from stop summaries."""
    purposes_set = set()
    purpose_col: dict[str, str] = {}
    for label, df in stop_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                purpose_col[label] = cand
                purposes_set.update(df[cand].drop_nulls().unique().to_list())
                break

    if purposes_set:
        return ["Total"] + sorted(purposes_set), purpose_col
    return ["Total"], purpose_col


def frequency_chart_data(
    stop_list: list[tuple[str, pl.DataFrame]],
    purp: str,
    purpose_col: dict[str, str],
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build outbound, inbound, and total stop-frequency datasets."""
    if len(purpose_col) == 0 or purp == "Total":
        ob_data = [
            (
                label,
                df.group_by("ob_stops")
                .agg(pl.col("freq").sum())
                .sort("ob_stops")
                .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.group_by("ib_stops")
                .agg(pl.col("freq").sum())
                .sort("ib_stops")
                .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.group_by("tot_stops")
                .agg(pl.col("freq").sum())
                .sort("tot_stops")
                .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    else:
        ob_data = [
            (
                label,
                df.filter(pl.col(purpose_col[label]) == purp)
                .group_by("ob_stops")
                .agg(pl.col("freq").sum())
                .sort("ob_stops")
                .with_columns(pl.col("ob_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.filter(pl.col(purpose_col[label]) == purp)
                .group_by("ib_stops")
                .agg(pl.col("freq").sum())
                .sort("ib_stops")
                .with_columns(pl.col("ib_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.filter(pl.col(purpose_col[label]) == purp)
                .group_by("tot_stops")
                .agg(pl.col("freq").sum())
                .sort("tot_stops")
                .with_columns(pl.col("tot_stops").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    return ob_data, ib_data, tot_data


def purpose_chart_data(
    purp_by_tp: list[tuple[str, pl.DataFrame]],
    purp: str,
    purpose_col: dict[str, str],
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-purpose chart data for the selected tour purpose."""
    if len(purpose_col) == 0 or purp == "Total":
        return [
            (label, df.group_by("purpose").agg(pl.col("freq").sum()))
            for label, df in purp_by_tp
        ]
    return [
        (label, df.filter(pl.col(purpose_col[label]) == purp))
        for label, df in purp_by_tp
    ]


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    stop_list = [(label, stops.stop_freq(rd)) for label, rd in runs]
    purp_by_tp = [(label, stops.stop_purpose_by_tour_purpose(rd)) for label, rd in runs]
    purp_opts, purpose_col = discover_purpose_columns(stop_list)

    purp_sel = pn.widgets.Select(
        name="Tour Purpose", options=purp_opts, value=purp_opts[0]
    )

    @pn.depends(purp_sel)
    def freq_charts(purp):
        ob_data, ib_data, tot_data = frequency_chart_data(stop_list, purp, purpose_col)
        return pn.Row(
            bar_chart(ob_data, "stops", "freq", f"Outbound Stops - {purp}", "Stops"),
            bar_chart(ib_data, "stops", "freq", f"Inbound Stops - {purp}", "Stops"),
            bar_chart(tot_data, "stops", "freq", f"Total Stops - {purp}", "Stops"),
        )

    @pn.depends(purp_sel)
    def purp_by_tp_chart(purp):
        return bar_chart(
            purpose_chart_data(purp_by_tp, purp, purpose_col),
            "purpose",
            "freq",
            f"Stop Purpose - tour={purp}",
            "Stop Purpose",
        )

    return pn.Column(
        pn.pane.Markdown("## Stop Frequency"),
        pn.Row(pn.pane.Markdown("**Tour Purpose:**"), purp_sel),
        freq_charts,
        purp_by_tp_chart,
        sizing_mode="stretch_width",
    )
