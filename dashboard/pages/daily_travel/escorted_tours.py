"""Escorted tours page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import selector_row
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
    ordered_category_values,
)
from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard import DashboardPage, dashboard_page
from dashboard.pages.daily_travel._escorted_tours_data import (
    adult_escort_event_stop_chart_data,
    adult_raw_direction,
    default_direction_option,
    direction_options,
    escort_distance_chart_data,
    escort_person_type_chart_data,
    household_school_escort_chart_data,
    schoolkids_per_escorted_tour_chart_data,
    stop_count_category_values,
    student_count_category_values,
    student_school_escort_chart_data,
)

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


@dashboard_page(
    page_id="escorted_tours",
    title="Escorted Tours",
    group_id="daily_travel",
    order=29,
    required_summary_ids=(*PAGE_SUMMARY_IDS,),
)
class EscortedToursPage(DashboardPage):
    """Render school escorting and adult chauffeur escorting summaries."""

    def build_page(self) -> pn.viewable.Viewable:
        """Build the page shell with one direction selector and two stable sections."""
        school_escort = self.feature("school_escort")
        adult_escort = self.feature("adult_escort")
        direction = self.feature("direction")
        distance = self.feature("distance")
        self.direction_sel = direction.select(
            "value",
            "Direction",
            options=self._direction_options,
            default=lambda options: default_direction_option(list(options)),
        )
        self.escort_distance_range = DistanceRangeControls.create(
            self,
            "escort_distance",
            max_options=capped_distance_max_options(),
            reset_label="Reset distance range",
        )
        self._school_escort_body = school_escort.section(
            "body",
            render=self.render_school_escort_feature,
        )
        self._adult_escort_body = adult_escort.section(
            "body",
            render=self.render_adult_escort_feature,
        )
        self._direction_body = direction.section(
            "body",
            selectors=("value",),
            render=self.render_direction_feature,
        )
        self._distance_body = distance.section(
            "body",
            selectors=(
                "direction.value",
                *self.escort_distance_range.selector_ids,
            ),
            render=self.render_distance_feature,
        )
        return self.new_section(
            pn.pane.Markdown("## Escorted Tours"),
            self._school_escort_body,
            self._adult_escort_body,
            self._direction_body,
            self._distance_body,
            sizing_mode="stretch_width",
        )

    def _direction_options(self) -> list[str]:
        """Discover available direction values from the core school escort summary."""
        data = self.data.summary(
            "school_escorted_tours_by_escort_type_and_direction",
            "weighted",
        )
        if data is None:
            return ["Both Directions"]
        return direction_options(data)

    def _load_page_summaries(self):
        """Load core summaries plus optional add-on summaries used by static sections."""
        summaries = self.data.summaries(*CORE_SUMMARY_IDS)
        if not all(summaries.values()):
            return None
        optional_summaries = self.data.summaries(*OPTIONAL_SUMMARY_IDS, required=False)
        return {**summaries, **optional_summaries}

    def _feature_summaries(self):
        if not self.state.run_labels:
            return None, [self.no_runs_message()]
        summaries = self._load_page_summaries()
        if summaries is None:
            return None, [
                self.summary_only_unavailable_card(summary_ids=CORE_SUMMARY_IDS)
            ]
        return summaries, None

    def render_school_escort_feature(self):
        """Render school status, household, and schoolkids views as one feature."""
        summaries, unavailable = self._feature_summaries()
        if unavailable is not None:
            return unavailable
        student_count_values = student_count_category_values(
            summaries["student_households_by_student_count"] or []
        )
        body: list[pn.viewable.Viewable] = []
        body.extend(
            self.render_student_school_escort_section(
                summaries["student_school_escort_status_by_direction"]
            )
        )
        body.extend(
            self.render_household_school_escort_section(
                summaries["student_households_by_student_count"],
                summaries[
                    "households_with_school_escorting_by_student_count_and_direction"
                ],
                student_count_values,
            )
        )
        body.extend(
            self.render_schoolkids_per_escorted_tour_section(
                summaries[
                    "schoolkids_per_escorted_tour_by_student_count_and_direction"
                ],
                student_count_values,
            )
        )
        return body

    def render_adult_escort_feature(self):
        """Render the adult chauffeur stop-distribution feature."""
        summaries, unavailable = self._feature_summaries()
        if unavailable is not None:
            return unavailable
        return self.render_chauffeur_stop_distribution_section(
            summaries["adult_escort_event_stop_distribution"],
            stop_count_category_values(
                summaries["adult_escort_event_stop_distribution"]
            ),
        )

    def render_direction_feature(self):
        """Render the direction-dependent adult chauffeur profile."""
        summaries, unavailable = self._feature_summaries()
        if unavailable is not None:
            return unavailable
        direction_label = str(self.direction_sel.value)
        raw_direction = adult_raw_direction(direction_label)
        return [
            pn.pane.Markdown("## Adult Chauffeur Tours and Trips"),
            selector_row(self.direction_sel),
            pn.pane.Markdown("### Chauffeur Person Type Distribution"),
            pn.pane.Markdown(PERSON_TYPE_DESCRIPTION),
            self.render_person_type_chart(
                summaries["adult_escorted_tours_by_person_type_and_direction"],
                raw_direction,
                direction_label,
            ),
        ]

    def render_distance_feature(self):
        """Render adult chauffeur tour/trip distance controls and charts."""
        summaries, unavailable = self._feature_summaries()
        if unavailable is not None:
            return unavailable
        direction_label = str(self.direction_sel.value)
        raw_direction = adult_raw_direction(direction_label)
        tour_distance_data = self.escort_distance_data(
            summaries["adult_escorted_tour_distance_distribution_by_direction"],
            raw_direction,
            y="tour_count",
        )
        trip_distance_data = self.escort_distance_data(
            summaries["adult_escorted_trip_distance_distribution_by_direction"],
            raw_direction,
            y="trip_count",
        )
        observed_bounds = distance_axis_bounds(
            [*tour_distance_data, *trip_distance_data]
        )
        bounds = (0.0, 40.0) if observed_bounds is not None else None
        self.escort_distance_range.sync((raw_direction, self.weighting_key), bounds)
        x_range = self.escort_distance_range.current_range()
        if bounds is not None and x_range is None:
            charts = self.data_not_available_card(
                detail="Chauffeur distance controls require finite values with min less than max.",
                title="Chauffeur Distance Data Not Available",
            )
        else:
            charts = pn.Row(
                self.render_distance_chart(
                    tour_distance_data,
                    direction_label,
                    title_prefix="Chauffeur Tour Distance Distribution",
                    yaxis_title="Chauffeur Tours",
                    x_range=x_range,
                ),
                self.render_distance_chart(
                    trip_distance_data,
                    direction_label,
                    title_prefix="Chauffeur Trip Distance Distribution",
                    yaxis_title="Chauffeur Trips",
                    x_range=x_range,
                ),
                sizing_mode="stretch_width",
            )
        return [
            pn.pane.Markdown("### Chauffeur Tour and Trip Distance Distributions"),
            pn.pane.Markdown(DISTANCE_DESCRIPTION),
            self.escort_distance_range.row(),
            charts,
        ]

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
            chart_data = self.query(
                lambda direction=direction: complete_category_counts(
                    student_school_escort_chart_data(summary_data, direction),
                    category="escort_type",
                    category_values=escort_order,
                    value_cols=("tour_count", "pct"),
                )
            )
            charts.append(
                self.plot.bar(
                    label_category_data(
                        chart_data,
                        source_col="escort_type",
                        category_id="escort",
                        config=self.config,
                        target_col="escort_type_label",
                    ),
                    x="escort_type_label",
                    y="tour_count",
                    title=f"Student School Escort Status - {label}",
                    x_title="Escort Type",
                    y_title="Student School Tours",
                    category_order=escort_labels,
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
            chart_data = self.query(
                lambda direction=direction: complete_category_counts(
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
                    category="student_count",
                    category_values=student_count_values,
                    value_cols=("household_count", "pct"),
                )
            )
            charts.append(
                self.plot.bar(
                    chart_data,
                    x="student_count",
                    y="pct" if self.as_percent else "household_count",
                    title=f"Households With School Escorting - {label}",
                    x_title="Students in Household",
                    y_title=(
                        "Percent of Households with Students (%)"
                        if self.as_percent
                        else "Number of Households with Students"
                    ),
                    value_mode="count",
                    category_order=student_count_values,
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
            chart_data = self.query(
                lambda direction=direction: complete_category_counts(
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
                    category="student_count",
                    category_values=student_count_values,
                    value_cols=("avg_schoolkids_per_tour", "tour_count"),
                )
            )
            charts.append(
                self.plot.bar(
                    chart_data,
                    x="student_count",
                    y="avg_schoolkids_per_tour",
                    title=f"Schoolkids Per Adult Chauffeur Tour - {label}",
                    x_title="Students in Household",
                    y_title="Average Schoolkids per Adult Chauffeur Tour",
                    value_mode="count",
                    category_order=student_count_values,
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
        chart_data = self.query(
            lambda: complete_category_counts(
                adult_escort_event_stop_chart_data(summary_data, segment),
                category="stop_count",
                category_values=stop_values,
                value_cols=("tour_count",),
            )
        )
        return self.plot.bar(
            chart_data,
            x="stop_count",
            y="tour_count",
            title=title,
            x_title="Stop Count",
            y_title="Chauffer Escorting Tour-Legs",
            category_order=stop_values,
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
        chart_data = self.query(
            lambda: complete_category_counts(
                escort_person_type_chart_data(summary_data, raw_direction),
                category="person_type",
                category_values=person_type_values,
                value_cols=("tour_count",),
            )
        )
        return self.plot.bar(
            label_category_data(
                chart_data,
                source_col="person_type",
                category_id="person_type",
                config=self.config,
                target_col="person_type_label",
            ),
            x="person_type_label",
            y="tour_count",
            title=f"Chauffeur Tours by Person Type - {direction_label}",
            x_title="Person Type",
            y_title="Chauffeur Tours",
            category_order=self.config.ordered_labels(
                "person_type", person_type_values
            ),
        )

    def escort_distance_data(
        self,
        summary_data,
        raw_direction: str,
        *,
        y: str,
    ) -> list[tuple[str, pl.DataFrame]]:
        """Return one chart-ready escort distance distribution."""
        return self.query(
            lambda: escort_distance_chart_data(
                summary_data,
                raw_direction,
                y_col=y,
            )
        )

    def render_distance_chart(
        self,
        chart_data: list[tuple[str, pl.DataFrame]],
        direction_label: str,
        *,
        title_prefix: str,
        yaxis_title: str,
        x_range: tuple[float, float] | None,
    ) -> pn.viewable.Viewable:
        """Render one escort distance distribution."""
        axis_data = with_distance_axis(chart_data)
        tickvals, ticktext = fixed_distance_axis_ticks()
        return self.plot.density(
            axis_data,
            x="_distance_axis",
            y="freq",
            title=f"{title_prefix} - {direction_label}",
            x_title="Distance (miles)",
            y_title=yaxis_title,
            x_range=x_range,
            tick_values=tickvals,
            tick_text=ticktext,
        )
