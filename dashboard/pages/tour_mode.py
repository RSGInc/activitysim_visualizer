"""Tour mode choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from summarize.reader import Config


def purpose_options(mode_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect available purposes across all runs."""
    purpose_set = set()
    for _, df in mode_list:
        if len(df) > 0 and "purpose" in df.columns:
            purpose_set.update(df["purpose"].drop_nulls().to_list())
    purposes = sorted(list(purpose_set))
    return (
        (["Total"] + [p for p in purposes if p != "Total"]) if purposes else ["Total"]
    )


def charts_by_column(
    mode_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    columns: list[str] | None = None,
) -> dict[str, list[tuple[str, pl.DataFrame]]]:
    """Build chart-ready mode datasets for the selected purpose."""
    columns = columns or ["freq_all", "freq_as0", "freq_as1", "freq_as2"]
    return {
        col: [
            (
                label,
                df.filter(pl.col("purpose") == purpose).select(["tour_mode", col]),
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
        mode_list = self.state.get_summary_table_set("tour_mode_profile", "weighted")
        if mode_list is None:
            return ["Total"]
        return purpose_options(mode_list)

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

        mode_list = summaries["tour_mode_profile"]
        purp_opts = purpose_options(mode_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purp = self.purp_sel.value

        charts_by_col = self.get_filtered_view(
            "tour_mode",
            purp,
            factory=lambda: charts_by_column(mode_list, purp),
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
                make_chart("freq_all", "All Households"),
                make_chart("freq_as0", "Zero Autos"),
            ),
            pn.Row(
                make_chart("freq_as1", "Autos < Workers"),
                make_chart("freq_as2", "Autos >= Workers"),
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
    required_summary_ids=("tour_mode_profile",),
)

TourModePage.definition = PAGE
