"""Escorted tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, density_chart, selector_row
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
    nonempty,
    ordered_category_values,
)
from dashboard.helpers.time_distance_helpers import distance_sort_expr
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
STUDENT_ESCORT_DESCRIPTION = (
    "Student school tours by escort type. `Both Directions` means the same child "
    "school tour is escorted in both outbound and inbound directions."
)
HOUSEHOLD_ESCORT_DESCRIPTION = (
    "Households with school escorting by number of students per household. "
    "A household counts if it has at least one escorted school tour in the "
    "selected direction."
)
SCHOOLKIDS_DESCRIPTION = (
    "Average number of escortees on adult chauffer tours, grouped by number of students "
    "in the household. `Both Directions` only counts chauffer tours where "
    "escorting occurred in both directions."
)
STOP_DISTRIBUTION_DESCRIPTION = (
    "Number of stops before and after the dropoff/pickup on each adult chauffeur trip. "
)
PERSON_TYPE_DESCRIPTION = (
    "Adult chauffeur tours by person type. `Both Directions` means the "
    "chauffer escorted in both outbound and inbound directions."
)
DISTANCE_DESCRIPTION = (
    "Distance distributions for adult chauffeur tours and trips. "
    "`Both Directions` means the chauffer escorted in both outbound and inbound "
    "directions."
)


def direction_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Return the dashboard's display directions in stable order."""
    directions = ordered_category_values(data_list, DIRECTION_COL)
    if not directions:
        return ["Both Directions"]
    options = ["Both Directions"]
    if "outbound" in directions:
        options.append("Outbound")
    if "inbound" in directions:
        options.append("Inbound")
    return options


def adult_raw_direction(value: str) -> str:
    """Translate the selector label into the raw summary value."""
    return {
        "Both Directions": "both",
        "Outbound": "outbound",
        "Inbound": "inbound",
    }.get(value, "both")


def default_direction_option(options: list[str]) -> str:
    """Prefer outbound when available because it is usually the first interesting view."""
    if "Outbound" in options:
        return "Outbound"
    return options[0] if options else "Both Directions"


def adult_escort_event_stop_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    segment: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one stop-count distribution for a specific chauffeur segment."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = (
            df.with_columns(pl.col("segment").cast(pl.Utf8))
            .filter(pl.col("segment") == segment)
            .group_by("stop_count")
            .agg(tour_count=pl.col("tour_count").sum())
            .with_columns(pl.col("stop_count").cast(pl.Utf8))
            .select("stop_count", "tour_count")
            .sort(pl.col("stop_count").cast(pl.Int64, strict=False))
        )
        out.append((label, filtered))
    return out


def escort_person_type_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build the person-type distribution for one adult escort direction."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        out.append(
            (
                label,
                df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
                .filter(pl.col(DIRECTION_COL) == direction)
                .with_columns(pl.col("person_type").cast(pl.Utf8))
                .select("person_type", "tour_count"),
            )
        )
    return out


