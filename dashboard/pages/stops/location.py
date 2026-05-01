"""Stop location page built from canonical summary-table columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


def purpose_options(loc_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect purpose options from stop-location summaries."""
    purposes_set = set()
    for _, df in loc_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
    return sorted(str(purpose) for purpose in purposes_set) if purposes_set else []


def purpose_mapping(raw_purposes: list[str]) -> tuple[list[str], dict[str, str | None]]:
    """Build selector display values for stop-location summaries."""
    mapping: dict[str, str | None] = {}
    if "all_tour_purposes" in raw_purposes:
        mapping["Total"] = "all_tour_purposes"
    else:
        mapping["Total"] = None
    for purpose in raw_purposes:
        if purpose not in {"all_tour_purposes", "Total"}:
            mapping[purpose] = purpose
    return list(mapping), mapping


def chart_data(
    loc_list: list[tuple[str, pl.DataFrame]],
    purpose: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build stop-location comparison data for the selected purpose."""
    if purpose is None:
        all_data: list[tuple[str, pl.DataFrame]] = []
        for label, df in loc_list:
            raw_purposes = (
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
                if "tour_purpose" in df.columns
                else []
            )
            if "all_tour_purposes" in raw_purposes:
                all_df = (
                    df.filter(pl.col("tour_purpose").cast(pl.Utf8) == "all_tour_purposes")
                    .select(["distance_bin", "stop_count"])
                    .sort("distance_bin")
                )
            else:
                all_df = (
                    df.filter(
                        ~pl.col("tour_purpose")
                        .cast(pl.Utf8)
                        .is_in(["all_tour_purposes", "Total"])
                    )
                    .group_by("distance_bin")
                    .agg(pl.col("stop_count").sum().alias("stop_count"))
                    .sort("distance_bin")
                )
            all_data.append((label, all_df))
        return all_data

    return [
        (
            label,
            df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purpose)
            .group_by("distance_bin")
            .agg(pl.col("stop_count").sum().alias("stop_count"))
            .sort("distance_bin"),
        )
        for label, df in loc_list
    ]


class StopLocationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Stop Location", state, config)
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
            pn.pane.Markdown("## Stop Location"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        loc_result = self.state.inspect_summary_table(
            "stop_out_of_direction_distance_by_tour_purpose",
            weighting_key="weighted",
            required_columns=("tour_purpose", "distance_bin", "stop_count"),
        )
        if not loc_result.has_usable_runs:
            return ["Total"]
        raw_purposes = purpose_options(
            [(label, table) for label, table in loc_result.usable_runs]
        )
        options, _ = purpose_mapping(raw_purposes)
        return options or ["Total"]

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        loc_result = self.resolve_summary_visualization(
            "stop_location_distance",
            summary_requirements={
                "stop_out_of_direction_distance_by_tour_purpose": (
                    "tour_purpose",
                    "distance_bin",
                    "stop_count",
                )
            },
        )
        if not loc_result.has_usable_runs:
            self._body.objects = [
                self.unavailable_visualization(
                    loc_result,
                    detail="Stop location summaries are unavailable.",
                )
            ]
            return

        loc_list = loc_result.usable_by_input[
            "stop_out_of_direction_distance_by_tour_purpose"
        ]
        purp = self.purp_sel.value
        raw_purposes = purpose_options(loc_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
            purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)

        self._body.objects = [
            density_chart(
                self.get_filtered_view(
                    "stop_location",
                    raw_purpose,
                    tuple(label for label, _ in loc_list),
                    factory=lambda: chart_data(loc_list, raw_purpose),
                ),
                "distance_bin",
                "stop_count",
                f"Stop Out-of-Direction Distance - {purp}",
                "Miles",
                normalize=False,
                as_percent=self.as_percent,
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="stop_location",
    title="Stop Location",
    group_id="stops",
    child_order=20,
    page_cls=StopLocationPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Tour Purpose",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="stop_location_body",
            view_attr="_body",
            selector_ids=("purpose",),
        ),
    ),
    required_summary_ids=("stop_out_of_direction_distance_by_tour_purpose",),
)

StopLocationPage.definition = PAGE

