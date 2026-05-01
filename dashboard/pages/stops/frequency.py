"""Stop frequency page built from canonical summary-table columns."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def purpose_options(stop_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    purposes_set = set()
    for _, df in stop_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purposes_set.update(
                df["tour_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
    return sorted(str(purpose) for purpose in purposes_set) if purposes_set else []


def purpose_mapping(raw_purposes: list[str]) -> tuple[list[str], dict[str, str | None]]:
    mapping: dict[str, str | None] = {}
    if "all_tour_purposes" in raw_purposes:
        mapping["Total"] = "all_tour_purposes"
    else:
        mapping["Total"] = None
    for purpose in raw_purposes:
        if purpose not in {"all_tour_purposes", "Total"}:
            mapping[purpose] = purpose
    return list(mapping), mapping


def frequency_chart_data(
    stop_list: list[tuple[str, pl.DataFrame]],
    purp: str | None,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    if purp is None:
        ob_data = [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose").cast(pl.Utf8).is_in(["all_tour_purposes", "Total"])
                )
                .group_by("outbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("outbound_stop_count")
                .with_columns(pl.col("outbound_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose").cast(pl.Utf8).is_in(["all_tour_purposes", "Total"])
                )
                .group_by("inbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("inbound_stop_count")
                .with_columns(pl.col("inbound_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose").cast(pl.Utf8).is_in(["all_tour_purposes", "Total"])
                )
                .group_by("total_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("total_stop_count")
                .with_columns(pl.col("total_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    else:
        ob_data = [
            (
                label,
                df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp)
                .group_by("outbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("outbound_stop_count")
                .with_columns(pl.col("outbound_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        ib_data = [
            (
                label,
                df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp)
                .group_by("inbound_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("inbound_stop_count")
                .with_columns(pl.col("inbound_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
        tot_data = [
            (
                label,
                df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp)
                .group_by("total_stop_count")
                .agg(pl.col("tour_count").sum().alias("freq"))
                .sort("total_stop_count")
                .with_columns(pl.col("total_stop_count").cast(pl.Utf8).alias("stops")),
            )
            for label, df in stop_list
        ]
    return ob_data, ib_data, tot_data


def purpose_chart_data(
    purp_by_tp: list[tuple[str, pl.DataFrame]],
    purp: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    if purp is None:
        return [
            (
                label,
                df.filter(
                    ~pl.col("tour_purpose").cast(pl.Utf8).is_in(["all_tour_purposes", "Total"])
                )
                .group_by("stop_destination_purpose")
                .agg(pl.col("stop_count").sum().alias("stop_count")),
            )
            for label, df in purp_by_tp
        ]
    return [
        (label, df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purp))
        for label, df in purp_by_tp
    ]


class StopFreqPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        purp_opts = self._purpose_options()
        _, self._purpose_to_raw = purpose_mapping([] if purp_opts == ["Total"] else purp_opts)
        if not self._purpose_to_raw:
            self._purpose_to_raw = {"Total": None}
        self.purp_sel = self.selector(
            "tour_purpose",
            widget=pn.widgets.Select(
                name="Tour Purpose",
                options=purp_opts,
                value=purp_opts[0],
            ),
            label="Tour Purpose",
        )
        self._body = self.section(
            "stop_frequency_body",
            selectors=("tour_purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Stop Frequency"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        stop_result = self.state.inspect_summary_table(
            "tour_stop_frequency_by_tour_purpose",
            weighting_key="weighted",
            required_columns=(
                "tour_purpose",
                "outbound_stop_count",
                "inbound_stop_count",
                "total_stop_count",
                "tour_count",
            ),
        )
        if not stop_result.has_usable_runs:
            return ["Total"]
        raw_purposes = purpose_options([(label, table) for label, table in stop_result.usable_runs])
        options, _ = purpose_mapping(raw_purposes)
        return options or ["Total"]

    def sync_controls(self) -> None:
        stop_result = self.resolve_summary_visualization(
            "stop_frequency_counts",
            summary_requirements={
                "tour_stop_frequency_by_tour_purpose": (
                    "tour_purpose",
                    "outbound_stop_count",
                    "inbound_stop_count",
                    "total_stop_count",
                    "tour_count",
                )
            },
        )
        raw_purposes = (
            purpose_options(stop_result.usable_by_input["tour_stop_frequency_by_tour_purpose"])
            if stop_result.has_usable_runs
            else []
        )
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        stop_result = self.resolve_summary_visualization(
            "stop_frequency_counts",
            summary_requirements={
                "tour_stop_frequency_by_tour_purpose": (
                    "tour_purpose",
                    "outbound_stop_count",
                    "inbound_stop_count",
                    "total_stop_count",
                    "tour_count",
                )
            },
        )
        purpose_result = self.resolve_summary_visualization(
            "stop_frequency_purpose",
            summary_requirements={
                "stop_destination_purpose_by_tour_purpose": (
                    "tour_purpose",
                    "stop_destination_purpose",
                    "stop_count",
                )
            },
        )
        purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)

        objects: list[pn.viewable.Viewable] = []
        if stop_result.has_usable_runs:
            stop_list = stop_result.usable_by_input["tour_stop_frequency_by_tour_purpose"]
            ob_data, ib_data, tot_data = self.get_filtered_view(
                "stop_freq_counts",
                raw_purpose,
                tuple(label for label, _ in stop_list),
                factory=lambda: frequency_chart_data(stop_list, raw_purpose),
            )
            objects.append(
                pn.Row(
                    bar_chart(ob_data, "stops", "freq", f"Outbound Stops - {purp}", "Stops", as_percent=self.as_percent),
                    bar_chart(ib_data, "stops", "freq", f"Inbound Stops - {purp}", "Stops", as_percent=self.as_percent),
                    bar_chart(tot_data, "stops", "freq", f"Total Stops - {purp}", "Stops", as_percent=self.as_percent),
                )
            )
        else:
            objects.append(
                self.unavailable_visualization(
                    stop_result,
                    detail="Stop frequency summaries are unavailable.",
                )
            )

        if purpose_result.has_usable_runs:
            purp_by_tp = purpose_result.usable_by_input["stop_destination_purpose_by_tour_purpose"]
            purp_chart = self.get_filtered_view(
                "stop_freq_purpose",
                raw_purpose,
                tuple(label for label, _ in purp_by_tp),
                factory=lambda: purpose_chart_data(purp_by_tp, raw_purpose),
            )
            objects.append(
                bar_chart(
                    purp_chart,
                    "stop_destination_purpose",
                    "stop_count",
                    f"Stop Purpose - tour={purp}",
                    "Stop Purpose",
                    as_percent=self.as_percent,
                )
            )
        else:
            objects.append(
                self.unavailable_visualization(
                    purpose_result,
                    detail="Stop destination purpose summaries are unavailable.",
                )
            )
        return objects


PAGE = DashboardPageDefinition(
    page_id="stop_frequency",
    title="Stop Frequency",
    group_id="stops",
    child_order=10,
    page_cls=StopFreqPage,
    required_summary_ids=(
        "tour_stop_frequency_by_tour_purpose",
        "stop_destination_purpose_by_tour_purpose",
    ),
)

StopFreqPage.definition = PAGE
