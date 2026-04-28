"""Trip mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    total_label: str = "All",
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    aggregate_label = f"all_{col}s"
    options = [total_label]
    options.extend(
        sorted(
            v for v in vals if v not in {total_label, aggregate_label}
        )
    )
    return options


def _raw_selector_value(column: str, value: str) -> str:
    if value == "All":
        return f"all_{column}s"
    return value


def trip_mode_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    tour_mode: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in _nonempty(data_list):
        df = df.with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
        )

        df = df.filter(pl.col("tour_purpose") == tour_purpose)
        df = df.filter(pl.col("tour_mode") == tour_mode)

        out.append((label, df))

    return out


class TripModePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Trip Mode", state, config)

        trip_mode_data = self.state.get_summary_table_set(
            "trip_mode_by_tour_purpose_and_tour_mode",
            "weighted",
        )

        purpose_opts = _options(trip_mode_data or [], "tour_purpose")
        mode_opts = _options(trip_mode_data or [], "tour_mode")

        self.tour_purpose_sel = pn.widgets.Select(
            name="Tour Purpose",
            options=purpose_opts,
            value=purpose_opts[0],
        )
        self._watch_widget(self.tour_purpose_sel)

        self.tour_mode_sel = pn.widgets.Select(
            name="Tour Mode",
            options=mode_opts,
            value=mode_opts[0],
        )
        self._watch_widget(self.tour_mode_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Trip Mode"),
            pn.Row(
                pn.pane.Markdown("**Tour Purpose:**"),
                self.tour_purpose_sel,
                pn.pane.Markdown("**Tour Mode:**"),
                self.tour_mode_sel,
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

        purpose_opts = _options(trip_mode_list, "tour_purpose")
        self.tour_purpose_sel.options = purpose_opts
        if self.tour_purpose_sel.value not in purpose_opts:
            self.tour_purpose_sel.value = purpose_opts[0]

        mode_opts = _options(trip_mode_list, "tour_mode")
        self.tour_mode_sel.options = mode_opts
        if self.tour_mode_sel.value not in mode_opts:
            self.tour_mode_sel.value = mode_opts[0]

        tour_purpose = self.tour_purpose_sel.value
        tour_mode = self.tour_mode_sel.value
        raw_tour_purpose = _raw_selector_value("tour_purpose", tour_purpose)
        raw_tour_mode = _raw_selector_value("tour_mode", tour_mode)

        trip_mode_data = self.get_filtered_view(
            "trip_mode",
            (raw_tour_purpose, raw_tour_mode),
            factory=lambda: trip_mode_chart_data(
                trip_mode_list,
                raw_tour_purpose,
                raw_tour_mode,
            ),
        )

        trip_mode_chart = bar_chart(
            trip_mode_data,
            x_col="trip_mode",
            y_col="trip_count",
            title=f"Trip Mode by Tour Mode and Tour Purpose - {tour_purpose}, {tour_mode}",
            xaxis_title="Trip Mode",
            yaxis_title="Trips",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            trip_mode_chart,
        ]


PAGE = DashboardPageDefinition(
    page_id="tp_mode",
    title="Old Trip Mode",
    group_id="trip_summaries",
    child_id="tp_mode",
    order=48,
    controller_cls=TripModePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="tour_purpose_sel",
            label="Tour Purpose",
        ),
        PageSelectorDefinition(
            selector_id="tour_mode",
            widget_attr="tour_mode_sel",
            label="Tour Mode",
        ),
    ),
    required_summary_ids=("trip_mode_by_tour_purpose_and_tour_mode",),
)

TripModePage.definition = PAGE
