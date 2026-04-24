"""Escorted tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


DIRECTION_COL = "direction"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def direction_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or DIRECTION_COL not in first_df.columns:
        return ["Both"]

    vals = (
        first_df.select(DIRECTION_COL)
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return ["Both"] + sorted(v for v in vals if v != "Both")


def escort_school_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))

        if direction != "Both" and DIRECTION_COL in df.columns:
            df = df.filter(pl.col(DIRECTION_COL) == direction)

        out.append((label, df))

    return out


class EscortedToursPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Escorted Tours", state, config)

        direction_opts = self._direction_options()
        self.direction_sel = pn.widgets.Select(
            name="Direction",
            options=direction_opts,
            value=direction_opts[0],
        )
        self._watch_widget(self.direction_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Escorted Tours"),
            self._body,
            sizing_mode="stretch_width",
        )

    def _direction_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "school_escorted_tours_by_escort_type_and_direction", "weighted"
        )
        if data is None:
            return ["Both"]
        return direction_options(data)

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

        total_escorted_tours = _nonempty(summaries["escorted_tour_totals"])

        direction_opts = direction_options(
            summaries["school_escorted_tours_by_escort_type_and_direction"]
        )
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = direction_opts[0]
        direction = self.direction_sel.value

        school_escort_data = self.get_filtered_view(
            "school_escorted_tours",
            direction,
            factory=lambda: escort_school_chart_data(
                summaries["school_escorted_tours_by_escort_type_and_direction"],
                direction,
            ),
        )

        total_kpi = data_table(
            total_escorted_tours,
            "Total Number of Escorted Tours",
        )

        school_escort_chart = bar_chart(
            school_escort_data,
            x_col="escort_type",
            y_col="tour_count",
            title=f"Escorted Tours To / From School - {direction}",
            xaxis_title="Escort Type",
            yaxis_title="School Tours",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        self._body.objects = [
            pn.Row(
                total_kpi,
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Direction:**"),
                        self.direction_sel,
                    ),
                    school_escort_chart,
                ),
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="escorted_tours",
    title="Escorted Tours",
    group_id="daily_travel",
    child_id="escorted_tours",
    order=29,
    controller_cls=EscortedToursPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="direction",
            widget_attr="direction_sel",
            label="Direction",
        ),
    ),
    required_summary_ids=(
        "escorted_tour_totals",
        "school_escorted_tours_by_escort_type_and_direction",
    ),
)

EscortedToursPage.definition = PAGE
