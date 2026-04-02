"""Tour time-of-day page: departure/arrival/duration profiles."""

from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import density_chart
from summarize.reader import RunData, Config
from summarize import tour_tod


def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def _duration_hours(timebin: int, maxbin: int) -> float:
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    tod_list = [(l, tour_tod.tod_profiles(rd)) for l, rd in runs]

    # Discover purpose options from data
    first_df = next((df for _, df in tod_list if len(df) > 0), pl.DataFrame())
    if len(first_df) > 0 and "purpose" in first_df.columns:
        purposes = sorted(first_df["purpose"].drop_nulls().unique().to_list())
        total_first = ["Total"] + [p for p in purposes if p != "Total"]
        purp_opts = total_first
    else:
        purp_opts = ["work"]

    purp_sel = pn.widgets.Select(name="Purpose", options=purp_opts, value=purp_opts[0])

    @pn.depends(purp_sel)
    def tod_charts(purp):
        maxbin = 48
        for _, df in tod_list:
            if len(df) > 0 and "timebin" in df.columns:
                maxbin = int(df["timebin"].max())
                break

        def _prep(df: pl.DataFrame, val_col: str) -> pl.DataFrame:
            return (
                df.filter(pl.col("purpose") == purp)
                .select(["timebin", val_col])
                .rename({val_col: "freq"})
                .with_columns(
                    pl.col("timebin")
                    .map_elements(
                        lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8
                    )
                    .alias("clock_time")
                )
            )

        dep_data = [(l, _prep(df, "freq_dep")) for l, df in tod_list]
        arr_data = [(l, _prep(df, "freq_arr")) for l, df in tod_list]
        dur_data = [
            (
                l,
                _prep(df, "freq_dur").with_columns(
                    pl.col("timebin")
                    .map_elements(
                        lambda tb: _duration_hours(int(tb), maxbin),
                        return_dtype=pl.Float64,
                    )
                    .alias("duration_hours")
                ),
            )
            for l, df in tod_list
        ]
        x_label = "Clock time (start at 03:00)"
        dur_plot = density_chart(
            dur_data, "duration_hours", "freq", f"Duration — {purp}", "Duration (hours)"
        )
        dur_plot.object.update_xaxes(dtick=1, tick0=0, showgrid=True)
        return pn.Column(
            density_chart(
                dep_data, "clock_time", "freq", f"Departure — {purp}", x_label
            ),
            density_chart(arr_data, "clock_time", "freq", f"Arrival — {purp}", x_label),
            dur_plot,
        )

    return pn.Column(
        pn.pane.Markdown("## Tour Time of Day"),
        pn.Row(pn.pane.Markdown("**Purpose:**"), purp_sel),
        tod_charts,
        sizing_mode="stretch_width",
    )
