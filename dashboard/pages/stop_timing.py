"""Stop timing page: stop and trip departure profiles."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from summarize import stops
from summarize.reader import Config, RunData


def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def discover_purpose_columns(
    timing_list: list[tuple[str, pl.DataFrame]],
) -> tuple[list[str], dict[str, str | None]]:
    """Collect non-numeric purpose options and source columns from timing summaries."""
    run_to_purpose_col: dict[str, str | None] = {}
    purposes_set = set()
    for label, df in timing_list:
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in df.columns and not df[cand].dtype.is_numeric():
                run_to_purpose_col[label] = cand
                purposes_set.update(df[cand].drop_nulls().unique().to_list())
                break
        else:
            run_to_purpose_col[label] = None
    if purposes_set:
        return sorted(purposes_set), run_to_purpose_col
    return ["work"], run_to_purpose_col


def max_timebin(timing_list: list[tuple[str, pl.DataFrame]]) -> int:
    """Return the maximum available timebin, defaulting to 48."""
    for _, df in timing_list:
        if len(df) > 0 and "timebin" in df.columns:
            return int(df["timebin"].max())
    return 48


def prep_profile(
    df: pl.DataFrame,
    val_col: str,
    purpose: str,
    purpose_col: str | None,
    maxbin: int,
) -> pl.DataFrame:
    """Prepare one timing profile for plotting."""
    if purpose_col is None or purpose_col not in df.columns:
        return pl.DataFrame({"timebin": [], "freq": [], "clock_time": []})
    return (
        df.filter(pl.col(purpose_col) == purpose)
        .select(["timebin", val_col])
        .rename({val_col: "freq"})
        .with_columns(
            pl.col("timebin")
            .map_elements(lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8)
            .alias("clock_time")
        )
    )


def chart_data(
    timing_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    run_to_purpose_col: dict[str, str | None],
) -> tuple[list[tuple[str, pl.DataFrame]], list[tuple[str, pl.DataFrame]]]:
    """Build stop- and trip-departure profile datasets."""
    maxbin = max_timebin(timing_list)
    stop_dep = [
        (
            label,
            prep_profile(
                df, "freq_stop_dep", purpose, run_to_purpose_col.get(label), maxbin
            ),
        )
        for label, df in timing_list
    ]
    trip_dep = [
        (
            label,
            prep_profile(
                df, "freq_trip_dep", purpose, run_to_purpose_col.get(label), maxbin
            ),
        )
        for label, df in timing_list
    ]
    return stop_dep, trip_dep


class StopTimingPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Timing", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Stop Timing"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        timing_list = self.state.get_precomputed_summary("stop_timing", "weighted")
        if timing_list is None:
            timing_list = [(label, stops.stop_timing(rd)) for label, rd in runs]
        purp_opts, _ = discover_purpose_columns(timing_list)
        return purp_opts

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp = self.purp_sel.value
        timing_list = self.get_summary(
            "stop_timing",
            lambda: [(label, stops.stop_timing(rd)) for label, rd in runs],
        )
        purp_opts, run_to_purpose_col = discover_purpose_columns(timing_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value

        stop_dep, trip_dep = self.get_filtered_view(
            "stop_timing",
            purp,
            factory=lambda: chart_data(timing_list, purp, run_to_purpose_col),
        )
        x_label = "Clock time (start at 03:00)"

        self._body.objects = [
            density_chart(
                trip_dep,
                "clock_time",
                "freq",
                f"Trip Departure - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            density_chart(
                stop_dep,
                "clock_time",
                "freq",
                f"Stop Departure - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="stop_timing",
    title="Stop Timing",
    order=100,
    controller_cls=StopTimingPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Purpose",
        ),
    ),
)
