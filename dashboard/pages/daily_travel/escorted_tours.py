"""Escorted tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, density_chart
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
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
CORE_SUMMARY_IDS = (
    "escorted_tour_totals",
    "school_escorted_tours_by_escort_type_and_direction",
    "adult_escort_event_stop_distribution",
    "adult_escorted_tours_by_person_type_and_direction",
    "adult_escorted_tour_distance_distribution_by_direction",
    "adult_escorted_trip_distance_distribution_by_direction",
)
OPTIONAL_SUMMARY_IDS = (
    "student_school_escort_status_by_direction",
    "student_households_by_student_count",
    "households_with_school_escorting_by_student_count_and_direction",
    "schoolkids_per_escorted_tour_by_student_count_and_direction",
)
PAGE_SUMMARY_IDS = (*CORE_SUMMARY_IDS, *OPTIONAL_SUMMARY_IDS)
STOP_SEGMENT_LABELS = {
    "outbound_before_dropoff": "Adult Escort Stops Before Dropoff - Outbound",
    "outbound_after_dropoff": "Adult Escort Stops After Dropoff - Outbound",
    "inbound_before_pickup": "Adult Escort Stops Before Pickup - Inbound",
    "inbound_after_pickup": "Adult Escort Stops After Pickup - Inbound",
}


def direction_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    directions = ordered_category_values(data_list, DIRECTION_COL)
    if not directions:
        return ["Both Directions"]
    options = ["Both Directions"]
    if "outbound" in directions:
        options.append("Outbound")
    if "inbound" in directions:
        options.append("Inbound")
    return options


def _adult_raw_direction(value: str) -> str:
    return {
        "Both Directions": "both",
        "Outbound": "outbound",
        "Inbound": "inbound",
    }.get(value, "both")


def _default_direction_option(options: list[str]) -> str:
    if "Outbound" in options:
        return "Outbound"
    return options[0] if options else "Both Directions"


def adult_escort_event_stop_chart_data(
    data_list: list[tuple[str, pl.DataFrame]], segment: str
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in nonempty(data_list):
        df = (
            df.with_columns(pl.col("segment").cast(pl.Utf8))
            .filter(pl.col("segment") == segment)
            .group_by("stop_count")
            .agg(tour_count=pl.col("tour_count").sum())
            .with_columns(pl.col("stop_count").cast(pl.Utf8))
            .select("stop_count", "tour_count")
            .sort(pl.col("stop_count").cast(pl.Int64, strict=False))
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
        bins_df = pl.DataFrame(
            {"distance_bin": DISTANCE_BINS}, schema={"distance_bin": pl.Utf8}
        )
        filtered = (
            bins_df.join(filtered, on="distance_bin", how="left")
            .with_columns(pl.col("freq").fill_null(0.0))
            .select("distance_bin", "freq")
        )
        out.append((label, filtered))
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


def schoolkids_per_escorted_tour_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .select(
                pl.col("student_count").cast(pl.Int64),
                pl.col("avg_schoolkids_per_tour").cast(pl.Float64),
                pl.col("tour_count").cast(pl.Float64),
            )
        )
        out.append((label, filtered))
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


def _stop_count_category_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    values: set[int] = set()
    for _, df in nonempty(data_list):
        if "stop_count" not in df.columns:
            continue
        values.update(
            value
            for value in df.select(pl.col("stop_count").cast(pl.Int64))
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
                name="Direction",
                options=direction_opts,
                value=_default_direction_option(direction_opts),
            ),
            label="Direction",
        )
        self._static_body = self.section(
            "escorted_tours_static_body",
            render=self.render_static_body,
        )
        self._directional_body = self.section(
            "escorted_tours_directional_body",
            selectors=("direction",),
            render=self.render_directional_body,
        )
        self._body = self.new_section(
            self._static_body,
            self._directional_body,
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
            return ["Both Directions"]
        return direction_options(data)

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*CORE_SUMMARY_IDS)
        if summaries is None:
            return
        direction_opts = direction_options(
            summaries["school_escorted_tours_by_escort_type_and_direction"]
        )
        self.direction_sel.options = direction_opts
        if self.direction_sel.value not in direction_opts:
            self.direction_sel.value = _default_direction_option(direction_opts)

    def _load_page_summaries(self):
        summaries = self.require_summaries(*CORE_SUMMARY_IDS)
        if summaries is None:
            return None
        optional_summaries: dict[str, list[tuple[str, pl.DataFrame]] | None] = {
            "student_school_escort_status_by_direction": self.optional_summary(
                "student_school_escort_status_by_direction"
            ),
            "student_households_by_student_count": self.optional_summary(
                "student_households_by_student_count"
            ),
            "households_with_school_escorting_by_student_count_and_direction": self.optional_summary(
                "households_with_school_escorting_by_student_count_and_direction"
            ),
            "schoolkids_per_escorted_tour_by_student_count_and_direction": self.optional_summary(
                "schoolkids_per_escorted_tour_by_student_count_and_direction"
            ),
        }
        return {**summaries, **optional_summaries}

    def render_static_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        summaries = self._load_page_summaries()
        if summaries is None:
            return [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(CORE_SUMMARY_IDS),
                )
            ]
        stop_frequency_values = _stop_count_category_values(
            summaries["adult_escort_event_stop_distribution"]
        )
        household_student_count_values = _student_count_category_values(
            summaries["student_households_by_student_count"] or []
        )

        escort_stop_data_by_segment = {
            segment: self.get_filtered_view(
                "adult_escort_event_stop_distribution",
                segment,
                factory=lambda segment=segment: complete_category_counts(
                    adult_escort_event_stop_chart_data(
                        summaries["adult_escort_event_stop_distribution"],
                        segment,
                    ),
                    category_col="stop_count",
                    category_values=stop_frequency_values,
                    value_cols=("tour_count",),
                ),
            )
            for segment in STOP_SEGMENT_LABELS
        }
        student_school_escort_outbound = None
        student_school_escort_inbound = None
        student_school_escort_both = None
        if summaries["student_school_escort_status_by_direction"] is not None:
            student_school_escort_outbound = self.get_filtered_view(
                "student_school_escort_status",
                "outbound",
                factory=lambda: complete_category_counts(
                    student_school_escort_chart_data(
                        summaries["student_school_escort_status_by_direction"],
                        "outbound",
                    ),
                    category_col="escort_type",
                    category_values=self.config.ordered_values(
                        "escort", STUDENT_ESCORT_TYPE_ORDER
                    ),
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
                    category_values=self.config.ordered_values(
                        "escort", STUDENT_ESCORT_TYPE_ORDER
                    ),
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
                    category_values=self.config.ordered_values(
                        "escort", STUDENT_ESCORT_TYPE_ORDER
                    ),
                    value_cols=("tour_count", "pct"),
                ),
            )

        household_school_escort_outbound = None
        household_school_escort_inbound = None
        household_school_escort_both = None
        if (
            summaries["student_households_by_student_count"] is not None
            and summaries[
                "households_with_school_escorting_by_student_count_and_direction"
            ]
            is not None
        ):
            household_school_escort_outbound = self.get_filtered_view(
                "household_school_escort_status",
                "outbound",
                factory=lambda: complete_category_counts(
                    [
                        (
                            label,
                            df.with_columns(
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
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
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
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
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
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

        schoolkids_per_escorted_tour_outbound = None
        schoolkids_per_escorted_tour_inbound = None
        schoolkids_per_escorted_tour_both = None
        if (
            summaries["schoolkids_per_escorted_tour_by_student_count_and_direction"]
            is not None
        ):
            schoolkids_per_escorted_tour_outbound = self.get_filtered_view(
                "schoolkids_per_escorted_tour",
                "outbound",
                factory=lambda: complete_category_counts(
                    [
                        (
                            label,
                            df.with_columns(
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
                            ),
                        )
                        for label, df in schoolkids_per_escorted_tour_chart_data(
                            summaries[
                                "schoolkids_per_escorted_tour_by_student_count_and_direction"
                            ],
                            "outbound",
                        )
                    ],
                    category_col="student_count",
                    category_values=household_student_count_values,
                    value_cols=("avg_schoolkids_per_tour", "tour_count"),
                ),
            )
            schoolkids_per_escorted_tour_inbound = self.get_filtered_view(
                "schoolkids_per_escorted_tour",
                "inbound",
                factory=lambda: complete_category_counts(
                    [
                        (
                            label,
                            df.with_columns(
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
                            ),
                        )
                        for label, df in schoolkids_per_escorted_tour_chart_data(
                            summaries[
                                "schoolkids_per_escorted_tour_by_student_count_and_direction"
                            ],
                            "inbound",
                        )
                    ],
                    category_col="student_count",
                    category_values=household_student_count_values,
                    value_cols=("avg_schoolkids_per_tour", "tour_count"),
                ),
            )
            schoolkids_per_escorted_tour_both = self.get_filtered_view(
                "schoolkids_per_escorted_tour",
                "both",
                factory=lambda: complete_category_counts(
                    [
                        (
                            label,
                            df.with_columns(
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
                            ),
                        )
                        for label, df in schoolkids_per_escorted_tour_chart_data(
                            summaries[
                                "schoolkids_per_escorted_tour_by_student_count_and_direction"
                            ],
                            "both",
                        )
                    ],
                    category_col="student_count",
                    category_values=household_student_count_values,
                    value_cols=("avg_schoolkids_per_tour", "tour_count"),
                ),
            )

        escort_stop_charts = [
            bar_chart(
                escort_stop_data_by_segment[segment],
                x_col="stop_count",
                y_col="tour_count",
                title=title,
                xaxis_title="Stop Count",
                yaxis_title="Chauffer Escorting Tour-Legs",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=stop_frequency_values,
            )
            for segment, title in STOP_SEGMENT_LABELS.items()
        ]
        student_school_escort_outbound_chart = None
        student_school_escort_inbound_chart = None
        student_school_escort_both_chart = None
        if student_school_escort_outbound is not None:
            escort_label_order = self.config.ordered_labels(
                "escort", STUDENT_ESCORT_TYPE_ORDER
            )
            student_school_escort_outbound_chart = bar_chart(
                label_category_data(
                    student_school_escort_outbound,
                    source_col="escort_type",
                    category_id="escort",
                    config=self.config,
                    target_col="escort_type_label",
                ),
                x_col="escort_type_label",
                y_col="tour_count",
                title="Student School Escort Status - Outbound",
                xaxis_title="Escort Type",
                yaxis_title="Student School Tours",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=escort_label_order,
            )
            student_school_escort_inbound_chart = bar_chart(
                label_category_data(
                    student_school_escort_inbound,
                    source_col="escort_type",
                    category_id="escort",
                    config=self.config,
                    target_col="escort_type_label",
                ),
                x_col="escort_type_label",
                y_col="tour_count",
                title="Student School Escort Status - Inbound",
                xaxis_title="Escort Type",
                yaxis_title="Student School Tours",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=escort_label_order,
            )
            student_school_escort_both_chart = bar_chart(
                label_category_data(
                    student_school_escort_both,
                    source_col="escort_type",
                    category_id="escort",
                    config=self.config,
                    target_col="escort_type_label",
                ),
                x_col="escort_type_label",
                y_col="tour_count",
                title="Student School Escort Status - Both Directions",
                xaxis_title="Escort Type",
                yaxis_title="Student School Tours",
                pct_col="pct",
                as_percent=self.as_percent,
                xaxis_categoryarray=escort_label_order,
            )

        household_school_escort_outbound_chart = None
        household_school_escort_inbound_chart = None
        household_school_escort_both_chart = None
        if household_school_escort_outbound is not None:
            household_school_escort_outbound_chart = bar_chart(
                household_school_escort_outbound,
                x_col="student_count",
                y_col="pct" if self.as_percent else "household_count",
                title="Households With School Escorting - Outbound",
                xaxis_title="Students in Household",
                yaxis_title=(
                    "Percent of Households with Students (%)"
                    if self.as_percent
                    else "Number of Households with Students"
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
                    "Percent of Households with Students (%)"
                    if self.as_percent
                    else "Number of Households with Students"
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
                    "Percent of Households with Students (%)"
                    if self.as_percent
                    else "Number of Households with Students"
                ),
                as_percent=False,
                xaxis_categoryarray=household_student_count_values,
            )

        schoolkids_per_escorted_tour_outbound_chart = None
        schoolkids_per_escorted_tour_inbound_chart = None
        schoolkids_per_escorted_tour_both_chart = None
        if schoolkids_per_escorted_tour_outbound is not None:
            schoolkids_per_escorted_tour_outbound_chart = bar_chart(
                schoolkids_per_escorted_tour_outbound,
                x_col="student_count",
                y_col="avg_schoolkids_per_tour",
                title="Schoolkids Per Escorted Tour - Outbound",
                xaxis_title="Students in Household",
                yaxis_title="Average Schoolkids per Escorted Tour",
                as_percent=False,
                xaxis_categoryarray=household_student_count_values,
            )
            schoolkids_per_escorted_tour_inbound_chart = bar_chart(
                schoolkids_per_escorted_tour_inbound,
                x_col="student_count",
                y_col="avg_schoolkids_per_tour",
                title="Schoolkids Per Escorted Tour - Inbound",
                xaxis_title="Students in Household",
                yaxis_title="Average Schoolkids per Escorted Tour",
                as_percent=False,
                xaxis_categoryarray=household_student_count_values,
            )
            schoolkids_per_escorted_tour_both_chart = bar_chart(
                schoolkids_per_escorted_tour_both,
                x_col="student_count",
                y_col="avg_schoolkids_per_tour",
                title="Schoolkids Per Escorted Tour - Both Directions",
                xaxis_title="Students in Household",
                yaxis_title="Average Schoolkids per Escorted Tour",
                as_percent=False,
                xaxis_categoryarray=household_student_count_values,
            )

        body_objects: list[pn.viewable.Viewable] = []
        if student_school_escort_outbound_chart is not None:
            body_objects.extend(
                [
                    pn.pane.Markdown("### Student School Tour Escort Status"),
                    pn.pane.Markdown(
                        "Student school tours by escort type. `Both Directions` means the same child school tour is escorted outbound and inbound."
                    ),
                    pn.Row(
                        student_school_escort_outbound_chart,
                        student_school_escort_inbound_chart,
                        student_school_escort_both_chart,
                        sizing_mode="stretch_width",
                    ),
                ]
            )
        else:
            body_objects.extend(
                [
                    pn.pane.Markdown("### Student School Tour Escort Status"),
                    pn.pane.Markdown(
                        "Student school tours by escort type. `Both Directions` means the same child school tour is escorted outbound and inbound."
                    ),
                    self.data_not_available_card(
                        detail="This section only renders when the student school escort summary is available.",
                        missing_items=["student_school_escort_status_by_direction"],
                    ),
                ]
            )
        if household_school_escort_outbound_chart is not None:
            body_objects.extend(
                [
                    pn.pane.Markdown("### Households With School Escorting"),
                    pn.pane.Markdown(
                        "Households with school escorting by number of students per household. A household counts if it has at least one escorted school tour in the selected direction."
                    ),
                    pn.Row(
                        household_school_escort_outbound_chart,
                        household_school_escort_inbound_chart,
                        household_school_escort_both_chart,
                        sizing_mode="stretch_width",
                    ),
                ]
            )
        else:
            body_objects.extend(
                [
                    pn.pane.Markdown("### Households With School Escorting"),
                    pn.pane.Markdown(
                        "Households with school escorting  number of students per household. A household counts if it has at least one escorted school tour in the selected direction."
                    ),
                    self.data_not_available_card(
                        detail="This section only renders when the household school escort summaries are available.",
                        missing_items=[
                            "student_households_by_student_count",
                            "households_with_school_escorting_by_student_count_and_direction",
                        ],
                    ),
                ]
            )
        if schoolkids_per_escorted_tour_outbound_chart is not None:
            body_objects.extend(
                [
                    pn.pane.Markdown("### Schoolkids Per Escorted Tour"),
                    pn.pane.Markdown(
                        "Average `num_escortees` on adult escort tours, grouped by number of students in the household. `Both Directions` only counts adult tour rows flagged in both directions."
                    ),
                    pn.Row(
                        schoolkids_per_escorted_tour_outbound_chart,
                        schoolkids_per_escorted_tour_inbound_chart,
                        schoolkids_per_escorted_tour_both_chart,
                        sizing_mode="stretch_width",
                    ),
                ]
            )
        else:
            body_objects.extend(
                [
                    pn.pane.Markdown("### Schoolkids Per Escorted Tour"),
                    pn.pane.Markdown(
                        "Average `num_escortees` on adult escort tours, grouped by number of students in the household. `Both Directions` only counts adult/chauffer tours where escorting occurred in both directions."
                    ),
                    self.data_not_available_card(
                        detail="This section only renders when the schoolkids-per-escorted-tour summary is available.",
                        missing_items=[
                            "schoolkids_per_escorted_tour_by_student_count_and_direction"
                        ],
                    ),
                ]
            )

        body_objects.extend(
            [
                pn.pane.Markdown("### Chauffer Escorting Stop Distribution"),
                pn.pane.Markdown(
                    "Number of stops before and after each adult chauffeur trips. Matched `escort_participants` to child school and home trips to determine the stop count."
                ),
                pn.Row(
                    *escort_stop_charts[:2],
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    *escort_stop_charts[2:],
                    sizing_mode="stretch_width",
                ),
            ]
        )

        return [pn.Column(*body_objects)]

    def render_directional_body(self):
        if not self.state.run_labels:
            return []

        summaries = self._load_page_summaries()
        if summaries is None:
            return []

        direction = self.direction_sel.value
        adult_raw_direction = _adult_raw_direction(direction)
        person_type_values = ordered_category_values(
            summaries["adult_escorted_tours_by_person_type_and_direction"],
            "person_type",
            category_id="person_type",
            config=self.config,
        )
        escort_person_type_data = self.get_filtered_view(
            "adult_escorted_tours_by_person_type_and_direction",
            adult_raw_direction,
            factory=lambda: complete_category_counts(
                escort_person_type_chart_data(
                    summaries["adult_escorted_tours_by_person_type_and_direction"],
                    adult_raw_direction,
                    person_type_labeler=self.config.person_type_label,
                ),
                category_col="person_type",
                category_values=person_type_values,
                value_cols=("tour_count",),
            ),
        )
        escorted_tour_distance_data = self.get_filtered_view(
            "adult_escorted_tour_distance_distribution_by_direction",
            adult_raw_direction,
            factory=lambda: escort_distance_chart_data(
                summaries["adult_escorted_tour_distance_distribution_by_direction"],
                adult_raw_direction,
                y_col="tour_count",
            ),
        )
        escorted_trip_distance_data = self.get_filtered_view(
            "adult_escorted_trip_distance_distribution_by_direction",
            adult_raw_direction,
            factory=lambda: escort_distance_chart_data(
                summaries["adult_escorted_trip_distance_distribution_by_direction"],
                adult_raw_direction,
                y_col="trip_count",
            ),
        )

        escort_person_type_chart = bar_chart(
            label_category_data(
                escort_person_type_data,
                source_col="person_type",
                category_id="person_type",
                config=self.config,
                target_col="person_type_label",
            ),
            x_col="person_type_label",
            y_col="tour_count",
            title=f"Chauffer Escorting Tours by Person Type - {direction}",
            xaxis_title="Person Type",
            yaxis_title="Chauffer Escorting Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=self.config.ordered_labels(
                "person_type", person_type_values
            ),
        )
        escorted_tour_distance_chart = density_chart(
            escorted_tour_distance_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"Chauffer Escorting Tour Distance Distribution - {direction}",
            xaxis_title="Distance (miles)",
            yaxis_title="Chauffer Escorting Tours",
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
            title=f"Chauffer Escorting Trip Distance Distribution - {direction}",
            xaxis_title="Distance (miles)",
            yaxis_title="Chauffer Escorting Trips",
            normalize=False,
            as_percent=self.as_percent,
            xaxis_categoryarray=DISTANCE_BINS,
            xaxis_tickvals=DISTANCE_BINS,
            xaxis_ticktext=DISTANCE_BINS,
        )

        return [
            pn.Column(
                pn.Row(
                    pn.pane.Markdown("**Direction:**"),
                    self.direction_sel,
                ),
                pn.pane.Markdown("### Chauffer Escorting Person Type Distribution"),
                pn.pane.Markdown(
                    "Adult chauffeur escort tours by person type. `Both Directions` means the chauffer escorted in both outbound and inbound directions."
                ),
                pn.Row(
                    escort_person_type_chart,
                    sizing_mode="stretch_width",
                ),
                pn.pane.Markdown(
                    "### Chauffer Escorting Tour and Trip Distance Distributions"
                ),
                pn.pane.Markdown(
                    "Distance distributions for adult chauffeur escort tours and trips. `Both Directions` means the chauffer escorted in both outbound and inbound directions."
                ),
                escorted_tour_distance_chart,
                escorted_trip_distance_chart,
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="escorted_tours",
    title="Escorted Tours",
    group_id="daily_travel",
    order=29,
    page_cls=EscortedToursPage,
    required_summary_ids=(*PAGE_SUMMARY_IDS,),
)

EscortedToursPage.definition = PAGE
