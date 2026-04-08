"""Stop location page: out-of-direction distance."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from summarize import stops
from summarize.reader import Config, RunData


def discover_purpose_columns(
    loc_list: list[tuple[str, pl.DataFrame]],
) -> tuple[list[str], dict[str, str | None]]:
    """Collect non-numeric purpose options and source columns from location summaries."""
    purposes_set = set()
    run_to_purpose_col: dict[str, str | None] = {}
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
    return sorted(purposes_set) if purposes_set else [], run_to_purpose_col


def all_purpose_chart_data(
    loc_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Build the all-purpose stop-location comparison data."""
    return [
        (label, df.group_by("distbin").agg(pl.col("freq").sum()).sort("distbin"))
        for label, df in loc_list
    ]


def purpose_chart_data(
    loc_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    run_to_purpose_col: dict[str, str | None],
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-location comparison data for one purpose."""
    return [
        (
            label,
            (
                df.filter(pl.col(run_to_purpose_col[label]) == purpose).select(
                    ["distbin", "freq"]
                )
                if run_to_purpose_col.get(label) is not None
                else pl.DataFrame({"distbin": [], "freq": []})
            ),
        )
        for label, df in loc_list
    ]


class StopLocationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Location", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = self._body

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        loc_list = self.get_summary(
            "stop_location",
            lambda: [(label, stops.stop_location(rd)) for label, rd in runs],
        )
        purp_opts, run_to_purpose_col = discover_purpose_columns(loc_list)

        charts = [
            density_chart(
                self.get_filtered_view(
                    "stop_location_all",
                    factory=lambda: all_purpose_chart_data(loc_list),
                ),
                "distbin",
                "freq",
                "Stop Out-of-Direction Distance - All Purposes",
                "Miles",
                normalize=False,
                as_percent=self.as_percent,
            )
        ]
        for purp in purp_opts:
            charts.append(
                density_chart(
                    self.get_filtered_view(
                        "stop_location",
                        purp,
                        factory=lambda purp=purp: purpose_chart_data(
                            loc_list, purp, run_to_purpose_col
                        ),
                    ),
                    "distbin",
                    "freq",
                    f"Stop Out-of-Direction Distance - {purp}",
                    "Miles",
                    normalize=False,
                    as_percent=self.as_percent,
                )
            )

        self._body.objects = [pn.pane.Markdown("## Stop Location"), *charts]


PAGE = DashboardPageDefinition(
    page_id="stop_location",
    title="Stop Location",
    order=90,
    controller_cls=StopLocationPage,
)
