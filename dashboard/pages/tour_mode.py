"""Tour mode choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from summarize import tour_mode as tm
from summarize.reader import Config, RunData


def purpose_options(mode_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect available purposes across all runs."""
    purpose_set = set()
    for _, df in mode_list:
        if len(df) > 0 and "purpose" in df.columns:
            purpose_set.update(df["purpose"].drop_nulls().to_list())
    purposes = sorted(list(purpose_set))
    return (
        (["Total"] + [p for p in purposes if p != "Total"]) if purposes else ["Total"]
    )


def charts_by_column(
    mode_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    columns: list[str] | None = None,
) -> dict[str, list[tuple[str, pl.DataFrame]]]:
    """Build chart-ready mode datasets for the selected purpose."""
    columns = columns or ["freq_all", "freq_as0", "freq_as1", "freq_as2"]
    return {
        col: [
            (
                label,
                df.filter(pl.col("purpose") == purpose).select(["tour_mode", col]),
            )
            for label, df in mode_list
            if col in df.columns
        ]
        for col in columns
    }


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    mode_list = [(label, tm.tour_mode_profile(rd, config)) for label, rd in runs]
    total_opts = purpose_options(mode_list)
    purp_sel = pn.widgets.Select(
        name="Purpose",
        options=total_opts,
        value=total_opts[0] if total_opts else "Total",
    )

    @pn.depends(purp_sel)
    def mode_charts(purp):
        by_col = charts_by_column(mode_list, purp)

        def make_chart(col: str, title: str):
            return bar_chart(
                by_col[col],
                x_col="tour_mode",
                y_col=col,
                title=title,
                xaxis_title="Mode",
            )

        return pn.Column(
            pn.Row(
                make_chart("freq_all", "All Households"),
                make_chart("freq_as0", "Zero Autos"),
            ),
            pn.Row(
                make_chart("freq_as1", "Autos < Workers"),
                make_chart("freq_as2", "Autos >= Workers"),
            ),
        )

    rows = [
        pn.pane.Markdown("## Tour Mode Choice"),
        pn.Row(pn.pane.Markdown("**Purpose:**"), purp_sel),
        mode_charts,
    ]

    if config.mode_groups:
        grouped_list = [
            (label, tm.grouped_tour_mode_profile(rd, config)) for label, rd in runs
        ]
        rows.append(pn.pane.Markdown("### Grouped Mode Summary"))
        rows.append(
            bar_chart(
                grouped_list,
                x_col="mode_group",
                y_col="freq_all",
                title="Tour Mode (Grouped)",
                xaxis_title="Mode Group",
            )
        )

    return pn.Column(*rows, sizing_mode="stretch_width")
