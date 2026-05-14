"""Trip mode page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import SelectorSpec, SingleSelectorSummaryPage
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_options, nonempty_runs
from dashboard.pages._shared.purposes import tour_purpose_mapping


def _tour_mode_labels(
    data_list: list[tuple[str, pl.DataFrame]],
    config,
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "tour_mode" not in first_df.columns:
        return []
    vals = (
        first_df.select("tour_mode")
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return config.ordered_values(
        "mode",
        [v for v in vals if v not in {"All", "all_tour_modes"}],
    )


def _filtered_trip_mode_data(
    data_list: list[tuple[str, pl.DataFrame]],
    tour_purpose: str,
    *,
    tour_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    ordered_trip_modes = column_options(
        data_list,
        "trip_mode",
        include_total=False,
    )
    base = pl.DataFrame({"trip_mode": ordered_trip_modes})
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty_runs(data_list):
        filtered = df.with_columns(
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_mode").cast(pl.Utf8),
            pl.col("trip_mode").cast(pl.Utf8),
        ).filter(pl.col("tour_purpose") == tour_purpose)
        if tour_mode is None:
            filtered = filtered.filter(pl.col("tour_mode") == "all_tour_modes")
        else:
            filtered = filtered.filter(pl.col("tour_mode") == tour_mode)
        filtered = base.join(
            filtered.select("trip_mode", "trip_count"),
            on="trip_mode",
            how="left",
        ).with_columns(pl.col("trip_count").fill_null(0.0))
        out.append((label, filtered))
    return out


class TripModePage(SingleSelectorSummaryPage):
    body_section_id = "trip_summary_mode_body"

    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        self._tour_purpose_to_raw = {"All": "all_tour_purposes"}
        return (
            SelectorSpec(
                selector_id="tour_purpose",
                label="Tour Purpose",
                attr_name="tour_purpose_sel",
                options_factory=lambda page: page._purpose_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Tour Purpose",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _purpose_options(self) -> list[str]:
        raw_values = self.state.get_summary_column_values(
            "trip_mode_by_tour_purpose_and_tour_mode",
            "tour_purpose",
            self.weighting_key,
        )
        options, self._tour_purpose_to_raw = tour_purpose_mapping(
            raw_values,
            total_display="All",
            config=self.config,
        )
        return options or ["All"]

    def render_ready(self, summaries: dict[str, object]):
        trip_mode_list = summaries["trip_mode_by_tour_purpose_and_tour_mode"]
        tour_purpose = self.tour_purpose_sel.value
        raw_purpose = self._tour_purpose_to_raw.get(str(tour_purpose), str(tour_purpose))
        mode_labels = _tour_mode_labels(trip_mode_list, self.config)

        overall_data = self.filtered_view(
            "trip_mode_overall",
            raw_purpose,
            factory=lambda: _filtered_trip_mode_data(
                trip_mode_list,
                raw_purpose,
            ),
        )

        grid_cards: list[pn.viewable.Viewable] = []
        for tour_mode in mode_labels:
            mode_data = self.filtered_view(
                "trip_mode_grid",
                (raw_purpose, tour_mode),
                factory=lambda tm=tour_mode: _filtered_trip_mode_data(
                    trip_mode_list,
                    raw_purpose,
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
                    xaxis_categoryarray=self.config.ordered_values(
                        "mode",
                        column_options(
                            mode_data,
                            "trip_mode",
                            include_total=False,
                        ),
                    ),
                )
            )

        grid_rows: list[pn.Row] = []
        for start in range(0, len(grid_cards), 2):
            grid_rows.append(
                pn.Row(*grid_cards[start : start + 2], sizing_mode="stretch_width")
            )

        return [
            bar_chart(
                overall_data,
                x_col="trip_mode",
                y_col="trip_count",
                title=f"Trip Mode Distribution - {tour_purpose}",
                xaxis_title="Trip Mode",
                yaxis_title="Trips",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=self.config.ordered_values(
                    "mode",
                    column_options(
                        overall_data,
                        "trip_mode",
                        include_total=False,
                    ),
                ),
            ),
            pn.pane.Markdown("### Trip Mode by Tour Mode"),
            *grid_rows,
        ]


PAGE = DashboardPageDefinition(
    page_id="trip_mode",
    title="Trip Mode",
    group_id="trip_summaries",
    order=48,
    page_cls=TripModePage,
    required_summary_ids=("trip_mode_by_tour_purpose_and_tour_mode",),
)

TripModePage.definition = PAGE
