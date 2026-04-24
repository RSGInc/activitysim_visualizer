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
    """Collect purpose options from stop-timing summaries."""
    purposes_set = set()
    for _, df in timing_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
    return sorted(str(purpose) for purpose in purposes_set) if purposes_set else []


def purpose_mapping(raw_purposes: list[str]) -> tuple[list[str], dict[str, str]]:
    """Build selector display values for stop-timing summaries."""
    mapping: dict[str, str] = {}
    if "all_tour_purposes" in raw_purposes:
        mapping["Total"] = "all_tour_purposes"
    for purpose in raw_purposes:
        if purpose not in {"all_tour_purposes", "Total"}:
            mapping[purpose] = purpose
    return list(mapping), mapping


def max_timebin(timing_list: list[tuple[str, pl.DataFrame]]) -> int:
    """Return the maximum available timebin, defaulting to 48."""
    for _, df in timing_list:
        if len(df) > 0 and "time_bin" in df.columns:
            return int(df["time_bin"].max())
    return 48


def prep_profile(
    df: pl.DataFrame,
    val_col: str,
    purpose: str,
    maxbin: int,
) -> pl.DataFrame:
    """Prepare one timing profile for plotting."""
    return (
        df.filter(pl.col("tour_purpose") == purpose)
        .select(["time_bin", val_col])
        .rename({val_col: "freq"})
        .with_columns(
            pl.col("time_bin")
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
        (label, prep_profile(df, "departure_stop_count", purpose, maxbin))
        for label, df in timing_list
    ]
    trip_dep = [
        (label, prep_profile(df, "departure_trip_count", purpose, maxbin))
        for label, df in timing_list
    ]
    return stop_dep, trip_dep


class StopTimingPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Timing", state, config)
        purp_opts = self._purpose_options() or ["Total"]
        _, self._purpose_to_raw = purpose_mapping(
            [] if purp_opts == ["Total"] else purp_opts
        )
        if not self._purpose_to_raw:
            self._purpose_to_raw = {option: option for option in purp_opts}
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Stop Timing"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        timing_result = self.state.inspect_summary_table(
            "trip_departure_time_by_purpose",
            weighting_key="weighted",
            required_columns=(
                "tour_purpose",
                "time_bin",
                "departure_stop_count",
                "departure_trip_count",
            ),
        )
        if not timing_result.has_usable_runs:
            return ["Total"]
        raw_purposes = purpose_options(
            [(label, table) for label, table in timing_result.usable_runs]
        )
        options, _ = purpose_mapping(raw_purposes)
        return options or sorted(
            purpose for purpose in raw_purposes if purpose != "all_tour_purposes"
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        timing_result = self.resolve_summary_visualization(
            "stop_timing_profiles",
            summary_requirements={
                "trip_departure_time_by_purpose": (
                    "tour_purpose",
                    "time_bin",
                    "departure_stop_count",
                    "departure_trip_count",
                )
            },
        )
        if not timing_result.has_usable_runs:
            self._body.objects = [
                self.unavailable_visualization(
                    timing_result,
                    detail="Stop timing summaries are unavailable.",
                )
            ]
            return

        timing_list = timing_result.usable_by_input["trip_departure_time_by_purpose"]
        purp = self.purp_sel.value
        raw_purposes = purpose_options(timing_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = sorted(
                purpose for purpose in raw_purposes if purpose != "all_tour_purposes"
            )
            self._purpose_to_raw = {purpose: purpose for purpose in purp_opts}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp, purp)

        stop_dep, trip_dep = self.get_filtered_view(
            "stop_timing",
            raw_purpose,
            tuple(label for label, _ in timing_list),
            factory=lambda: chart_data(timing_list, str(raw_purpose)),
        )
        x_label = "Clock time (start at 03:00)"

        self._body.objects = [
            density_chart(
                trip_dep,
                "clock_time",
                "freq",
                f"Trip Departure Time - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
            density_chart(
                stop_dep,
                "clock_time",
                "freq",
                f"Stop Departure Time - {purp}",
                x_label,
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="stop_timing",
    title="Stop Timing",
    group_id="stops",
    child_id="timing",
    child_order=30,
    controller_cls=StopTimingPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Tour Purpose",
        ),
    ),
    required_summary_ids=("trip_departure_time_by_purpose",),
)

StopTimingPage.definition = PAGE
