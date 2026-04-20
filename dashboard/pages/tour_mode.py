"""Tour mode choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def purpose_options(mode_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect available purposes across all runs."""
    purpose_set = set()
    for _, df in mode_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purpose_set.update(df["tour_purpose"].drop_nulls().cast(pl.Utf8).to_list())
    return sorted(str(purpose) for purpose in purpose_set) if purpose_set else []


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


def charts_by_column(
    mode_list: list[tuple[str, pl.DataFrame]],
    purpose: str | None,
    columns: list[str] | None = None,
) -> dict[str, list[tuple[str, pl.DataFrame]]]:
    """Build chart-ready mode datasets for the selected purpose."""
    columns = columns or [
        "tour_count_all_households",
        "tour_count_zero_auto",
        "tour_count_auto_deficient",
        "tour_count_auto_sufficient",
    ]

    def filtered_df(df: pl.DataFrame, column: str) -> pl.DataFrame:
        if purpose is None:
            purpose_col = pl.col("tour_purpose").cast(pl.Utf8)
            return (
                df.filter(~purpose_col.is_in(["all_tour_purposes", "Total"]))
                .group_by("tour_mode")
                .agg(pl.col(column).sum().alias(column))
                .sort("tour_mode")
            )
        return (
            df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purpose)
            .select(["tour_mode", column])
            .sort("tour_mode")
        )

    return {
        col: [
            (
                label,
                filtered_df(df, col),
            )
            for label, df in mode_list
            if col in df.columns
        ]
        for col in columns
    }


class TourModePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Mode", state, config)
        total_opts = self._purpose_options()
        _, self._purpose_to_raw = purpose_mapping(
            [] if total_opts == ["Total"] else total_opts
        )
        if not self._purpose_to_raw:
            self._purpose_to_raw = {"Total": None}
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=total_opts, value=total_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Mode Choice"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        mode_list = self.state.get_summary_table_set(
            "tour_mode_by_tour_purpose_and_auto_sufficiency", "weighted"
        )
        if mode_list is None:
            return ["Total"]
        raw_purposes = purpose_options(mode_list)
        options, _ = purpose_mapping(raw_purposes)
        return options or ["Total"]

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        mode_list = summaries["tour_mode_by_tour_purpose_and_auto_sufficiency"]
        raw_purposes = purpose_options(mode_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)

        charts_by_col = self.get_filtered_view(
            "tour_mode",
            raw_purpose,
            factory=lambda: charts_by_column(mode_list, raw_purpose),
        )

        def make_chart(col: str, title: str):
            data = charts_by_col[col]
            return bar_chart(
                data,
                x_col="tour_mode",
                y_col=col,
                title=title,
                xaxis_title="Mode",
                as_percent=self.as_percent,
            )

        body = [
            pn.Row(
                make_chart("tour_count_all_households", "All Households"),
                make_chart("tour_count_zero_auto", "Zero Autos"),
            ),
            pn.Row(
                make_chart("tour_count_auto_deficient", "Autos < Workers"),
                make_chart("tour_count_auto_sufficient", "Autos >= Workers"),
            ),
        ]

        if self.config.mode_groups:
            grouped_list = self.require_summary("grouped_tour_mode_profile")
            if grouped_list is None:
                self._body.objects = [
                    self.data_not_available_card(
                        detail=(
                            "This page requires the grouped tour mode summary when mode groups are enabled."
                        ),
                        missing_items=["grouped_tour_mode_profile"],
                    )
                ]
                return
            body.extend(
                [
                    pn.pane.Markdown("### Grouped Mode Summary"),
                    bar_chart(
                        grouped_list,
                        x_col="mode_group",
                        y_col="freq_all",
                        title="Tour Mode (Grouped)",
                        xaxis_title="Mode Group",
                        as_percent=self.as_percent,
                    ),
                ]
            )

        self._body.objects = body


PAGE = DashboardPageDefinition(
    page_id="tour_mode",
    title="Tour Mode",
    order=70,
    controller_cls=TourModePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Purpose",
        ),
    ),
    required_summary_ids=("tour_mode_by_tour_purpose_and_auto_sufficiency",),
)

TourModePage.definition = PAGE
