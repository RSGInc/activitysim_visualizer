"""Mandatory location choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


GEO_LEVEL_COL = "geography_level"
GEO_COL = "geography"


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def geo_level_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or GEO_LEVEL_COL not in first_df.columns:
        return ["Total"]

    vals = (
        first_df.select(GEO_LEVEL_COL)
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return sorted(vals) if vals else ["Total"]


def student_type_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "student_type" not in first_df.columns:
        return ["All"]

    vals = (
        first_df.select("student_type")
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return sorted(vals) if vals else ["All"]


def filter_geo_level(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        if GEO_LEVEL_COL in df.columns:
            df = df.with_columns(pl.col(GEO_LEVEL_COL).cast(pl.Utf8)).filter(
                pl.col(GEO_LEVEL_COL) == geo_level
            )
        out.append((label, df))
    return out


def school_location_table_data(
    data_list: list[tuple[str, pl.DataFrame]],
    geo_level: str,
    student_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in filter_geo_level(data_list, geo_level):
        if "student_type" in df.columns and student_type != "All":
            df = df.with_columns(pl.col("student_type").cast(pl.Utf8)).filter(
                pl.col("student_type") == student_type
            )
        out.append((label, df))
    return out


def distance_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (
            label,
            df.select(
                pl.col("distance_bin"),
                pl.col("person_count"),
            ).sort("distance_bin"),
        )
        for label, df in _nonempty(data_list)
    ]


class MandatoryLocationChoicePage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Mandatory Location Choice", state, config)

        geo_opts = self._geo_level_options()
        self.geo_level_sel = pn.widgets.Select(
            name="Geography Level",
            options=geo_opts,
            value=geo_opts[0],
        )
        self._watch_widget(self.geo_level_sel)

        student_opts = self._student_type_options()
        self.student_type_sel = pn.widgets.Select(
            name="Student Type",
            options=student_opts,
            value=student_opts[0],
        )
        self._watch_widget(self.student_type_sel)

        self.location_type_sel = pn.widgets.Select(
            name="Distance Location Type",
            options=["Workplace", "School", "University"],
            value="Workplace",
        )
        self._watch_widget(self.location_type_sel)

        self._worker_section = self.new_section()
        self._location_validation_section = self.new_section()
        self._flows_distance_section = self.new_section()
        self._remote_work_section = self.new_section()

        self.view = self.new_section(
            pn.pane.Markdown("## Mandatory Location Choice"),
            pn.Row(
                pn.pane.Markdown("**Geography Level:**"),
                self.geo_level_sel,
            ),
            self._worker_section,
            self._location_validation_section,
            self._flows_distance_section,
            self._remote_work_section,
        )

    def _geo_level_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "internal_external_worker_by_geography", "weighted"
        )
        if data is None:
            return ["Total"]
        return geo_level_options(data)

    def _student_type_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "school_location_enrollment_comparison", "weighted"
        )
        if data is None:
            return ["All"]
        return student_type_options(data)

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._worker_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._location_validation_section.objects = []
            self._flows_distance_section.objects = []
            self._remote_work_section.objects = []
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._worker_section.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            self._location_validation_section.objects = []
            self._flows_distance_section.objects = []
            self._remote_work_section.objects = []
            return

        geo_opts = geo_level_options(summaries["internal_external_worker_by_geography"])
        self.geo_level_sel.options = geo_opts
        if self.geo_level_sel.value not in geo_opts:
            self.geo_level_sel.value = geo_opts[0]
        geo_level = self.geo_level_sel.value

        student_opts = student_type_options(
            summaries["school_location_enrollment_comparison"]
        )
        self.student_type_sel.options = student_opts
        if self.student_type_sel.value not in student_opts:
            self.student_type_sel.value = student_opts[0]
        student_type = self.student_type_sel.value

        internal_external_table = self.get_filtered_view(
            "mandatory_internal_external",
            geo_level,
            factory=lambda: filter_geo_level(
                summaries["internal_external_worker_by_geography"], geo_level
            ),
        )

        workplace_lu_table = self.get_filtered_view(
            "mandatory_workplace_lu",
            geo_level,
            factory=lambda: filter_geo_level(
                summaries["workplace_location_employment_comparison"], geo_level
            ),
        )

        school_lu_table = self.get_filtered_view(
            "mandatory_school_lu",
            (geo_level, student_type),
            factory=lambda: school_location_table_data(
                summaries["school_location_enrollment_comparison"],
                geo_level,
                student_type,
            ),
        )

        commuting_flows_table = self.get_filtered_view(
            "mandatory_commuting_flows",
            geo_level,
            factory=lambda: filter_geo_level(summaries["commuting_flows"], geo_level),
        )

        wfh_data = self.get_filtered_view(
            "mandatory_wfh",
            geo_level,
            factory=lambda: filter_geo_level(
                summaries["work_from_home_rate_by_geography"], geo_level
            ),
        )

        external_workplace_data = _nonempty(
            summaries["external_worker_workplace_locations"]
        )

        telecommute_data = _nonempty(summaries["telecommute_frequency_distribution"])

        location_type = self.location_type_sel.value
        dist_summary_id = {
            "Workplace": "work_location_distance_distribution_by_geography",
            "School": "school_location_distance_distribution_by_geography",
            "University": "university_location_distance_distribution_by_geography",
        }[location_type]

        distance_data = self.get_filtered_view(
            "mandatory_distance_distribution",
            location_type,
            factory=lambda: distance_chart_data(summaries[dist_summary_id]),
        )

        external_workplace_chart = bar_chart(
            external_workplace_data,
            x_col="workplace_location",
            y_col="person_count",
            title="External Worker Workplace Location",
            xaxis_title="Workplace Location",
            yaxis_title="External Workers",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        distance_chart = density_chart(
            distance_data,
            x_col="distance_bin",
            y_col="person_count",
            title=f"{location_type} Location Distance Distribution",
            xaxis_title="Distance (miles)",
            normalize=False,
            as_percent=self.as_percent,
        )

        wfh_chart = bar_chart(
            wfh_data,
            x_col=GEO_COL,
            y_col="work_from_home_worker_count",
            title="Work From Home Rate by Geography",
            xaxis_title="Geography",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )

        telecommute_chart = bar_chart(
            telecommute_data,
            x_col="telecommute_frequency",
            y_col="person_count",
            title="Telecommute Rate",
            xaxis_title="Telecommute Frequency",
            yaxis_title="Workers",
            as_percent=self.as_percent,
        )

        self._worker_section.objects = [
            pn.pane.Markdown("### Worker Geography"),
            data_table(internal_external_table, "Internal vs. External Workers"),
            external_workplace_chart,
        ]

        self._location_validation_section.objects = [
            pn.pane.Markdown("### Location Choice Validation"),
            data_table(
                workplace_lu_table,
                "Workplace Location vs Land Use Employment",
            ),
            pn.Row(
                pn.pane.Markdown("**Student Type:**"),
                self.student_type_sel,
            ),
            data_table(
                school_lu_table,
                "School Location vs Land Use Enrollment",
            ),
        ]

        self._flows_distance_section.objects = [
            pn.pane.Markdown("### Commuting Flows and Location Distance"),
            pn.Row(
                data_table(commuting_flows_table, "Commuting Flows"),
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Distance Location Type:**"),
                        self.location_type_sel,
                    ),
                    distance_chart,
                ),
            ),
        ]

        self._remote_work_section.objects = [
            pn.pane.Markdown("### Remote Work"),
            pn.Row(wfh_chart, telecommute_chart),
        ]


PAGE = DashboardPageDefinition(
    page_id="mandatory_location_choice",
    title="Mandatory Location Choice",
    order=27,
    controller_cls=MandatoryLocationChoicePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="geography_level",
            widget_attr="geo_level_sel",
            label="Geography Level",
        ),
        PageSelectorDefinition(
            selector_id="student_type",
            widget_attr="student_type_sel",
            label="Student Type",
        ),
        PageSelectorDefinition(
            selector_id="distance_location_type",
            widget_attr="location_type_sel",
            label="Distance Location Type",
        ),
    ),
    required_summary_ids=(
        "internal_external_worker_by_geography",
        "external_worker_workplace_locations",
        "workplace_location_employment_comparison",
        "school_location_enrollment_comparison",
        "commuting_flows",
        "work_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        "work_from_home_rate_by_geography",
        "telecommute_frequency_distribution",
    ),
)

MandatoryLocationChoicePage.definition = PAGE
