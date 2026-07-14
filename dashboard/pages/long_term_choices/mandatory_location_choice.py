"""Mandatory location choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import data_table, selector_row
from dashboard.helpers.distance_range import (
    DistanceRangeControls,
    capped_distance_max_options,
    distance_axis_bounds,
    fixed_distance_axis_ticks,
    with_distance_axis,
)
from dashboard.helpers.geography_helpers import (
    ALL_GEOGRAPHY_TYPES_LABEL,
    ALL_GEOGRAPHY_TYPES_VALUE,
    ALL_WITHIN_LEVEL_VALUE,
    GEOGRAPHY_NAME_SELECTOR_LABEL,
    GEOGRAPHY_TYPE_SELECTOR_LABEL,
    export_geography_name_options,
    filter_geography,
    filter_geography_level,
    geography_name_options_for_type,
    geography_name_selector_label,
    geography_type_options,
    geography_name_label,
    is_all_geographies,
    normalize_geography_data,
    with_display_geography_columns,
)
from dashboard import DashboardPage, dashboard_page
from dashboard.page_base import SectionContent
from dashboard.pages.long_term_choices._mandatory_location_choice_support import (
    adapt_external_workplace,
    distance_distribution_chart_data,
    external_workplace_percent_data,
    filter_selected_geography,
    mandatory_distance_comparison_table,
    selected_telecommute_values,
    telecommute_chart_data,
    work_from_home_chart_data,
)


@dashboard_page(
    page_id="mandatory_location_choice",
    title="Mandatory Location Choice",
    group_id="long_term_choices",
    order=27,
    required_summary_ids=(
        "internal_external_worker_by_geography",
        "external_worker_workplace_locations",
        "work_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        "work_from_home_rate_by_geography",
        "telecommute_frequency_distribution",
        "average_mandatory_tour_distance_by_purpose_and_geography",
    ),
)
class MandatoryLocationChoicePage(DashboardPage):
    """Geography-driven page for mandatory worker, commute, and distance summaries."""

    def on_global_state_changed(self) -> None:
        """Invalidate page-local caches when the dashboard's global state changes."""
        self.clear_query_cache()
        self._current_data = self._collect_data()

    def build_page(self) -> pn.viewable.Viewable:
        """Build the persistent selectors and stable section containers."""
        self._current_data: dict[str, object] = {}
        self._geo_level_raw_by_label: dict[str, str | None] = {
            ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
        }
        self._geography_raw_by_label: dict[str, str | None] = {
            ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE
        }
        self.geo_level_sel = self.select(
            "geography_level",
            GEOGRAPHY_TYPE_SELECTOR_LABEL,
            options=self._geography_level_options,
        )
        self.geography_sel = self.select(
            "geography",
            GEOGRAPHY_NAME_SELECTOR_LABEL,
            options=self._geography_options,
        )
        self.mandatory_distance_range = DistanceRangeControls.create(
            self,
            "mandatory_distance",
            max_options=capped_distance_max_options(),
            reset_label="Reset distance range",
        )
        geography = self.feature("geography_comparison")
        flows = self.feature("flows")
        distance = self.feature("distance")
        remote_work = self.feature("remote_work")
        self._remote_work_section = remote_work.section(
            "body",
            selectors=("geography_level", "geography"),
            render=self.render_remote_work_section,
        )
        self._distance_section = distance.section(
            "distribution",
            selectors=(
                "geography_level",
                "geography",
                *self.mandatory_distance_range.selector_ids,
            ),
            render=self.render_distance_distribution_section,
        )
        self._worker_section = flows.section(
            "body",
            selectors=("geography_level", "geography"),
            render=self.render_worker_geography_section,
        )
        self._mandatory_distance_table_section = geography.section(
            "body",
            selectors=("geography_level", "geography"),
            render=self.render_mandatory_distance_table_section,
        )

        return self.new_section(
            pn.pane.Markdown("## Mandatory Location Choice"),
            selector_row(self.geo_level_sel, self.geography_sel),
            self._remote_work_section,
            self._distance_section,
            self._worker_section,
            self._mandatory_distance_table_section,
        )

    def _geography_level_options(self) -> list[str]:
        """Return available geography levels and refresh their raw mapping."""
        if not self._current_data:
            self._current_data = self._collect_data()
        geo_opts = self._current_data["geo_opts"]
        self._geo_level_raw_by_label = self._current_data["geo_raw_by_label"]
        return geo_opts

    def _geography_options(self) -> list[str]:
        """Return names valid for the selected geography level."""
        if not self._current_data:
            self._current_data = self._collect_data()
        geography_opts_by_level = self._current_data["geography_opts_by_level"]
        selected_geo_level = self.selected_geography_level_raw()
        if self.state.export_mode:
            geography_opts, self._geography_raw_by_label = (
                export_geography_name_options(
                    geography_opts_by_level,
                    config=self.config,
                )
            )
        else:
            geography_opts, self._geography_raw_by_label = geography_opts_by_level.get(
                selected_geo_level,
                (
                    [ALL_WITHIN_LEVEL_VALUE],
                    {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                ),
            )
        if getattr(self, "geography_sel", None) is not None:
            self.geography_sel.name = geography_name_selector_label(
                selected_geo_level,
                config=self.config,
            )
        return geography_opts

    def selected_geography_level_raw(self) -> str:
        """Return the raw geography type value selected in the display selector."""
        selected = str(self.geo_level_sel.value)
        raw_value = self._geo_level_raw_by_label.get(selected, selected)
        return ALL_GEOGRAPHY_TYPES_VALUE if raw_value is None else str(raw_value)

    def selected_geography_raw(self) -> str:
        """Return the raw geography name/id value selected in the display selector."""
        selected = str(self.geography_sel.value)
        raw_value = self._geography_raw_by_label.get(selected, selected)
        return ALL_WITHIN_LEVEL_VALUE if raw_value is None else str(raw_value)

    def export_canonical_selector_value(
        self,
        section_id: str,
        selector_id: str,
        value: str,
        selected_values: dict[str, str],
    ) -> str:
        if selector_id != "geography":
            return value

        selected_geo_level = selected_values.get("geography_level")
        raw_geo_level = self._geo_level_raw_by_label.get(
            str(selected_geo_level),
            selected_geo_level,
        )
        raw_geo_level = (
            ALL_GEOGRAPHY_TYPES_VALUE if raw_geo_level is None else str(raw_geo_level)
        )
        geography_opts_by_level = self._current_data.get("geography_opts_by_level", {})
        _, raw_by_label = geography_opts_by_level.get(
            raw_geo_level,
            (
                [ALL_WITHIN_LEVEL_VALUE],
                {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
            ),
        )
        raw_geography = self._geography_raw_by_label.get(value, value)
        raw_geography = (
            ALL_WITHIN_LEVEL_VALUE if raw_geography is None else str(raw_geography)
        )
        valid_values = {str(raw) for raw in raw_by_label.values() if raw is not None}
        if raw_geography in valid_values:
            return value
        return ALL_WITHIN_LEVEL_VALUE

    def _selected_geography(self) -> tuple[str, str]:
        """Return the effective geography selection, honoring export-mode flattening."""
        geo_level = self.selected_geography_level_raw()
        geography = self.selected_geography_raw()
        if not self.state.export_mode:
            return geo_level, geography

        geography_opts_by_level = self._current_data.get("geography_opts_by_level", {})
        _, raw_by_label = geography_opts_by_level.get(
            geo_level,
            (
                [ALL_WITHIN_LEVEL_VALUE],
                {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
            ),
        )
        valid_options = {
            str(value) for value in raw_by_label.values() if value is not None
        }
        if geography in valid_options:
            return geo_level, geography
        return geo_level, ALL_WITHIN_LEVEL_VALUE

    def _collect_data(self) -> dict[str, object]:
        """Collect and normalize every summary used by the page."""
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": [ALL_GEOGRAPHY_TYPES_LABEL],
                "geo_raw_by_label": {
                    ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
                },
                "geography_opts_by_level": {
                    ALL_GEOGRAPHY_TYPES_VALUE: (
                        [ALL_WITHIN_LEVEL_VALUE],
                        {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                    )
                },
            }

        summaries = self.data.summaries(
            "internal_external_worker_by_geography",
            "external_worker_workplace_locations",
            "work_from_home_rate_by_geography",
            "telecommute_frequency_distribution",
            "work_location_distance_distribution_by_geography",
            "school_location_distance_distribution_by_geography",
            "university_location_distance_distribution_by_geography",
            "average_mandatory_tour_distance_by_purpose_and_geography",
        )

        if not any(summary is not None for summary in summaries.values()):
            return {
                "mode": "unavailable",
                "geo_opts": [ALL_GEOGRAPHY_TYPES_LABEL],
                "geo_raw_by_label": {
                    ALL_GEOGRAPHY_TYPES_LABEL: ALL_GEOGRAPHY_TYPES_VALUE
                },
                "geography_opts_by_level": {
                    ALL_GEOGRAPHY_TYPES_VALUE: (
                        [ALL_WITHIN_LEVEL_VALUE],
                        {ALL_WITHIN_LEVEL_VALUE: ALL_WITHIN_LEVEL_VALUE},
                    )
                },
            }

        internal_external = normalize_geography_data(
            summaries["internal_external_worker_by_geography"]
        )
        external_workplace = adapt_external_workplace(
            summaries["external_worker_workplace_locations"]
        )
        work_from_home = normalize_geography_data(
            summaries["work_from_home_rate_by_geography"]
        )
        telecommute = normalize_geography_data(
            summaries["telecommute_frequency_distribution"]
        )
        work_distance = normalize_geography_data(
            summaries["work_location_distance_distribution_by_geography"]
        )
        school_distance = normalize_geography_data(
            summaries["school_location_distance_distribution_by_geography"]
        )
        university_distance = normalize_geography_data(
            summaries["university_location_distance_distribution_by_geography"]
        )
        average_distance = normalize_geography_data(
            summaries["average_mandatory_tour_distance_by_purpose_and_geography"]
        )

        geo_opts, geo_raw_by_label = geography_type_options(
            internal_external or None,
            work_from_home or None,
            work_distance or None,
            school_distance or None,
            university_distance or None,
            average_distance or None,
            config=self.config,
            include_all_types=True,
        )
        geography_option_sources = (
            internal_external or None,
            work_distance or None,
            school_distance or None,
            university_distance or None,
            average_distance or None,
        )
        geography_opts_by_level = {
            str(raw_geo_level): geography_name_options_for_type(
                str(raw_geo_level),
                *geography_option_sources,
                config=self.config,
            )
            for raw_geo_level in geo_raw_by_label.values()
            if raw_geo_level is not None
        }
        return {
            "mode": "ready",
            "geo_opts": geo_opts,
            "geo_raw_by_label": geo_raw_by_label,
            "geography_opts_by_level": geography_opts_by_level,
            "internal_external": internal_external or None,
            "external_workplace": external_workplace or None,
            "work_from_home": work_from_home or None,
            "telecommute": telecommute or None,
            "work_distance": work_distance or None,
            "school_distance": school_distance or None,
            "university_distance": university_distance or None,
            "average_distance": average_distance or None,
        }

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
            worker_views.append(
                data_table(
                    [
                        (label, self.render_internal_external_worker_table(df))
                        for label, df in internal_external_table
                    ],
                    "Internal vs. External Workers",
                )
            )
        else:
            worker_views.append(
                self.data_not_available_card(
                    detail="The internal/external worker summary is unavailable.",
                    missing_items=["internal_external_worker_by_geography"],
                )
            )

        worker_views.append(self.render_external_workplace_chart(geo_level, geography))
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
        if self._current_data["mode"] != "ready":
            return []

        geo_level, geography = self._selected_geography()
        chart_specs = [
            {
                "summary_data": self._current_data["work_distance"],
                "title": "Workplace Location Distance Distribution",
                "yaxis_title": "Workplace Locations",
                "summary_id": "work_location_distance_distribution_by_geography",
            },
            {
                "summary_data": self._current_data["school_distance"],
                "title": "School Location Distance Distribution",
                "yaxis_title": "School Locations",
                "summary_id": "school_location_distance_distribution_by_geography",
            },
            {
                "summary_data": self._current_data["university_distance"],
                "title": "University Location Distance Distribution",
                "yaxis_title": "University Locations",
                "summary_id": "university_location_distance_distribution_by_geography",
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
                    self.render_distance_distribution_chart(
                        geo_level,
                        geography,
                        summary_data=spec["summary_data"],
                        title=spec["title"],
                        yaxis_title=spec["yaxis_title"],
                        summary_id=spec["summary_id"],
                        distance_data=distance_data,
                        x_range=x_range,
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
        if self._current_data["mode"] != "ready":
            return []

        geo_level, geography = self._selected_geography()
        return [
            pn.pane.Markdown("### Remote Work"),
            pn.Row(
                self.render_work_from_home_chart(geo_level, geography),
                self.render_telecommute_chart(geo_level, geography),
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
        if self._current_data["mode"] != "ready":
            return []

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
            data_table(
                comparison_tables,
                "Average Mandatory Tour Distance vs Base Run",
            )
        ]
