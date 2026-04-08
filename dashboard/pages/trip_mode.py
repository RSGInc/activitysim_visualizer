"""Trip mode by tour mode cross-tab page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
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


class TripModePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Trip Mode", state, config)
        purp_opts, tmode_opts = self._options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value="Total"
        )
        self.tmode_sel = pn.widgets.Select(
            name="Tour Mode", options=["All"] + tmode_opts, value="All"
        )
        self._watch_widget(self.purp_sel)
        self._watch_widget(self.tmode_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Trip Mode Choice"),
            pn.Row(self.purp_sel, self.tmode_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _options(self, runs: list[tuple[str, RunData]]) -> tuple[list[str], list[str]]:
        trip_list = self.state.get_precomputed_summary("trip_mode_profile", "weighted")
        if trip_list is None:
            trip_list = [
                (label, trips.trip_mode_profile(rd, self.config)) for label, rd in runs
            ]
        purp_opts, tmode_opts, _ = discover_options(trip_list)
        return purp_opts, tmode_opts

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        tmode = self.tmode_sel.value
        trip_list = self.get_summary(
            "trip_mode_profile",
            lambda: [
                (label, trips.trip_mode_profile(rd, self.config)) for label, rd in runs
            ],
        )
        purp_opts, tmode_opts, run_to_purpose_col = discover_options(trip_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value
        self.tmode_sel.options = ["All"] + tmode_opts
        if self.tmode_sel.value not in self.tmode_sel.options:
            self.tmode_sel.value = "All"
            tmode = self.tmode_sel.value

        filtered_trip_mode = self.get_filtered_view(
            "trip_mode",
            purp,
            tmode,
            factory=lambda: chart_data(trip_list, purp, tmode, run_to_purpose_col),
        )

        self._body.objects = [
            bar_chart(
                filtered_trip_mode,
                "trip_mode",
                "freq",
                f"Trip Mode - {purp} / Tour Mode: {tmode}",
                "Trip Mode",
                as_percent=self.as_percent,
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_mode",
    title="Trip Mode",
    order=110,
    controller_cls=TripModePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="purp_sel",
            label="Tour Purpose",
        ),
        PageSelectorDefinition(
            selector_id="tour_mode",
            widget_attr="tmode_sel",
            label="Tour Mode",
        ),
    ),
)
