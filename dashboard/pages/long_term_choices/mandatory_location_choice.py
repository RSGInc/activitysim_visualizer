"""Mandatory location choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, density_chart
from dashboard.helpers.geography_helpers import (
    ALL_WITHIN_LEVEL_VALUE,
    export_geography_options,
    filter_geography,
    filter_geography_level,
    filter_origin_geography,
    geography_level_options,
    geography_options_for_level,
    normalize_geography_data,
)
from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages.long_term_choices._mandatory_location_choice_support import (
    adapt_commuting_flows,
    adapt_external_workplace,
    distance_distribution_chart_data,
    external_workplace_percent_data,
    filter_selected_geography,
    mandatory_distance_comparison_table,
    selected_telecommute_values,
    telecommute_chart_data,
    work_from_home_chart_data,
)


class MandatoryLocationChoicePage(DashboardPage):
    """Geography-driven page for mandatory worker, commute, and distance summaries."""

    def on_global_state_changed(self) -> None:
        """Invalidate page-local caches when the dashboard's global state changes."""
        self.clear_filtered_view_cache()
        self._current_data = self._collect_data()

    def build_page(self) -> pn.viewable.Viewable:
        """Build the persistent selectors and stable section containers."""
        self._current_data: dict[str, object] = {}
        self.geo_level_sel = self.selector(
            "geography_level",
            widget=pn.widgets.Select(
                name="Geography Level",
                options=["Total"],
                value="Total",
            ),
            label="Geography Level",
        )
        self.geography_sel = self.selector(
            "geography",
            widget=pn.widgets.Select(
                name="Geography",
                options=[ALL_WITHIN_LEVEL_VALUE],
                value=ALL_WITHIN_LEVEL_VALUE,
            ),
            label="Geography",
        )
        self._remote_work_section = self.section(
            "remote_work",
            selectors=("geography_level", "geography"),
            render=self.render_remote_work_section,
        )
        self._distance_section = self.section(
            "distance_distribution",
            selectors=("geography_level", "geography"),
            render=self.render_distance_distribution_section,
        )
        self._worker_section = self.section(
            "worker_geography",
            selectors=("geography_level", "geography"),
            render=self.render_worker_geography_section,
        )
        self._commuting_flows_section = self.section(
            "commuting_flows",
            selectors=("geography_level", "geography"),
            render=self.render_commuting_flows_section,
        )
        self._mandatory_distance_table_section = self.section(
            "mandatory_distance_table",
            selectors=("geography_level", "geography"),
            render=self.render_mandatory_distance_table_section,
        )

        return self.new_section(
            pn.pane.Markdown("## Mandatory Location Choice"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
                pn.pane.Markdown("**Geography:**"),
                self.geography_sel,
            ),
            self._remote_work_section,
            self._distance_section,
            self._worker_section,
            self._commuting_flows_section,
            self._mandatory_distance_table_section,
        )

    def sync_controls(self) -> None:
        """Keep geography selectors aligned with the currently available summaries."""
        if not self._current_data:
            self._current_data = self._collect_data()

        geo_opts = self._current_data["geo_opts"]
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]

        geography_opts_by_level = self._current_data["geography_opts_by_level"]
        if self.state.export_mode:
            geography_opts = export_geography_options(
                geography_opts_by_level,
                config=self.config,
            )
        else:
            geography_opts = geography_opts_by_level.get(
                str(self.geo_level_sel.value),
                [ALL_WITHIN_LEVEL_VALUE],
            )
        self.geography_sel.options = geography_opts
        if self.geography_sel.value not in geography_opts:
            self.geography_sel.value = geography_opts[0]

    def _selected_geography(self) -> tuple[str, str]:
        """Return the effective geography selection, honoring export-mode flattening."""
        geo_level = str(self.geo_level_sel.value)
        geography = str(self.geography_sel.value)
        if not self.state.export_mode:
            return geo_level, geography

        geography_opts_by_level = self._current_data.get("geography_opts_by_level", {})
        valid_options = set(geography_opts_by_level.get(geo_level, [ALL_WITHIN_LEVEL_VALUE]))
        if geography in valid_options:
            return geo_level, geography
        return geo_level, ALL_WITHIN_LEVEL_VALUE

    def _collect_data(self) -> dict[str, object]:
        """Collect and normalize every summary used by the page."""
        if not self.state.run_labels:
            return {
                "mode": "no_runs",
                "geo_opts": ["Total"],
                "geography_opts_by_level": {"Total": [ALL_WITHIN_LEVEL_VALUE]},
            }

        summaries = self.optional_summaries_dict(
            "internal_external_worker_by_geography",
            "external_worker_workplace_locations",
            "commuting_flows",
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
                "geo_opts": ["Total"],
                "geography_opts_by_level": {"Total": [ALL_WITHIN_LEVEL_VALUE]},
            }

        internal_external = normalize_geography_data(
            summaries["internal_external_worker_by_geography"]
        )
        external_workplace = adapt_external_workplace(
            summaries["external_worker_workplace_locations"]
        )
        commuting_flows = adapt_commuting_flows(summaries["commuting_flows"])
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

        geo_opts = geography_level_options(
            internal_external or None,
            commuting_flows or None,
            work_from_home or None,
            config=self.config,
            total_label="Total",
        )
        geography_option_sources = (
            internal_external or None,
            commuting_flows or None,
            work_distance or None,
            school_distance or None,
            university_distance or None,
            average_distance or None,
        )
        geography_opts_by_level = {
            geo_level: geography_options_for_level(
                geo_level,
                *geography_option_sources,
                config=self.config,
            )
            for geo_level in geo_opts
        }
        return {
            "mode": "ready",
            "geo_opts": geo_opts,
            "geography_opts_by_level": geography_opts_by_level,
            "internal_external": internal_external or None,
            "external_workplace": external_workplace or None,
            "commuting_flows": commuting_flows or None,
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
            internal_external_table = self.get_filtered_view(
                "mandatory_internal_external",
                (geo_level, geography),
                factory=lambda: filter_selected_geography(
                    internal_external,
                    geo_level,
                    geography,
                ),
            )
            worker_views.append(
                data_table(internal_external_table, "Internal vs. External Workers")
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

        external_workplace_level_data = self.get_filtered_view(
            "mandatory_external_workplace_level",
            geo_level,
            factory=lambda: filter_geography_level(external_workplace, geo_level),
        )
        workplace_location_values = sorted(
            {
                str(value)
                for _, df in external_workplace_level_data
                for value in (
                    df["workplace_location"].cast(pl.Utf8).to_list()
                    if "workplace_location" in df.columns
                    else []
                )
            }
        )
        filtered_external_workplace = self.get_filtered_view(
            "mandatory_external_workplace",
            (geo_level, geography),
            factory=lambda: filter_geography(external_workplace_level_data, geography),
        )
        chart_data = filtered_external_workplace
        if self.as_percent:
            chart_data = self.get_filtered_view(
                "mandatory_external_workplace_percent",
                (geo_level, geography),
                factory=lambda: external_workplace_percent_data(
                    filtered_external_workplace,
                    geo_level,
                ),
            )

        return bar_chart(
            chart_data,
            x_col="workplace_location",
            y_col=(
                "external_worker_percent"
                if self.as_percent and geo_level == "all_geographies"
                else "person_count"
            ),
            title="External Worker Workplace Location",
            xaxis_title="Workplace Location",
            yaxis_title=(
                "Workers with External Workplaces (%)"
                if self.as_percent and geo_level == "all_geographies"
                else "External Workers"
            ),
            pct_col="pct",
            as_percent=False if geo_level == "all_geographies" else self.as_percent,
            xaxis_categoryarray=workplace_location_values,
        )

    def render_commuting_flows_section(self) -> SectionContent:
        """Render origin-to-destination commuting flow tables."""
        if self._current_data["mode"] != "ready":
            return []

        geo_level, geography = self._selected_geography()
        commuting_flows = self._current_data["commuting_flows"]
        if commuting_flows is None:
            return [
                self.data_not_available_card(
                    detail="The commuting flows summary is unavailable.",
                    missing_items=["commuting_flows"],
                )
            ]

        commuting_table = self.get_filtered_view(
            "mandatory_commuting_flows",
            (geo_level, geography),
            factory=lambda: filter_origin_geography(
                filter_geography_level(commuting_flows, geo_level),
                geography,
            ),
        )
        return [data_table(commuting_table, "Commuting Flows")]

    def render_distance_distribution_section(self) -> SectionContent:
        """Render the three mandatory distance distributions side by side."""
        if self._current_data["mode"] != "ready":
            return []

        geo_level, geography = self._selected_geography()
        return [
            pn.pane.Markdown("### Mandatory Location Distance"),
            pn.Row(
                self.render_distance_distribution_chart(
                    geo_level,
                    geography,
                    summary_data=self._current_data["work_distance"],
                    cache_key="mandatory_work_distance_distribution",
                    title="Workplace Location Distance Distribution",
                    yaxis_title="Workplace Locations",
                    summary_id="work_location_distance_distribution_by_geography",
                ),
                self.render_distance_distribution_chart(
                    geo_level,
                    geography,
                    summary_data=self._current_data["school_distance"],
                    cache_key="mandatory_school_distance_distribution",
                    title="School Location Distance Distribution",
                    yaxis_title="School Locations",
                    summary_id="school_location_distance_distribution_by_geography",
                ),
                self.render_distance_distribution_chart(
                    geo_level,
                    geography,
                    summary_data=self._current_data["university_distance"],
                    cache_key="mandatory_university_distance_distribution",
                    title="University Location Distance Distribution",
                    yaxis_title="University Locations",
                    summary_id="university_location_distance_distribution_by_geography",
                ),
                sizing_mode="stretch_width",
            ),
        ]

    def render_distance_distribution_chart(
        self,
        geo_level: str,
        geography: str,
        *,
        summary_data: list[tuple[str, pl.DataFrame]] | None,
        cache_key: str,
        title: str,
        yaxis_title: str,
        summary_id: str,
    ) -> pn.viewable.Viewable:
        """Render one distance-distribution chart or a targeted unavailable card."""
        if summary_data is None:
            return self.data_not_available_card(
                detail="The selected distance distribution summary is unavailable.",
                missing_items=[summary_id],
            )

        filtered_summary = self.get_filtered_view(
            cache_key,
            (geo_level, geography),
            factory=lambda: filter_selected_geography(
                summary_data,
                geo_level,
                geography,
            ),
        )
        distance_data = self.get_filtered_view(
            f"{cache_key}_chart",
            (geo_level, geography),
            factory=lambda: distance_distribution_chart_data(filtered_summary),
        )
        if not any(not df.is_empty() for _, df in distance_data):
            return self.data_not_available_card(
                detail=(
                    f"No distance distribution data is available for geography "
                    f"`{geography}` at level `{geo_level}`."
                ),
                missing_items=[summary_id],
            )

        return density_chart(
            distance_data,
            x_col="distance_bin",
            y_col="person_count",
            title=title,
            xaxis_title="Distance (miles)",
            yaxis_title=yaxis_title,
            normalize=False,
            as_percent=self.as_percent,
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

        wfh_data = self.get_filtered_view(
            "mandatory_wfh",
            (geo_level, geography),
            factory=lambda: work_from_home_chart_data(
                work_from_home,
                geo_level,
                geography,
            ),
        )
        return bar_chart(
            wfh_data,
            x_col="geography_label",
            y_col=(
                "work_from_home_percent"
                if self.as_percent
                else "work_from_home_worker_count"
            ),
            title=(
                "Work From Home Rate by Geography"
                if self.as_percent
                else "Workers Working From Home by Geography"
            ),
            xaxis_title="Geography",
            yaxis_title=(
                "Workers Working From Home (%)"
                if self.as_percent
                else "Workers Working From Home"
            ),
            as_percent=False,
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

        telecommute_level_data = self.get_filtered_view(
            "mandatory_telecommute_level",
            geo_level,
            factory=lambda: filter_geography_level(telecommute, geo_level),
        )
        telecommute_values = selected_telecommute_values(
            telecommute_level_data,
            config=self.config,
        )
        filtered_telecommute = self.get_filtered_view(
            "mandatory_telecommute",
            (geo_level, geography),
            factory=lambda: filter_geography(telecommute_level_data, geography),
        )
        chart_data = self.get_filtered_view(
            "mandatory_telecommute_chart",
            (geo_level, geography),
            factory=lambda: telecommute_chart_data(
                filtered_telecommute,
                telecommute_values,
                config=self.config,
            ),
        )
        return bar_chart(
            chart_data,
            x_col="telecommute_frequency_label",
            y_col="person_count",
            title="Telecommute Rate",
            xaxis_title="Telecommute Frequency",
            yaxis_title="Workers Who Do Not Work From Home",
            as_percent=self.as_percent,
            xaxis_categoryarray=self.config.ordered_labels(
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

        comparison_df = self.get_filtered_view(
            "mandatory_distance_comparison_table",
            (geo_level, geography),
            factory=lambda: mandatory_distance_comparison_table(
                average_distance,
                geo_level,
                geography,
                config=self.config,
            ),
        )
        if comparison_df.is_empty():
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
                [("Comparison", comparison_df)],
                "Average Mandatory Tour Distance vs Base Run",
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="mandatory_location_choice",
    title="Mandatory Location Choice",
    group_id="long_term_choices",
    order=27,
    page_cls=MandatoryLocationChoicePage,
    required_summary_ids=(
        "internal_external_worker_by_geography",
        "external_worker_workplace_locations",
        "commuting_flows",
        "work_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        "work_from_home_rate_by_geography",
        "telecommute_frequency_distribution",
        "average_mandatory_tour_distance_by_purpose_and_geography",
    ),
)

MandatoryLocationChoicePage.definition = PAGE
