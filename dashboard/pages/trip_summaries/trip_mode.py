"""Trip mode page."""

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


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _tour_purpose_options(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "tour_purpose" not in first_df.columns:
        return ["All"]

    vals = (
        first_df.select("tour_purpose")
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    options = ["All"]
    options.extend(
        sorted(v for v in vals if v not in {"All", "all_tour_purposes"})
    )
    return options


def _raw_tour_purpose(value: str) -> str:
    return "all_tour_purposes" if value == "All" else value


def _tour_mode_labels(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "tour_mode" not in first_df.columns:
        return []
    vals = (
        first_df.select("tour_mode").drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    return sorted(v for v in vals if v not in {"All", "all_tour_modes"})


def _filtered_trip_mode_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    *,
    tour_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        filtered = df.with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
            pl.col("trip_mode").cast(pl.Utf8),
        ).filter(pl.col("tour_purpose") == tour_purpose)
        if tour_mode is None:
            filtered = filtered.filter(pl.col("tour_mode") == "all_tour_modes")
        else:
            filtered = filtered.filter(pl.col("tour_mode") == tour_mode)
        out.append((label, filtered.sort("trip_mode")))
    return out


class TripModePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Trip Mode", state, config)

        trip_mode_data = self.state.get_summary_table_set(
            "trip_mode_by_tour_purpose_and_tour_mode",
            "weighted",
        )
        purpose_opts = _tour_purpose_options(trip_mode_data or [])

        self.tour_purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=purpose_opts,
            value=purpose_opts[0],
        )
        self._watch_widget(self.tour_purpose_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Trip Mode"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.tour_purpose_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

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

        trip_mode_list = summaries["trip_mode_by_tour_purpose_and_tour_mode"]
        purpose_opts = _tour_purpose_options(trip_mode_list)
        self.tour_purpose_sel.options = purpose_opts
        if self.tour_purpose_sel.value not in purpose_opts:
            self.tour_purpose_sel.value = purpose_opts[0]

        tour_purpose = self.tour_purpose_sel.value
        raw_tour_purpose = _raw_tour_purpose(tour_purpose)
        mode_labels = _tour_mode_labels(trip_mode_list)

        overall_data = self.get_filtered_view(
            "trip_mode_overall",
            raw_tour_purpose,
            factory=lambda: _filtered_trip_mode_data(
                trip_mode_list,
                raw_tour_purpose,
            ),
        )

        grid_cards: list[pn.viewable.Viewable] = []
        for tour_mode in mode_labels:
            mode_data = self.get_filtered_view(
                "trip_mode_grid",
                (raw_tour_purpose, tour_mode),
                factory=lambda tm=tour_mode: _filtered_trip_mode_data(
                    trip_mode_list,
                    raw_tour_purpose,
                    tour_mode=tm,
                ),
            )
            grid_cards.append(
                bar_chart(
                    mode_data,
                    x_col="trip_mode",
                    y_col="trip_count",
                    title=f"Trip Mode Distribution - {tour_mode}",
                    xaxis_title="Trip Mode",
                    yaxis_title="Trips",
                    pct_col="pct",
                    as_percent=self.as_percent,
                    height=320,
                )
            )

        grid_rows: list[pn.Row] = []
        row_size = 2
        for start in range(0, len(grid_cards), row_size):
            grid_rows.append(pn.Row(*grid_cards[start : start + row_size], sizing_mode="stretch_width"))

        self._body.objects = [
            bar_chart(
                overall_data,
                x_col="trip_mode",
                y_col="trip_count",
                title=f"Trip Mode Distribution - {tour_purpose}",
                xaxis_title="Trip Mode",
                yaxis_title="Trips",
                pct_col="pct",
                as_percent=self.as_percent,
            ),
            pn.pane.Markdown("### Trip Mode by Tour Mode"),
            *grid_rows,
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_mode",
    title="Trip Mode",
    group_id="trip_summaries",
    child_id="trip_mode",
    order=48,
    controller_cls=TripModePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="tour_purpose_sel",
            label="Tour Purpose",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="trip_summary_mode_body",
            view_attr="_body",
            selector_ids=("tour_purpose",),
        ),
    ),
    required_summary_ids=("trip_mode_by_tour_purpose_and_tour_mode",),
)

TripModePage.definition = PAGE
