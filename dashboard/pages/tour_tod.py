"""Tour time-of-day page: departure/arrival/duration profiles."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from summarize.reader import Config


def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def _duration_hours(timebin: int, maxbin: int) -> float:
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def purpose_options(tod_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Discover purpose options from TOD summaries."""
    first_df = next((df for _, df in tod_list if len(df) > 0), pl.DataFrame())
    if len(first_df) > 0 and "purpose" in first_df.columns:
        purposes = sorted(first_df["purpose"].drop_nulls().unique().to_list())
        return ["Total"] + [p for p in purposes if p != "Total"]
    return ["work"]


def max_timebin(tod_list: list[tuple[str, pl.DataFrame]]) -> int:
    """Return the maximum available timebin, defaulting to 48."""
    for _, df in tod_list:
        if len(df) > 0 and "timebin" in df.columns:
            return int(df["timebin"].max())
    return 48


def prep_profile(
    df: pl.DataFrame, purpose: str, val_col: str, maxbin: int
) -> pl.DataFrame:
    """Prepare one tour TOD profile for plotting."""
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
    tod_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build departure, arrival, and duration datasets for one purpose."""
    maxbin = max_timebin(tod_list)
    dep_data = [
        (label, prep_profile(df, purpose, "freq_dep", maxbin)) for label, df in tod_list
    ]
    arr_data = [
        (label, prep_profile(df, purpose, "freq_arr", maxbin)) for label, df in tod_list
    ]
    dur_data = [
        (
            label,
            prep_profile(df, purpose, "freq_dur", maxbin).with_columns(
                pl.col("timebin")
                .map_elements(
                    lambda tb: _duration_hours(int(tb), maxbin),
                    return_dtype=pl.Float64,
                )
                .alias("duration_hours")
            ),
        )
        for label, df in tod_list
    ]
    return dep_data, arr_data, dur_data


class TourTODPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour TOD", state, config)
        purp_opts = self._purpose_options()
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Time of Day"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        tod_list = self.state.get_summary_table_set("tour_tod_profiles", "weighted")
        if tod_list is None:
            return ["work"]
        return purpose_options(tod_list)

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        tod_list = self.require_summary("tour_tod_profiles")
        if tod_list is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return
        purp_opts = purpose_options(tod_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purp = self.purp_sel.value

        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_tod",
            purp,
            factory=lambda: chart_data(tod_list, purp),
        )
        x_label = "Clock time (start at 03:00)"
        dur_plot = density_chart(
            dur_data,
            "duration_hours",
            "freq",
            f"Duration - {purp}",
            "Duration (hours)",
            as_percent=self.as_percent,
        )
        dur_plot.object.update_xaxes(dtick=1, tick0=0, showgrid=True)

        self._body.objects = [
            density_chart(
                dep_data,
                "clock_time",
                "freq",
                f"Departure - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            density_chart(
                arr_data,
                "clock_time",
                "freq",
                f"Arrival - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            dur_plot,
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_tod",
    title="Tour TOD",
    order=60,
    controller_cls=TourTODPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Purpose",
        ),
    ),
    required_summary_ids=("tour_tod_profiles",),
)

TourTODPage.definition = PAGE