def escort_distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
    *,
    y_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one complete distance distribution for escort tours or trips."""
    out: list[tuple[str, pl.DataFrame]] = []
    bins_df = pl.DataFrame(
        {"distance_bin": DISTANCE_BINS}, schema={"distance_bin": pl.Utf8}
    )
    for label, df in nonempty(data_list):
        filtered = (
            df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
            .filter(pl.col(DIRECTION_COL) == direction)
            .select(
                pl.col("distance_bin").cast(pl.Utf8),
                pl.col(y_col).cast(pl.Float64).alias("freq"),
            )
            .with_columns(distance_sort_expr("distance_bin").alias("_sort_distance"))
            .sort("_sort_distance")
            .drop("_sort_distance")
        )
        completed = (
            bins_df.join(filtered, on="distance_bin", how="left")
            .with_columns(pl.col("freq").fill_null(0.0))
            .select("distance_bin", "freq")
        )
        out.append((label, completed))
    return out


def student_school_escort_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one student escort-type distribution for the selected direction."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        out.append(
            (
                label,
                df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
                .filter(pl.col(DIRECTION_COL) == direction)
                .select("escort_type", "tour_count"),
            )
        )
    return out


def household_school_escort_chart_data(
    numerator_data_list: list[tuple[str, pl.DataFrame]],
    denominator_data_list: list[tuple[str, pl.DataFrame]],
    direction: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Compute household counts and rates for the selected escort direction."""
    denominator_by_label = {
        label: df.select(
            pl.col("student_count").cast(pl.Int64),
            pl.col("household_count").cast(pl.Float64).alias("total_household_count"),
        )
        for label, df in nonempty(denominator_data_list)
    }
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(numerator_data_list):
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
    """Build one schoolkids-per-tour distribution for the selected direction."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        out.append(
            (
                label,
                df.with_columns(pl.col(DIRECTION_COL).cast(pl.Utf8))
                .filter(pl.col(DIRECTION_COL) == direction)
                .select(
                    pl.col("student_count").cast(pl.Int64),
                    pl.col("avg_schoolkids_per_tour").cast(pl.Float64),
                    pl.col("tour_count").cast(pl.Float64),
                ),
            )
        )
    return out


def student_count_category_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    """Return observed student-count bins in numeric order."""
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


def stop_count_category_values(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    """Return observed stop-count bins in numeric order."""
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
    """Render school escorting and adult chauffeur escorting summaries."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell with one direction selector and two stable sections."""
        direction_opts = self._direction_options()
        self.direction_sel = self.selector(
            "direction",
            widget=pn.widgets.Select(
                name="Direction",
                options=direction_opts,
                value=default_direction_option(direction_opts),
            ),
            label="Direction",
        )
        self._static_body = self.section(
            "escorted_tours_static_body",
            render=self.render_static_body_section,
        )
        self._directional_body = self.section(
            "escorted_tours_directional_body",
            selectors=("direction",),
            render=self.render_directional_body_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Escorted Tours"),
            self.new_section(self._static_body, self._directional_body),
            sizing_mode="stretch_width",
        )

    def _direction_options(self) -> list[str]:
        """Discover available direction values from the core school escort summary."""
        data = self.state.get_summary_table_set(
            "school_escorted_tours_by_escort_type_and_direction",
            "weighted",
        )
        if data is None:
            return ["Both Directions"]
        return direction_options(data)

    def sync_controls(self) -> None:
        """Keep the direction selector aligned with currently available summaries."""
        summaries = self.require_summaries(*CORE_SUMMARY_IDS)
        if summaries is None:
            return
        options = direction_options(
            summaries["school_escorted_tours_by_escort_type_and_direction"]
        )
        self.direction_sel.options = options
        if self.direction_sel.value not in options:
            self.direction_sel.value = default_direction_option(options)

    def _load_page_summaries(self):
        """Load core summaries plus optional add-on summaries used by static sections."""
        summaries = self.require_summaries(*CORE_SUMMARY_IDS)
        if summaries is None:
            return None
        optional_summaries = self.optional_summaries_dict(*OPTIONAL_SUMMARY_IDS)
        return {**summaries, **optional_summaries}

    def render_static_body_section(self):
        """Render the sections that do not depend on the live direction selector."""
        if not self.state.run_labels:
            return [self.no_runs_message()]

        summaries = self._load_page_summaries()
        if summaries is None:
            return [self.summary_only_unavailable_card(summary_ids=CORE_SUMMARY_IDS)]

        stop_values = stop_count_category_values(
            summaries["adult_escort_event_stop_distribution"]
        )
        student_count_values = student_count_category_values(
            summaries["student_households_by_student_count"] or []
        )

        body_objects: list[pn.viewable.Viewable] = []
        body_objects.extend(
            self.render_student_school_escort_section(
                summaries["student_school_escort_status_by_direction"]
            )
        )
        body_objects.extend(
            self.render_household_school_escort_section(
                summaries["student_households_by_student_count"],
                summaries[
                    "households_with_school_escorting_by_student_count_and_direction"
                ],
                student_count_values,
            )
        )
        body_objects.extend(
            self.render_schoolkids_per_escorted_tour_section(
                summaries[
                    "schoolkids_per_escorted_tour_by_student_count_and_direction"
                ],
                student_count_values,
            )
        )
        body_objects.extend(
            self.render_chauffeur_stop_distribution_section(
                summaries["adult_escort_event_stop_distribution"],
                stop_values,
            )
        )
        return [pn.Column(*body_objects)]

    def render_student_school_escort_section(self, summary_data):
        """Render outbound, inbound, and both-direction student escort status charts."""
        charts = self.render_student_school_escort_charts(summary_data)
        return self.render_static_triptych_section(
            title="Student School Tour Escort Status",
            description=STUDENT_ESCORT_DESCRIPTION,
            charts=charts,
            unavailable_detail=(
                "This section only renders when the student school escort summary "
                "is available."
            ),
            missing_items=["student_school_escort_status_by_direction"],
        )

    def render_student_school_escort_charts(self, summary_data):
        """Build the three student escort status charts when the summary is available."""
        if summary_data is None:
            return None

        escort_order = self.config.ordered_values("escort", STUDENT_ESCORT_TYPE_ORDER)
        escort_labels = self.config.ordered_labels("escort", STUDENT_ESCORT_TYPE_ORDER)
        charts: list[pn.viewable.Viewable] = []
        for direction, label in (
            ("outbound", "Outbound"),
            ("inbound", "Inbound"),
            ("both", "Both Directions"),
        ):
            chart_data = self.get_filtered_view(
                "student_school_escort_status",
                direction,
                factory=lambda direction=direction: complete_category_counts(
                    student_school_escort_chart_data(summary_data, direction),
                    category_col="escort_type",
                    category_values=escort_order,
                    value_cols=("tour_count", "pct"),
                ),
            )
            charts.append(
                bar_chart(
                    label_category_data(
                        chart_data,
                        source_col="escort_type",
                        category_id="escort",
                        config=self.config,
                        target_col="escort_type_label",
                    ),
                    x_col="escort_type_label",
                    y_col="tour_count",
                    title=f"Student School Escort Status - {label}",
                    xaxis_title="Escort Type",
                    yaxis_title="Student School Tours",
                    pct_col="pct",
                    as_percent=self.as_percent,
                    xaxis_categoryarray=escort_labels,
                )
            )
        return charts

    def render_household_school_escort_section(
        self,
        denominator_summary,
        numerator_summary,
        student_count_values: list[str],
    ):
        """Render household escorting charts or an unavailable placeholder."""
        charts = self.render_household_school_escort_charts(
            denominator_summary,
            numerator_summary,
            student_count_values,
        )
        return self.render_static_triptych_section(
            title="Households With School Escorting",
            description=HOUSEHOLD_ESCORT_DESCRIPTION,
            charts=charts,
            unavailable_detail=(
                "This section only renders when the household school escort summaries "
                "are available."
            ),
            missing_items=[
                "student_households_by_student_count",
                "households_with_school_escorting_by_student_count_and_direction",
            ],
        )

    def render_household_school_escort_charts(
        self,
        denominator_summary,
        numerator_summary,
        student_count_values: list[str],
    ):
        """Build household escort count/rate charts for each direction."""
        if denominator_summary is None or numerator_summary is None:
            return None

        charts: list[pn.viewable.Viewable] = []
        for direction, label in (
            ("outbound", "Outbound"),
            ("inbound", "Inbound"),
            ("both", "Both Directions"),
        ):
            chart_data = self.get_filtered_view(
                "household_school_escort_status",
                direction,
                factory=lambda direction=direction: complete_category_counts(
                    [
                        (
                            run_label,
                            df.with_columns(
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
                            ),
                        )
                        for run_label, df in household_school_escort_chart_data(
                            numerator_summary,
                            denominator_summary,
                            direction,
                        )
                    ],
                    category_col="student_count",
                    category_values=student_count_values,
                    value_cols=("household_count", "pct"),
                ),
            )
            charts.append(
                bar_chart(
                    chart_data,
                    x_col="student_count",
                    y_col="pct" if self.as_percent else "household_count",
                    title=f"Households With School Escorting - {label}",
                    xaxis_title="Students in Household",
                    yaxis_title=(
                        "Percent of Households with Students (%)"
                        if self.as_percent
                        else "Number of Households with Students"
                    ),
                    as_percent=False,
                    xaxis_categoryarray=student_count_values,
                )
            )
        return charts

    def render_schoolkids_per_escorted_tour_section(
        self,
        summary_data,
        student_count_values: list[str],
    ):
        """Render schoolkids-per-tour charts or an unavailable placeholder."""
        charts = self.render_schoolkids_per_escorted_tour_charts(
            summary_data,
            student_count_values,
        )
        return self.render_static_triptych_section(
            title="Schoolkids Per Escorted Tour",
            description=SCHOOLKIDS_DESCRIPTION,
            charts=charts,
            unavailable_detail=(
                "This section only renders when the schoolkids-per-chauffer-tour "
                "summary is available."
            ),
            missing_items=[
                "schoolkids_per_escorted_tour_by_student_count_and_direction"
            ],
        )

    def render_schoolkids_per_escorted_tour_charts(
        self,
        summary_data,
        student_count_values: list[str],
    ):
        """Build average schoolkids-per-tour charts for each direction."""
        if summary_data is None:
            return None

        charts: list[pn.viewable.Viewable] = []
        for direction, label in (
            ("outbound", "Outbound"),
            ("inbound", "Inbound"),
            ("both", "Both Directions"),
        ):
            chart_data = self.get_filtered_view(
                "schoolkids_per_escorted_tour",
                direction,
                factory=lambda direction=direction: complete_category_counts(
                    [
                        (
                            run_label,
                            df.with_columns(
                                pl.col("student_count")
                                .cast(pl.Utf8)
                                .alias("student_count")
                            ),
                        )
                        for run_label, df in schoolkids_per_escorted_tour_chart_data(
                            summary_data,
                            direction,
                        )
                    ],
                    category_col="student_count",
                    category_values=student_count_values,
                    value_cols=("avg_schoolkids_per_tour", "tour_count"),
                ),
            )
            charts.append(
                bar_chart(
                    chart_data,
                    x_col="student_count",
                    y_col="avg_schoolkids_per_tour",
                    title=f"Schoolkids Per Adult Chauffer Tour - {label}",
                    xaxis_title="Students in Household",
                    yaxis_title="Average Schoolkids per Adult Chauffer Tour",
                    as_percent=False,
                    xaxis_categoryarray=student_count_values,
                )
            )
        return charts

    def render_chauffeur_stop_distribution_section(
        self,
        summary_data,
        stop_values: list[str],
    ):
        """Render the four chauffeur stop-distribution charts."""
        charts = [
            self.render_chauffeur_stop_distribution_chart(
                summary_data,
                segment,
                title,
                stop_values,
            )
            for segment, title in STOP_SEGMENT_LABELS.items()
        ]
        return [
            pn.pane.Markdown("### Chauffer Stop Distribution"),
            pn.pane.Markdown(STOP_DISTRIBUTION_DESCRIPTION),
            pn.Row(*charts[:2], sizing_mode="stretch_width"),
            pn.Row(*charts[2:], sizing_mode="stretch_width"),
        ]

    def render_chauffeur_stop_distribution_chart(
        self,
        summary_data,
        segment: str,
        title: str,
        stop_values: list[str],
    ) -> pn.viewable.Viewable:
        """Render one chauffeur stop-distribution chart."""
        chart_data = self.get_filtered_view(
            "adult_escort_event_stop_distribution",
            segment,
            factory=lambda: complete_category_counts(
                adult_escort_event_stop_chart_data(summary_data, segment),
                category_col="stop_count",
                category_values=stop_values,
                value_cols=("tour_count",),
            ),
        )
        return bar_chart(
            chart_data,
            x_col="stop_count",
            y_col="tour_count",
            title=title,
            xaxis_title="Stop Count",
            yaxis_title="Chauffer Escorting Tour-Legs",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=stop_values,
        )

    def render_static_triptych_section(
        self,
        *,
        title: str,
        description: str,
        charts: list[pn.viewable.Viewable] | None,
        unavailable_detail: str,
        missing_items: list[str],
    ) -> list[pn.viewable.Viewable]:
        """Render a three-chart static section or a targeted unavailable card."""
        if charts is None:
            return [
                pn.pane.Markdown(f"### {title}"),
                pn.pane.Markdown(description),
                self.data_not_available_card(
                    detail=unavailable_detail,
                    missing_items=missing_items,
                ),
            ]
        return [
            pn.pane.Markdown(f"### {title}"),
            pn.pane.Markdown(description),
            pn.Row(*charts, sizing_mode="stretch_width"),
        ]

    def render_directional_body_section(self):
        """Render the charts that depend on the selected escort direction."""
        if not self.state.run_labels:
            return []

        summaries = self._load_page_summaries()
        if summaries is None:
            return []

        direction_label = str(self.direction_sel.value)
        raw_direction = adult_raw_direction(direction_label)
        return [
            pn.Column(
                pn.pane.Markdown("## Adult Chauffer Tours and Trips"),
                selector_row(self.direction_sel),
                pn.pane.Markdown("### Chauffer Person Type Distribution"),
                pn.pane.Markdown(PERSON_TYPE_DESCRIPTION),
                pn.Row(
                    self.render_person_type_chart(
                        summaries["adult_escorted_tours_by_person_type_and_direction"],
                        raw_direction,
                        direction_label,
                    ),
                    sizing_mode="stretch_width",
                ),
                pn.pane.Markdown("### Chauffer Tour and Trip Distance Distributions"),
                pn.pane.Markdown(DISTANCE_DESCRIPTION),
                self.render_distance_chart(
                    summaries["adult_escorted_tour_distance_distribution_by_direction"],
                    raw_direction,
                    direction_label,
                    cache_key="adult_escorted_tour_distance_distribution_by_direction",
                    y_col="tour_count",
                    title_prefix="Chauffer Tour Distance Distribution",
                    yaxis_title="Chauffer Tours",
                ),
                self.render_distance_chart(
                    summaries["adult_escorted_trip_distance_distribution_by_direction"],
                    raw_direction,
                    direction_label,
                    cache_key="adult_escorted_trip_distance_distribution_by_direction",
                    y_col="trip_count",
                    title_prefix="Chauffer Trip Distance Distribution",
                    yaxis_title="Chauffer Trips",
                ),
            )
        ]

    def render_person_type_chart(
        self,
        summary_data,
        raw_direction: str,
        direction_label: str,
    ) -> pn.viewable.Viewable:
        """Render adult escorting tours by person type."""
        person_type_values = ordered_category_values(
            summary_data,
            "person_type",
            category_id="person_type",
            config=self.config,
        )
        chart_data = self.get_filtered_view(
            "adult_escorted_tours_by_person_type_and_direction",
            raw_direction,
            factory=lambda: complete_category_counts(
                escort_person_type_chart_data(summary_data, raw_direction),
                category_col="person_type",
                category_values=person_type_values,
                value_cols=("tour_count",),
            ),
        )
        return bar_chart(
            label_category_data(
                chart_data,
                source_col="person_type",
                category_id="person_type",
                config=self.config,
                target_col="person_type_label",
            ),
            x_col="person_type_label",
            y_col="tour_count",
            title=f"Chauffer Tours by Person Type - {direction_label}",
            xaxis_title="Person Type",
            yaxis_title="Chauffer Tours",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=self.config.ordered_labels(
                "person_type", person_type_values
            ),
        )

    def render_distance_chart(
        self,
        summary_data,
        raw_direction: str,
        direction_label: str,
        *,
        cache_key: str,
        y_col: str,
        title_prefix: str,
        yaxis_title: str,
    ) -> pn.viewable.Viewable:
        """Render one escort distance distribution."""
        chart_data = self.get_filtered_view(
            cache_key,
            raw_direction,
            factory=lambda: escort_distance_chart_data(
                summary_data,
                raw_direction,
                y_col=y_col,
            ),
        )
        return density_chart(
            chart_data,
            x_col="distance_bin",
            y_col="freq",
            title=f"{title_prefix} - {direction_label}",
            xaxis_title="Distance (miles)",
            yaxis_title=yaxis_title,
            normalize=False,
            as_percent=self.as_percent,
            xaxis_categoryarray=DISTANCE_BINS,
            xaxis_tickvals=DISTANCE_BINS,
            xaxis_ticktext=DISTANCE_BINS,
        )


PAGE = DashboardPageDefinition(
    page_id="escorted_tours",
    title="Escorted Tours",
    group_id="daily_travel",
    order=29,
    page_cls=EscortedToursPage,
    required_summary_ids=(*PAGE_SUMMARY_IDS,),
)

EscortedToursPage.definition = PAGE
