"""Escorted tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, density_chart, kpi_box
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    nonempty,
    ordered_category_values,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

DIRECTION_COL = "direction"
DISTANCE_BINS = [str(i) for i in range(40)] + ["40+"]
STUDENT_ESCORT_TYPE_ORDER = [
    "not_escorted",
    "pure_escort",
    "ride_share",
]
STUDENT_ESCORT_TYPE_LABELS = {
    "not_escorted": "Not Escorted",
    "pure_escort": "Pure Escort",
    "ride_share": "Rideshare Escort",
}


def direction_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    directions = ordered_category_values(data_list, DIRECTION_COL)
    if not directions:
        return ["Both"]
    options = ["Both"]
    if "outbound" in directions:
        options.append("Outbound")
    if "inbound" in directions:
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
    for label, df in nonempty(data_list):
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
    for label, df in nonempty(data_list):
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
    for label, df in nonempty(data_list):
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .with_columns(pl.col("person_type").cast(pl.Utf8))
            .select("person_type", "tour_count")
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
    for label, df in nonempty(data_list):
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


def student_school_escort_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .select("escort_type", "tour_count")
        )
        out.append((label, filtered))
    return out


def household_school_escort_chart_data(
    numerator_data_list: list[tuple[str, pl.DataFrame]],
    denominator_data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    denominator_by_label = {
        label: df.select(
            pl.col("student_count").cast(pl.Int64),
            pl.col("household_count").cast(pl.Float64).alias("total_household_count"),
        )
        for label, df in nonempty(denominator_data_list)
    }
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in numerator_data_list:
        denominator = denominator_by_label.get(label)
        if denominator is None or denominator.is_empty():
            continue
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .select(
                pl.col("student_count").cast(pl.Int64),
                pl.col("household_count").cast(pl.Float64),
            )
        )
        out.append(
            (
                label,
                denominator.join(filtered, on="student_count", how="left")
                .with_columns(
                    pl.col("household_count").fill_null(0.0),
                    pl.when(pl.col("total_household_count") > 0)
                    .then(
                        pl.col("household_count")
                        / pl.col("total_household_count")
                        * 100.0
                    )
                    .otherwise(0.0)
                    .alias("pct"),
                )
                .select("student_count", "household_count", "pct"),
            )
        )
    return out


def _student_count_category_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    values: set[int] = set()
    for _, df in nonempty(data_list):
        if "student_count" not in df.columns:
            continue
        values.update(
            value
            for value in df.select(pl.col("student_count").cast(pl.Int64))
            .to_series()
            .to_list()
            if value is not None
        )
    return [str(value) for value in sorted(values)]


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

        total_escorted_tours = nonempty(summaries["escorted_tour_totals"])
        direction = self.direction_sel.value
        raw_direction = _raw_direction(direction)
        escort_type_values = ordered_category_values(
            summaries["school_escorted_tours_by_escort_type_and_direction"],
            "escort_type",
        )
        stop_frequency_values = ordered_category_values(
            escort_stop_frequency_chart_data(
                summaries["adult_escort_trip_stop_frequency"],
                direction,
            ),
            "stop_frequency",
        )
        person_type_values = ordered_category_values(
            summaries["adult_escorted_tours_by_person_type_and_direction"],
            "person_type",
            category_id="person_type",
            config=self.config,
        )
        household_student_count_values = _student_count_category_values(
            summaries["student_households_by_student_count"]
        )

        school_escort_data = self.get_filtered_view(
            "school_escorted_tours",
            raw_direction,
            factory=lambda: complete_category_counts(
                escort_school_chart_data(
                    summaries["school_escorted_tours_by_escort_type_and_direction"],
                    raw_direction,
                ),
                category_col="escort_type",
                category_values=escort_type_values,
                value_cols=("tour_count", "pct"),
            ),
        )
        escort_stop_data = self.get_filtered_view(
            "adult_escort_trip_stop_frequency",
            direction,
            factory=lambda: complete_category_counts(
                escort_stop_frequency_chart_data(
                    summaries["adult_escort_trip_stop_frequency"],
                    direction,
                ),
                category_col="stop_frequency",
                category_values=stop_frequency_values,
                value_cols=("tour_count",),
            ),
        )
        escort_person_type_data = self.get_filtered_view(
            "adult_escorted_tours_by_person_type_and_direction",
            raw_direction,
            factory=lambda: complete_category_counts(
                escort_person_type_chart_data(
                    summaries["adult_escorted_tours_by_person_type_and_direction"],
                    raw_direction,
                    person_type_labeler=self.config.person_type_label,
                ),
                category_col="person_type",
                category_values=person_type_values,
                value_cols=("tour_count",),
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
        student_school_escort_outbound = self.get_filtered_view(
            "student_school_escort_status",
            "outbound",
            factory=lambda: complete_category_counts(
                student_school_escort_chart_data(
                    summaries["student_school_escort_status_by_direction"],
                    "outbound",
                ),
                category_col="escort_type",
                category_values=STUDENT_ESCORT_TYPE_ORDER,
                value_cols=("tour_count", "pct"),
            ),
        )
        student_school_escort_inbound = self.get_filtered_view(
            "student_school_escort_status",
            "inbound",
            factory=lambda: complete_category_counts(
                student_school_escort_chart_data(
                    summaries["student_school_escort_status_by_direction"],
                    "inbound",
                ),
                category_col="escort_type",
                category_values=STUDENT_ESCORT_TYPE_ORDER,
                value_cols=("tour_count", "pct"),
            ),
        )
        student_school_escort_both = self.get_filtered_view(
            "student_school_escort_status",
            "both",
            factory=lambda: complete_category_counts(
                student_school_escort_chart_data(
                    summaries["student_school_escort_status_by_direction"],
                    "both",
                ),
                category_col="escort_type",
                category_values=STUDENT_ESCORT_TYPE_ORDER,
                value_cols=("tour_count", "pct"),
            ),
        )
        household_school_escort_outbound = self.get_filtered_view(
            "household_school_escort_status",
            "outbound",
            factory=lambda: complete_category_counts(
                [
                    (
                        label,
                        df.with_columns(
                            pl.col("student_count").cast(pl.Utf8).alias("student_count")
                        ),
                    )
                    for label, df in household_school_escort_chart_data(
                        summaries[
                            "households_with_school_escorting_by_student_count_and_direction"
                        ],
                        summaries["student_households_by_student_count"],
                        "outbound",
                    )
                ],
                category_col="student_count",
                category_values=household_student_count_values,
                value_cols=("household_count", "pct"),
            ),
        )
        household_school_escort_inbound = self.get_filtered_view(
            "household_school_escort_status",
            "inbound",
            factory=lambda: complete_category_counts(
                [
                    (
                        label,
                        df.with_columns(
                            pl.col("student_count").cast(pl.Utf8).alias("student_count")
                        ),
                    )
                    for label, df in household_school_escort_chart_data(
                        summaries[
                            "households_with_school_escorting_by_student_count_and_direction"
                        ],
                        summaries["student_households_by_student_count"],
                        "inbound",
                    )
                ],
                category_col="student_count",
                category_values=household_student_count_values,
                value_cols=("household_count", "pct"),
            ),
        )
        household_school_escort_both = self.get_filtered_view(
            "household_school_escort_status",
            "both",
            factory=lambda: complete_category_counts(
                [
                    (
                        label,
                        df.with_columns(
                            pl.col("student_count").cast(pl.Utf8).alias("student_count")
                        ),
                    )
                    for label, df in household_school_escort_chart_data(
                        summaries[
                            "households_with_school_escorting_by_student_count_and_direction"
                        ],
                        summaries["student_households_by_student_count"],
                        "both",
                    )
                ],
                category_col="student_count",
                category_values=household_student_count_values,
                value_cols=("household_count", "pct"),
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
            xaxis_categoryarray=escort_type_values,
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
            xaxis_categoryarray=stop_frequency_values,
        )
        escort_person_type_chart = bar_chart(
            [
                (
                    label,
                    df.with_columns(
                        pl.col("person_type")
                        .cast(pl.Utf8)
                        .map_elements(self.config.person_type_label, return_dtype=pl.Utf8)
                        .alias("person_type_label")
                    ),
                )
                for label, df in escort_person_type_data
            ],
            x_col="person_type_label",
            y_col="tour_count",
            title=f"Adult Escorted Tours by Person Type - {direction}",
            xaxis_title="Person Type",
            yaxis_title="Adult Escort Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=self.config.ordered_labels("person_type", person_type_values),
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
        student_school_escort_outbound_chart = bar_chart(
            [
                (
                    label,
                    df.with_columns(
                        pl.col("escort_type")
                        .cast(pl.Utf8)
                        .replace_strict(
                            STUDENT_ESCORT_TYPE_LABELS,
                            default=pl.col("escort_type"),
                        )
                        .alias("escort_type_label")
                    ),
                )
                for label, df in student_school_escort_outbound
            ],
            x_col="escort_type_label",
            y_col="tour_count",
            title="Student School Escort Status - Outbound",
            xaxis_title="Escort Type",
            yaxis_title="Student School Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=[
                STUDENT_ESCORT_TYPE_LABELS[value]
                for value in STUDENT_ESCORT_TYPE_ORDER
            ],
        )
        student_school_escort_inbound_chart = bar_chart(
            [
                (
                    label,
                    df.with_columns(
                        pl.col("escort_type")
                        .cast(pl.Utf8)
                        .replace_strict(
                            STUDENT_ESCORT_TYPE_LABELS,
                            default=pl.col("escort_type"),
                        )
                        .alias("escort_type_label")
                    ),
                )
                for label, df in student_school_escort_inbound
            ],
            x_col="escort_type_label",
            y_col="tour_count",
            title="Student School Escort Status - Inbound",
            xaxis_title="Escort Type",
            yaxis_title="Student School Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=[
                STUDENT_ESCORT_TYPE_LABELS[value]
                for value in STUDENT_ESCORT_TYPE_ORDER
            ],
        )
        student_school_escort_both_chart = bar_chart(
            [
                (
                    label,
                    df.with_columns(
                        pl.col("escort_type")
                        .cast(pl.Utf8)
                        .replace_strict(
                            STUDENT_ESCORT_TYPE_LABELS,
                            default=pl.col("escort_type"),
                        )
                        .alias("escort_type_label")
                    ),
                )
                for label, df in student_school_escort_both
            ],
            x_col="escort_type_label",
            y_col="tour_count",
            title="Student School Escort Status - Both Directions",
            xaxis_title="Escort Type",
            yaxis_title="Student School Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=[
                STUDENT_ESCORT_TYPE_LABELS[value]
                for value in STUDENT_ESCORT_TYPE_ORDER
            ],
        )
        household_school_escort_outbound_chart = bar_chart(
            household_school_escort_outbound,
            x_col="student_count",
            y_col="pct" if self.as_percent else "household_count",
            title="Households With School Escorting - Outbound",
            xaxis_title="Students in Household",
            yaxis_title=(
                "Student Households With School Escorting (%)"
                if self.as_percent
                else "Student Households With School Escorting"
            ),
            as_percent=False,
            xaxis_categoryarray=household_student_count_values,
        )
        household_school_escort_inbound_chart = bar_chart(
            household_school_escort_inbound,
            x_col="student_count",
            y_col="pct" if self.as_percent else "household_count",
            title="Households With School Escorting - Inbound",
            xaxis_title="Students in Household",
            yaxis_title=(
                "Student Households With School Escorting (%)"
                if self.as_percent
                else "Student Households With School Escorting"
            ),
            as_percent=False,
            xaxis_categoryarray=household_student_count_values,
        )
        household_school_escort_both_chart = bar_chart(
            household_school_escort_both,
            x_col="student_count",
            y_col="pct" if self.as_percent else "household_count",
            title="Households With School Escorting - Both Directions",
            xaxis_title="Students in Household",
            yaxis_title=(
                "Student Households With School Escorting (%)"
                if self.as_percent
                else "Student Households With School Escorting"
            ),
            as_percent=False,
            xaxis_categoryarray=household_student_count_values,
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
                pn.pane.Markdown("### Student School Escort Status"),
                pn.Row(
                    student_school_escort_outbound_chart,
                    student_school_escort_inbound_chart,
                    student_school_escort_both_chart,
                    sizing_mode="stretch_width",
                ),
                pn.pane.Markdown("### Households With School Escorting"),
                pn.Row(
                    household_school_escort_outbound_chart,
                    household_school_escort_inbound_chart,
                    household_school_escort_both_chart,
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
        "student_school_escort_status_by_direction",
        "student_households_by_student_count",
        "households_with_school_escorting_by_student_count_and_direction",
        "adult_escorted_tour_distance_distribution_by_direction",
        "adult_escorted_trip_distance_distribution_by_direction",
    ),
)

EscortedToursPage.definition = PAGE
