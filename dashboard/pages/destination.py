"""Destination page: NM tour distance distributions."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import _to_pandas, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def purpose_options(dist_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect destination purpose options from summary tables."""
    first_df = next((df for _, df in dist_list if len(df) > 0), pl.DataFrame())
    if len(first_df) == 0 or "purpose" not in first_df.columns:
        return ["All NM"]
    purposes = sorted(
        [
            purpose
            for purpose in first_df["purpose"]
            .cast(pl.Utf8)
            .drop_nulls()
            .unique()
            .to_list()
            if purpose != "All NM"
        ]
    )
    return ["All NM"] + purposes


def distance_chart_data(
    dist_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build destination distance chart data for one selected purpose."""
    return [
        (
            label,
            df.with_columns(pl.col("purpose").cast(pl.Utf8))
            .filter(pl.col("purpose") == purpose)
            .select(["distbin", "freq"]),
        )
        for label, df in dist_list
    ]


def average_distance_table(
    avg_list: list[tuple[str, pl.DataFrame]],
    purposes: list[str],
) -> pl.DataFrame:
    """Build the average destination distance comparison table from summaries."""
    rows = []
    for purp in purposes:
        row = {"Purpose": purp}
        for run_label, df in avg_list:
            value = None
            if len(df) > 0 and {"purpose", "avg_distance"}.issubset(df.columns):
                match = df.with_columns(pl.col("purpose").cast(pl.Utf8)).filter(
                    pl.col("purpose") == purp
                )
                if len(match) > 0:
                    value = match["avg_distance"][0]
            row[run_label] = round(float(value), 2) if value is not None else None
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()


class DestinationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Destination", state, config)
        purp_opts = self._purpose_options()
        self.purp_sel = pn.widgets.Select(
            name="Tour Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown(
                "## Destination Choice (Non-Mandatory (NM) Tour Distances)"
            ),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        dist_list = self.state.get_summary_table_set("destination_distance", "weighted")
        if dist_list is None:
            return ["All NM"]
        return purpose_options(dist_list)

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

        dist_list = summaries["destination_distance"]
        avg_list = summaries["destination_average_distance"]
        purp_opts = purpose_options(dist_list)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purpose = self.purp_sel.value
        data = self.get_filtered_view(
            "destination_dist",
            purpose,
            factory=lambda: distance_chart_data(dist_list, purpose),
        )
        avg_df = self.get_filtered_view(
            "destination_avg",
            tuple(self.purp_sel.options[1:]),
            factory=lambda: average_distance_table(
                avg_list, list(self.purp_sel.options[1:])
            ),
        )

        self._body.objects = [
            density_chart(
                data,
                "distbin",
                "freq",
                f"Non-Mandatory Tour Distance Distribution - {purpose}",
                "Distance (miles)",
                normalize=False,
                as_percent=self.as_percent,
            ),
            pn.pane.Markdown("### Average Tour Distances (miles)"),
            (
                pn.widgets.Tabulator(_to_pandas(avg_df), sizing_mode="stretch_width")
                if len(avg_df) > 0
                else pn.pane.Markdown("*(No distance data available)*")
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="destination",
    title="Destination",
    order=50,
    controller_cls=DestinationPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Tour Purpose",
        ),
    ),
    required_summary_ids=("destination_distance", "destination_average_distance"),
)

DestinationPage.definition = PAGE
