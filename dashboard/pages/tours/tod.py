"""Tour time-of-day page: departure/arrival/duration profiles."""

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


def _duration_hours(timebin: int, maxbin: int) -> float:
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def purpose_options(tod_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Discover purpose options from TOD summaries."""
    purposes_set = set()
    for _, df in tod_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
    return sorted(str(purpose) for purpose in purposes_set) if purposes_set else []


def purpose_mapping(raw_purposes: list[str]) -> tuple[list[str], dict[str, str | None]]:
    """Build selector display values for tour-purpose summaries."""
    mapping: dict[str, str | None] = {}
    if "all_tour_purposes" in raw_purposes:
        mapping["Total"] = "all_tour_purposes"
    else:
        mapping["Total"] = None
    for purpose in raw_purposes:
        if purpose not in {"all_tour_purposes", "Total"}:
            mapping[purpose] = purpose
    return list(mapping), mapping


def max_timebin(tod_list: list[tuple[str, pl.DataFrame]]) -> int:
    """Return the maximum available timebin, defaulting to 48."""
    for _, df in tod_list:
        if len(df) > 0 and "time_bin" in df.columns:
            return int(df["time_bin"].max())
    return 48


def prep_profile(df: pl.DataFrame, purpose: str | None, val_col: str, maxbin: int) -> pl.DataFrame:
    """Prepare one tour TOD profile for plotting."""
    if purpose is None:
        purpose_col = pl.col("tour_purpose").cast(pl.Utf8)
        selected = (
            df.filter(~purpose_col.is_in(["all_tour_purposes", "Total"]))
            .group_by("time_bin")
            .agg(pl.col(val_col).sum().alias("freq"))
            .sort("time_bin")
        )
    else:
        selected = (
            df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purpose)
            .select(["time_bin", val_col])
            .rename({val_col: "freq"})
        )
    return selected.with_columns(
        pl.col("time_bin")
        .map_elements(lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8)
        .alias("clock_time")
    )


def chart_data(
    tod_list: list[tuple[str, pl.DataFrame]],
    purpose: str | None,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build departure, arrival, and duration datasets for one purpose."""
    maxbin = max_timebin(tod_list)
    dep_data = [
        (label, prep_profile(df, purpose, "departure_tour_count", maxbin))
        for label, df in tod_list
    ]
    arr_data = [
        (label, prep_profile(df, purpose, "arrival_tour_count", maxbin))
        for label, df in tod_list
    ]
    dur_data = [
        (
            label,
            prep_profile(df, purpose, "duration_tour_count", maxbin).with_columns(
                pl.col("time_bin")
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
        _, self._purpose_to_raw = purpose_mapping(
            [] if purp_opts == ["Total"] else purp_opts
        )
        if not self._purpose_to_raw:
            self._purpose_to_raw = {"Total": None}
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Time of Day"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        tod_result = self.state.inspect_summary_table(
            "tour_time_of_day_by_tour_purpose",
            weighting_key="weighted",
            required_columns=(
                "tour_purpose",
                "time_bin",
                "departure_tour_count",
                "arrival_tour_count",
                "duration_tour_count",
            ),
        )
        if not tod_result.has_usable_runs:
            return ["Total"]
        raw_purposes = purpose_options(
            [(label, table) for label, table in tod_result.usable_runs]
        )
        options, _ = purpose_mapping(raw_purposes)
        return options or ["Total"]

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        tod_result = self.resolve_summary_visualization(
            "tour_tod_profiles",
            summary_requirements={
                "tour_time_of_day_by_tour_purpose": (
                    "tour_purpose",
                    "time_bin",
                    "departure_tour_count",
                    "arrival_tour_count",
                    "duration_tour_count",
                )
            },
        )
        if not tod_result.has_usable_runs:
            self._body.objects = [
                self.unavailable_visualization(
                    tod_result,
                    detail="Tour time-of-day summaries are unavailable.",
                )
            ]
            return
        tod_list = tod_result.usable_by_input["tour_time_of_day_by_tour_purpose"]
        raw_purposes = purpose_options(tod_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)

        dep_data, arr_data, dur_data = self.get_filtered_view(
            "tour_tod",
            raw_purpose,
            tuple(label for label, _ in tod_list),
            factory=lambda: chart_data(tod_list, raw_purpose),
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
    group_id="tours",
    child_id="tod",
    child_order=20,
    controller_cls=TourTODPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Tour Purpose",
        ),
    ),
    required_summary_ids=("tour_time_of_day_by_tour_purpose",),
)

TourTODPage.definition = PAGE
