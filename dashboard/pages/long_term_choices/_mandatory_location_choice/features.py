"""Feature rendering for Mandatory Location Choice."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard.helpers.geography_helpers import *
from dashboard.page_base import SectionContent
from dashboard.rendering import data_table, selector_row
from dashboard.pages.long_term_choices._mandatory_location_choice_support import *


class MandatoryLocationFeatureMixin:
    def _render_ready_state(self) -> SectionContent | None:
        """Return a shared top-level placeholder for no-runs or no-summary states."""
        mode = self._current_data["mode"]
        if mode == "no_runs":
            return [self.no_runs_message()]
        if mode == "unavailable":
            return [self.summary_only_unavailable_card()]
        return None

    def render_worker_geography_section(self) -> SectionContent:
        """Render internal/external worker comparisons and external workplace charts."""
        placeholder = self._render_ready_state()
        if placeholder is not None:
            return placeholder

        geo_level, geography = self._selected_geography()
        worker_views: list[pn.viewable.Viewable] = []
        internal_external = self._current_data["internal_external"]
        if internal_external is not None:
            internal_external_table = self.query(
                lambda: filter_selected_geography(
                    internal_external,
                    geo_level,
                    geography,
                )
            )
            if any(not df.is_empty() for _, df in internal_external_table):
                worker_views.append(
                    self.noted_view(
                        "mandatory_location.worker_status_table",
                        data_table(
                            [
                                (
                                    label,
                                    self.render_internal_external_worker_table(df),
                                )
                                for label, df in internal_external_table
                            ],
                            "Internal vs. External Workers",
                        ),
                    )
                )
            else:
                worker_views.append(
                    self.data_not_available_card(
                        detail=(
                            "No internal/external worker data is available for "
                            "the selected geography."
                        ),
                        missing_items=["internal_external_worker_by_geography"],
                    )
                )
        else:
            worker_views.append(
                self.data_not_available_card(
                    detail="The internal/external worker summary is unavailable.",
                    missing_items=["internal_external_worker_by_geography"],
                )
            )

        worker_views.append(
            self.noted_view(
                "mandatory_location.external_workplace",
                self.render_external_workplace_chart(geo_level, geography),
            )
        )
        return worker_views

    def render_internal_external_worker_table(self, df: pl.DataFrame) -> pl.DataFrame:
        """Return a display-ready internal/external worker geography table."""
        display_df = with_display_geography_columns(df, config=self.config)
        columns = [
            column
            for column in (
                "Geography Type",
                "Geography Name",
                "internal_worker_count",
                "external_worker_count",
            )
            if column in display_df.columns
        ]
        return display_df.select(columns) if columns else display_df

    def render_external_workplace_chart(
        self,
        geo_level: str,
        geography: str,
    ) -> pn.viewable.Viewable:
        """Render workplace locations for workers with external jobs."""
        external_workplace = self._current_data["external_workplace"]
        if external_workplace is None:
            return self.data_not_available_card(
                detail="The external workplace summary is unavailable.",
                missing_items=["external_worker_workplace_locations"],
            )

        external_workplace_level_data = self.query(
            lambda: filter_geography_level(external_workplace, geo_level)
        )
        filtered_external_workplace = self.query(
            lambda: filter_geography(external_workplace_level_data, geography)
        )
        if not any(not df.is_empty() for _, df in filtered_external_workplace):
            return self.data_not_available_card(
                detail=(
                    "No external workplace location data is available for the selected "
                    "geography. This summary can render MPO, County, or other configured "
                    "workplace geographies only when the prepared person data includes the "
                    "corresponding work geography columns."
                ),
                missing_items=["external_worker_workplace_locations"],
            )
        chart_data = filtered_external_workplace
        if self.as_percent:
            chart_data = self.query(
                lambda: external_workplace_percent_data(
                    filtered_external_workplace,
                    geo_level,
                )
            )
        chart_data = [
            (
                label,
                df.with_columns(
                    pl.col("workplace_location")
                    .cast(pl.Utf8)
                    .map_elements(
                        lambda value: geography_name_label(value, config=self.config),
                        return_dtype=pl.Utf8,
                    )
                    .alias("workplace_location_label")
                ),
            )
            for label, df in chart_data
            if df is not None and "workplace_location" in df.columns
        ]
        workplace_location_values = sorted(
            {
                str(value)
                for _, df in chart_data
                for value in (
                    df["workplace_location_label"].cast(pl.Utf8).to_list()
                    if "workplace_location_label" in df.columns
                    else []
                )
            }
        )

        return self.plot.bar(
            chart_data,
            x="workplace_location_label",
            y=(
                "external_worker_percent"
                if self.as_percent and is_all_geographies(geo_level)
                else "person_count"
            ),
            title="External Worker Workplace Location",
            x_title="Workplace Location",
            y_title=(
                "Workers with External Workplaces (%)"
                if self.as_percent and is_all_geographies(geo_level)
                else "External Workers"
            ),
            value_mode="count" if is_all_geographies(geo_level) else "dashboard",
            category_order=workplace_location_values,
        )

    def render_distance_distribution_section(self) -> SectionContent:
        """Render the three mandatory distance distributions side by side."""
        placeholder = self._render_ready_state()
        if placeholder is not None:
            return placeholder

        geo_level, geography = self._selected_geography()
        chart_specs = [
            {
                "summary_data": self._current_data["work_distance"],
                "title": "Workplace Location Distance Distribution",
                "yaxis_title": "Workplace Locations",
                "summary_id": "work_location_distance_distribution_by_geography",
                "note_id": "mandatory_location.work_distance",
            },
            {
                "summary_data": self._current_data["school_distance"],
                "title": "School Location Distance Distribution",
                "yaxis_title": "School Locations",
                "summary_id": "school_location_distance_distribution_by_geography",
                "note_id": "mandatory_location.school_distance",
            },
            {
                "summary_data": self._current_data["university_distance"],
                "title": "University Location Distance Distribution",
                "yaxis_title": "University Locations",
                "summary_id": "university_location_distance_distribution_by_geography",
                "note_id": "mandatory_location.university_distance",
            },
        ]
        prepared_charts = [
            (
                spec,
                self.distance_distribution_chart_data(
                    geo_level,
                    geography,
                    summary_data=spec["summary_data"],
                ),
            )
            for spec in chart_specs
        ]
        observed_bounds = distance_axis_bounds(
            [
                item
                for _, distance_data in prepared_charts
                if distance_data is not None
                for item in distance_data
            ]
        )
        bounds = (0.0, 40.0) if observed_bounds is not None else None
        self.mandatory_distance_range.sync(
            (geo_level, geography, self.weighting_key),
            bounds,
        )
        x_range = self.mandatory_distance_range.current_range()
        if bounds is not None and x_range is None:
            return [
                pn.pane.Markdown("### Mandatory Location Distance"),
                self.mandatory_distance_range.row(),
                self.data_not_available_card(
                    detail="Mandatory location distance controls require finite values with min less than max.",
                    title="Mandatory Location Distance Data Not Available",
                ),
            ]
        return [
            pn.pane.Markdown("### Mandatory Location Distance"),
            self.mandatory_distance_range.row(),
            pn.Row(
                *[
                    self.noted_view(
                        spec["note_id"],
                        self.render_distance_distribution_chart(
                            geo_level,
                            geography,
                            summary_data=spec["summary_data"],
                            title=spec["title"],
                            yaxis_title=spec["yaxis_title"],
                            summary_id=spec["summary_id"],
                            distance_data=distance_data,
                            x_range=x_range,
                        ),
                    )
                    for spec, distance_data in prepared_charts
                ],
                sizing_mode="stretch_width",
            ),
        ]

    def distance_distribution_chart_data(
        self,
        geo_level: str,
        geography: str,
        *,
        summary_data: list[tuple[str, pl.DataFrame]] | None,
    ) -> list[tuple[str, pl.DataFrame]] | None:
        """Return chart-ready mandatory distance data for one summary."""
        if summary_data is None:
            return None
        filtered_summary = self.query(
            lambda: filter_selected_geography(
                summary_data,
                geo_level,
                geography,
            )
        )
        return self.query(lambda: distance_distribution_chart_data(filtered_summary))

    def render_distance_distribution_chart(
        self,
        geo_level: str,
        geography: str,
        *,
        summary_data: list[tuple[str, pl.DataFrame]] | None,
        title: str,
        yaxis_title: str,
        summary_id: str,
        distance_data: list[tuple[str, pl.DataFrame]] | None = None,
        x_range: tuple[float, float] | None = None,
    ) -> pn.viewable.Viewable:
        """Render one distance-distribution chart or a targeted unavailable card."""
        if summary_data is None or distance_data is None:
            return self.data_not_available_card(
                detail="The selected distance distribution summary is unavailable.",
                missing_items=[summary_id],
            )
        if not any(not df.is_empty() for _, df in distance_data):
            return self.data_not_available_card(
                detail=(
                    f"No distance distribution data is available for geography "
                    f"`{geography}` at level `{geo_level}`."
                ),
                missing_items=[summary_id],
            )

        axis_data = with_distance_axis(distance_data)
        tickvals, ticktext = fixed_distance_axis_ticks()
        return self.plot.density(
            axis_data,
            x="_distance_axis",
            y="person_count",
            title=title,
            x_title="Distance (miles)",
            y_title=yaxis_title,
            x_range=x_range,
            tick_values=tickvals,
            tick_text=ticktext,
        )

    def render_remote_work_section(self) -> SectionContent:
        """Render work-from-home and telecommute summaries."""
        placeholder = self._render_ready_state()
        if placeholder is not None:
            return placeholder

        geo_level, geography = self._selected_geography()
        return [
            pn.pane.Markdown("### Remote Work"),
            pn.Row(
                self.noted_view(
                    "mandatory_location.work_from_home",
                    self.render_work_from_home_chart(geo_level, geography),
                ),
                self.noted_view(
                    "mandatory_location.telecommute",
                    self.render_telecommute_chart(geo_level, geography),
                ),
            ),
        ]

    def render_work_from_home_chart(
        self,
        geo_level: str,
        geography: str,
    ) -> pn.viewable.Viewable:
        """Render work-from-home counts or rates by geography."""
        work_from_home = self._current_data["work_from_home"]
        if work_from_home is None:
            return self.data_not_available_card(
                detail="The work-from-home summary is unavailable.",
                missing_items=["work_from_home_rate_by_geography"],
            )

        wfh_data = self.query(
            lambda: work_from_home_chart_data(
                work_from_home,
                geo_level,
                geography,
            )
        )
        if not any(not df.is_empty() for _, df in wfh_data):
            return self.data_not_available_card(
                detail=(
                    "No work-from-home data is available for the selected geography."
                ),
                missing_items=["work_from_home_rate_by_geography"],
            )
        return self.plot.bar(
            wfh_data,
            x="geography_label",
            y=(
                "work_from_home_percent"
                if self.as_percent
                else "work_from_home_worker_count"
            ),
            title=(
                "Work From Home Rate by Geography"
                if self.as_percent
                else "Workers Working From Home by Geography"
            ),
            x_title="Geography",
            y_title=(
                "Workers Working From Home (%)"
                if self.as_percent
                else "Workers Working From Home"
            ),
            value_mode="count",
        )

    def render_telecommute_chart(
        self,
        geo_level: str,
        geography: str,
    ) -> pn.viewable.Viewable:
        """Render telecommute frequency for workers who do not work from home."""
        telecommute = self._current_data["telecommute"]
        if telecommute is None:
            return self.data_not_available_card(
                detail="The telecommute summary is unavailable.",
                missing_items=["telecommute_frequency_distribution"],
            )

        telecommute_level_data = self.query(
            lambda: filter_geography_level(telecommute, geo_level)
        )
        telecommute_values = selected_telecommute_values(
            telecommute_level_data,
            config=self.config,
        )
        filtered_telecommute = self.query(
            lambda: filter_geography(telecommute_level_data, geography)
        )
        chart_data = self.query(
            lambda: telecommute_chart_data(
                filtered_telecommute,
                telecommute_values,
                config=self.config,
            )
        )
        return self.plot.bar(
            chart_data,
            x="telecommute_frequency_label",
            y="person_count",
            title="Telecommute Rate",
            x_title="Telecommute Frequency",
            y_title="Workers Who Do Not Work From Home",
            category_order=self.config.ordered_labels(
                "telecommute_frequency",
                telecommute_values,
            ),
        )

    def render_mandatory_distance_table_section(self) -> SectionContent:
        """Render the percent-difference table for average mandatory tour distance."""
        placeholder = self._render_ready_state()
        if placeholder is not None:
            return placeholder

        geo_level, geography = self._selected_geography()
        average_distance = self._current_data["average_distance"]
        if average_distance is None:
            return [
                self.data_not_available_card(
                    detail="The average mandatory tour distance summary is unavailable.",
                    missing_items=[
                        "average_mandatory_tour_distance_by_purpose_and_geography"
                    ],
                )
            ]

        comparison_tables = self.query(
            lambda: mandatory_distance_comparison_table(
                average_distance,
                geo_level,
                geography,
                config=self.config,
            )
        )
        if not comparison_tables:
            return [
                self.data_not_available_card(
                    detail=(
                        f"No average mandatory tour distance data is available for "
                        f"geography `{geography}` at level `{geo_level}`."
                    ),
                    missing_items=[
                        "average_mandatory_tour_distance_by_purpose_and_geography"
                    ],
                )
            ]

        return [
            self.noted_view(
                "mandatory_location.average_distance",
                data_table(
                    comparison_tables,
                    "Average Mandatory Tour Distance vs Base Run",
                ),
            )
        ]
