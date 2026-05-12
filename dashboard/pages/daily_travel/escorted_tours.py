"""Escorted tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, density_chart, kpi_box
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

DIRECTION_COL = "direction"
DISTANCE_BINS = [str(i) for i in range(40)] + ["40+"]


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
    options = ["Both"]
    if "outbound" in vals:
        options.append("Outbound")
    if "inbound" in vals:
        options.append("Inbound")
    return options


def _raw_direction(value: str) -> str:
    return {
        "Both": "all_directions",
        "Outbound": "outbound",
        "Inbound": "inbound",
    }.get(value, "all_directions")


def escort_school_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
        df = df.filter(pl.col(DIRECTION_COL) == direction)
        out.append((label, df))
    return out


def escort_stop_frequency_chart_data(
    data_list: list[tuple[str, pl.DataFrame]], direction: str
) -> list[tuple[str, pl.DataFrame]]:
    stop_col = {
        "Both": "total_stop_count",
        "Outbound": "outbound_stop_count",
        "Inbound": "inbound_stop_count",
    }[direction]
    out = []
    for label, df in _nonempty(data_list):
        df = df.group_by(stop_col).agg(tour_count=pl.col("tour_count").sum())
        df = (
            df.with_columns(pl.col(stop_col).cast(pl.Utf8).alias("stop_frequency"))
            .select("stop_frequency", "tour_count")
            .sort("stop_frequency")
        )
        out.append((label, df))
    return out


def escort_person_type_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
    *,
    person_type_labeler,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .with_columns(
                pl.col("person_type")
                .cast(pl.Utf8)
                .map_elements(person_type_labeler, return_dtype=pl.Utf8)
                .alias("person_type_label")
            )
            .select("person_type", "person_type_label", "tour_count")
            .sort("person_type")
        )
        out.append((label, filtered))
    return out


def _distance_sort_expr(column: str) -> pl.Expr:
    return (
        pl.when(pl.col(column).cast(pl.Utf8) == "40+")
        .then(999)
        .otherwise(pl.col(column).cast(pl.Int64, strict=False))
    )


def escort_distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
    *,
    y_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .select(
                pl.col("distance_bin").cast(pl.Utf8),
                pl.col(y_col).cast(pl.Float64).alias("freq"),
            )
            .with_columns(_distance_sort_expr("distance_bin").alias("_sort_distance"))
            .sort("_sort_distance")
            .drop("_sort_distance")
        )
        bins_df = pl.DataFrame({"distance_bin": DISTANCE_BINS}, schema={"distance_bin": pl.Utf8})
        filtered = (
            bins_df.join(filtered, on="distance_bin", how="left")
            .with_columns(pl.col("freq").fill_null(0.0))
            .select("distance_bin", "freq")
        )
        out.append((label, filtered))
    return out


def _escort_total_kpi_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for label, df in data_list:
        value = 0.0
        if df is not None and len(df) > 0 and "tour_count" in df.columns:
            value = float(df["tour_count"][0])
        out.append((label, value))
    return out


class EscortedToursPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        direction_opts = self._direction_options()
        self.direction_sel = self.selector(
            "direction",
            widget=pn.widgets.Select(
                name="Stop Direction",
                options=direction_opts,
                value=direction_opts[0],
            ),
            label="Stop Direction",
        )
        self._body = self.section(
            "escorted_tours_body",
            selectors=("direction",),
            render=self.render_body,
        )
        return self.new_section(
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

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        direction_opts = direction_options(
            summaries["school_escorted_tours_by_escort_type_and_direction"]
        )
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = direction_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]

        total_escorted_tours = _nonempty(summaries["escorted_tour_totals"])
        direction = self.direction_sel.value
        raw_direction = _raw_direction(direction)

        school_escort_data = self.get_filtered_view(
            "school_escorted_tours",
            raw_direction,
            factory=lambda: escort_school_chart_data(
                summaries["school_escorted_tours_by_escort_type_and_direction"],
                raw_direction,
            ),
        )
        escort_stop_data = self.get_filtered_view(
            "adult_escort_trip_stop_frequency",
            direction,
            factory=lambda: escort_stop_frequency_chart_data(
                summaries["adult_escort_trip_stop_frequency"],
                direction,
            ),
        )
        escort_person_type_data = self.get_filtered_view(
            "adult_escorted_tours_by_person_type_and_direction",
            raw_direction,
            factory=lambda: escort_person_type_chart_data(
                summaries["adult_escorted_tours_by_person_type_and_direction"],
                raw_direction,
                person_type_labeler=self.config.person_type_label,
            ),
        )
        escorted_tour_distance_data = self.get_filtered_view(
            "adult_escorted_tour_distance_distribution_by_direction",
            raw_direction,
            factory=lambda: escort_distance_chart_data(
                summaries["adult_escorted_tour_distance_distribution_by_direction"],
                raw_direction,
                y_col="tour_count",
            ),
        )
        escorted_trip_distance_data = self.get_filtered_view(
            "adult_escorted_trip_distance_distribution_by_direction",
            raw_direction,
            factory=lambda: escort_distance_chart_data(
                summaries["adult_escorted_trip_distance_distribution_by_direction"],
                raw_direction,
                y_col="trip_count",
            ),
        )

        total_kpi = kpi_box(
            "Total Escorted Tours",
            _escort_total_kpi_values(total_escorted_tours),
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
        escort_stop_chart = bar_chart(
            escort_stop_data,
            x_col="stop_frequency",
            y_col="tour_count",
            title=f"Adult Escort Trip Stop Frequency - {direction}",
            xaxis_title="Stop Count",
            yaxis_title="Adult Escort Trips",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        escort_person_type_chart = bar_chart(
            escort_person_type_data,
            x_col="person_type_label",
            y_col="tour_count",
            title=f"Adult Escorted Tours by Person Type - {direction}",
            xaxis_title="Person Type",
            yaxis_title="Adult Escort Tours",
            pct_col="pct",
            as_percent=self.as_percent,
        )
        escorted_tour_distance_chart = density_chart(
            escorted_tour_distance_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"Adult Escorted Tour Distance Distribution - {direction}",
            xaxis_title="Distance (miles)",
            yaxis_title="Adult Escort Tours",
            normalize=False,
            as_percent=self.as_percent,
            xaxis_categoryarray=DISTANCE_BINS,
            xaxis_tickvals=DISTANCE_BINS,
            xaxis_ticktext=DISTANCE_BINS,
        )
        escorted_trip_distance_chart = density_chart(
            escorted_trip_distance_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"Adult Escorted Trip Distance Distribution - {direction}",
            xaxis_title="Distance (miles)",
            yaxis_title="Adult Escort Trips",
            normalize=False,
            as_percent=self.as_percent,
            xaxis_categoryarray=DISTANCE_BINS,
            xaxis_tickvals=DISTANCE_BINS,
            xaxis_ticktext=DISTANCE_BINS,
        )

        return [
            total_kpi,
            pn.Column(
                pn.Row(
                    pn.pane.Markdown("**Stop Direction:**"),
                    self.direction_sel,
                ),
                pn.Row(
                    school_escort_chart,
                    escort_stop_chart,
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    escort_person_type_chart,
                    sizing_mode="stretch_width",
                ),
                escorted_tour_distance_chart,
                escorted_trip_distance_chart,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="escorted_tours",
    title="Escorted Tours",
    group_id="daily_travel",
    order=29,
    page_cls=EscortedToursPage,
    required_summary_ids=(
        "escorted_tour_totals",
        "school_escorted_tours_by_escort_type_and_direction",
        "adult_escort_trip_stop_frequency",
        "adult_escorted_tours_by_person_type_and_direction",
        "adult_escorted_tour_distance_distribution_by_direction",
        "adult_escorted_trip_distance_distribution_by_direction",
    ),
)

EscortedToursPage.definition = PAGE
