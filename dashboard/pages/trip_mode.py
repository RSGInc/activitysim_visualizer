"""Trip mode by tour mode cross-tab page built from canonical summary columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


def discover_options(
    trip_list: list[tuple[str, pl.DataFrame]],
) -> tuple[list[str], list[str]]:
    """Discover trip mode selector options from summary tables."""
    purposes_set = set()
    tmode_set = set()
    for _, df in trip_list:
        if "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
        if "tour_mode" in df.columns:
            tmode_set.update(
                df["tour_mode"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )

    return (
        sorted(str(purpose) for purpose in purposes_set),
        sorted(str(tour_mode) for tour_mode in tmode_set),
    )


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


def tour_mode_mapping(
    raw_tour_modes: list[str],
) -> tuple[list[str], dict[str, str | None]]:
    """Build selector display values for tour-mode summaries."""
    mapping: dict[str, str | None] = {}
    if "all_tour_modes" in raw_tour_modes:
        mapping["All"] = "all_tour_modes"
    else:
        mapping["All"] = None
    for tour_mode in raw_tour_modes:
        if tour_mode not in {"all_tour_modes", "All"}:
            mapping[tour_mode] = tour_mode
    return list(mapping), mapping


def chart_data(
    trip_list: list[tuple[str, pl.DataFrame]],
    purp: str | None,
    tmode: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build trip mode chart data for the selected purpose and tour mode."""

    def apply_filter(df: pl.DataFrame) -> pl.DataFrame:
        purpose_col = pl.col("tour_purpose").cast(pl.Utf8)
        tour_mode_col = pl.col("tour_mode").cast(pl.Utf8)
        if purp is None:
            df = df.filter(~purpose_col.is_in(["all_tour_purposes", "Total"]))
        else:
            df = df.filter(purpose_col == purp)
        if tmode is None:
            df = df.filter(~tour_mode_col.is_in(["all_tour_modes", "All"]))
        else:
            df = df.filter(tour_mode_col == tmode)
        return (
            df.group_by("trip_mode")
            .agg(pl.col("trip_count").sum().alias("trip_count"))
            .sort("trip_mode")
        )

    return [(label, apply_filter(df)) for label, df in trip_list]


class TripModePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Trip Mode", state, config)
        purp_opts, tmode_opts = self._options()
        _, self._purpose_to_raw = purpose_mapping(
            [] if purp_opts == ["Total"] else purp_opts
        )
        _, self._tour_mode_to_raw = tour_mode_mapping(
            [] if tmode_opts == ["All"] else tmode_opts
        )
        if not self._purpose_to_raw:
            self._purpose_to_raw = {"Total": None}
        if not self._tour_mode_to_raw:
            self._tour_mode_to_raw = {"All": None}
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value="Total"
        )
        self.tmode_sel = pn.widgets.Select(
            name="Tour Mode", options=tmode_opts, value="All"
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

    def _options(self) -> tuple[list[str], list[str]]:
        trip_result = self.state.inspect_summary_table(
            "trip_mode_by_tour_purpose_and_tour_mode",
            weighting_key="weighted",
            required_columns=("tour_purpose", "tour_mode", "trip_mode", "trip_count"),
        )
        if not trip_result.has_usable_runs:
            return ["Total"], ["All"]
        raw_purposes, raw_tour_modes = discover_options(
            [(label, table) for label, table in trip_result.usable_runs]
        )
        purp_opts, _ = purpose_mapping(raw_purposes)
        tmode_opts, _ = tour_mode_mapping(raw_tour_modes)
        return purp_opts or ["Total"], tmode_opts or ["All"]

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        trip_result = self.resolve_summary_visualization(
            "trip_mode_cross_tab",
            summary_requirements={
                "trip_mode_by_tour_purpose_and_tour_mode": (
                    "tour_purpose",
                    "tour_mode",
                    "trip_mode",
                    "trip_count",
                )
            },
        )
        if not trip_result.has_usable_runs:
            self._body.objects = [
                self.unavailable_visualization(
                    trip_result,
                    detail="Trip mode summaries are unavailable.",
                )
            ]
            return

        trip_list = trip_result.usable_by_input[
            "trip_mode_by_tour_purpose_and_tour_mode"
        ]
        purp = self.purp_sel.value
        tmode = self.tmode_sel.value
        raw_purposes, raw_tour_modes = discover_options(trip_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        tmode_opts, self._tour_mode_to_raw = tour_mode_mapping(raw_tour_modes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        if not tmode_opts:
            tmode_opts = ["All"]
            self._tour_mode_to_raw = {"All": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value
        self.tmode_sel.options = tmode_opts
        if self.tmode_sel.value not in self.tmode_sel.options:
            self.tmode_sel.value = "All"
            tmode = self.tmode_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)
        raw_tour_mode = self._tour_mode_to_raw.get(tmode)

        filtered_trip_mode = self.get_filtered_view(
            "trip_mode",
            raw_purpose,
            raw_tour_mode,
            tuple(label for label, _ in trip_list),
            factory=lambda: chart_data(trip_list, raw_purpose, raw_tour_mode),
        )

        self._body.objects = [
            bar_chart(
                filtered_trip_mode,
                "trip_mode",
                "trip_count",
                f"Trip Mode for {purp} Tours with {tmode} Tour Mode",
                "Trip Mode",
                as_percent=self.as_percent,
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="tp_mode",
    title="Old Trip Mode",
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
    export_regions=(
        PageExportRegionDefinition(
            region_id="legacy_trip_mode_body",
            view_attr="_body",
            selector_ids=("tour_purpose", "tour_mode"),
        ),
    ),
    required_summary_ids=("trip_mode_by_tour_purpose_and_tour_mode",),
)

TripModePage.definition = PAGE
