"""Stop timing page built from canonical summary-table columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def purpose_options(timing_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect purpose options from canonical stop-timing summaries."""
    purposes_set = set()
    for _, df in timing_list:
        if len(df) > 0 and "purpose" in df.columns:
            purposes_set.update(df["purpose"].drop_nulls().cast(pl.Utf8).unique().to_list())
    return sorted(purposes_set) if purposes_set else ["Total"]


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
    maxbin: int,
) -> pl.DataFrame:
    """Prepare one timing profile for plotting."""
    return (
        df.filter(pl.col("purpose") == purpose)
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
) -> tuple[list[tuple[str, pl.DataFrame]], list[tuple[str, pl.DataFrame]]]:
    """Build stop- and trip-departure profile datasets."""
    maxbin = max_timebin(timing_list)
    stop_dep = [
        (
            label,
            prep_profile(df, "freq_stop_dep", purpose, maxbin),
        )
        for label, df in timing_list
    ]
    trip_dep = [
        (
            label,
            prep_profile(df, "freq_trip_dep", purpose, maxbin),
        )
        for label, df in timing_list
    ]
    return stop_dep, trip_dep


class StopTimingPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Timing", state, config)
        purp_opts = self._purpose_options()
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

    def _purpose_options(self) -> list[str]:
        timing_list = self.state.get_summary_table_set("stop_timing", "weighted")
        if timing_list is None:
            return ["Total"]
        return purpose_options(timing_list)

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        timing_list = self.require_summary("stop_timing")
        if timing_list is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        purp = self.purp_sel.value
        purp_opts = purpose_options(timing_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value

        stop_dep, trip_dep = self.get_filtered_view(
            "stop_timing",
            purp,
            factory=lambda: chart_data(timing_list, purp),
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
    required_summary_ids=("stop_timing",),
)

StopTimingPage.definition = PAGE
