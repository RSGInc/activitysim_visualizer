"""Stop timing page: stop and trip departure profiles."""
from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import density_chart
from summarize.reader import RunData, Config
from summarize import stops

def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    timing_list = [(l, stops.stop_timing(rd)) for l, rd in runs]

    # Discover valid non-numeric purpose column for each df and collect all purpose options
    run_to_purpose_col = {}
    purposes_set = set()
    for l, df in timing_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                run_to_purpose_col[l] = cand
                purposes_set.update(df[cand].drop_nulls().unique().to_list())
                break
        else:
            run_to_purpose_col[l] = None
    if purposes_set:
        purp_opts = sorted(purposes_set)
    else:
        purp_opts = ["work"]

    purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value=purp_opts[0])

    @pn.depends(purp_sel)
    def timing_charts(purp):
        maxbin = 48
        for _, df in timing_list:
            if len(df) > 0 and "timebin" in df.columns:
                maxbin = int(df["timebin"].max())
                break

        def _prep(df: pl.DataFrame, val_col: str, l: str) -> pl.DataFrame:
            purpose_col = run_to_purpose_col.get(l)
            if purpose_col is None or purpose_col not in df.columns:
                return pl.DataFrame({"timebin": [], "freq": [], "clock_time": []})
            return (df.filter(pl.col(purpose_col) == purp)
                    .select(["timebin", val_col])
                    .rename({val_col: "freq"})
                    .with_columns(
                        pl.col("timebin").map_elements(
                            lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8
                        ).alias("clock_time")
                    ))

        stop_dep = [(l, _prep(df, "freq_stop_dep", l)) for l, df in timing_list]
        trip_dep = [(l, _prep(df, "freq_trip_dep", l)) for l, df in timing_list]
        x_label = "Clock time (start at 03:00)"
        return pn.Column(
            density_chart(trip_dep, "clock_time", "freq", f"Trip Departure — {purp}", x_label),
            density_chart(stop_dep, "clock_time", "freq", f"Stop Departure — {purp}", x_label),
        )

    return pn.Column(
        pn.pane.Markdown("## Stop Timing"),
        pn.Row(pn.pane.Markdown("**Purpose:**"), purp_sel),
        timing_charts,
        sizing_mode="stretch_width",
    )