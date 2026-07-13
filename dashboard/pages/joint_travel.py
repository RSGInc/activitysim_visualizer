"""Joint travel page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer, selector_row
from dashboard.helpers.category_helpers import (
    complete_category_counts,
    label_category_data,
    nonempty,
)
from dashboard import DashboardPage, dashboard_page
from dashboard.pages._joint_travel_data import (
    HOUSEHOLD_SIZE_ALL_LABEL,
    JOINT_SIZE_VALUES,
    PARTY_SIZE_ALL_LABEL,
    complete_joint_household_size_data,
    composition_by_party_size_data,
    household_participation_data,
    household_size_options,
    joint_household_size_values,
    joint_party_size_data,
    joint_tour_frequency_data,
    party_size_options,
    person_participation_data,
)


@dashboard_page(
    page_id="joint_travel",
    title="Joint Travel",
    order=40,
    required_summary_ids=(
        "jtf_distribution",
        "joint_tours_by_household_size",
        "joint_tour_party_size_distribution",
        "joint_tour_composition_by_party_size",
        "person_jtp_by_household_size",
        "household_jtp_by_household_size_and_jtf",
    ),
)
class JointTravelPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        party_opts = self._party_size_options()
        hh_opts = self._household_size_options()
        self.hide_no_joint_tours = self.selector(
            "hide_no_joint_tours",
            widget=pn.widgets.Checkbox(name='Hide "No Joint Tours"', value=False),
            label='Hide "No Joint Tours"',
        )
        self.party_size_sel = self.selector(
            "party_size",
            widget=pn.widgets.Select(
                name="Party Size",
                options=party_opts,
                value=party_opts[0],
            ),
            label="Party Size",
        )
        self.hhsize_sel = self.selector(
            "household_size",
            widget=pn.widgets.Select(
                name="Household Size",
                options=hh_opts,
                value=hh_opts[0],
            ),
            label="Household Size",
        )
        self._frequency_section = self.section(
            "joint_travel_frequency",
            selectors=("hide_no_joint_tours",),
            render=self.render_frequency,
        )
        self._joint_tour_detail_section = self.section(
            "joint_travel_detail",
            selectors=("party_size",),
            render=self.render_joint_tour_detail,
        )
        self._participation_section = self.section(
            "joint_travel_participation",
            selectors=("household_size",),
            render=self.render_participation,
        )
        return self.new_section(
            pn.pane.Markdown("## Joint Travel"),
            self._frequency_section,
            self._joint_tour_detail_section,
            self._participation_section,
        )

    def _party_size_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "joint_tour_composition_by_party_size",
            "weighted",
        )
        return party_size_options(data) if data is not None else ["All"]

    def _household_size_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "household_jtp_by_household_size_and_jtf",
            "weighted",
        )
        return household_size_options(data) if data is not None else ["All"]

    def sync_controls(self) -> None:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return
        party_opts = party_size_options(summaries["joint_tour_composition_by_party_size"])
        hh_opts = household_size_options(summaries["household_jtp_by_household_size_and_jtf"])
        self.party_size_sel.options = party_opts
        if self.party_size_sel.value not in party_opts:
            self.party_size_sel.value = party_opts[0]
        self.hhsize_sel.options = hh_opts
        if self.hhsize_sel.value not in hh_opts:
            self.hhsize_sel.value = hh_opts[0]

    def _summaries(self):
        return self.require_summaries(*self.required_summary_ids)

    def _values_for_column(
        self,
        data_list: list[tuple[str, pl.DataFrame]],
        column: str,
    ) -> list[str]:
        return sorted(
            {
                str(value)
                for _, df in data_list
                for value in (df[column].cast(pl.Utf8).to_list() if column in df.columns else [])
            }
        )

    def render_frequency(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self._summaries()
        if summaries is None:
            return [self.summary_only_unavailable_card()]
        return [
            pn.pane.Markdown("### Joint Tour Frequency"),
            selector_row(self.hide_no_joint_tours, height=48),
            self.render_joint_tour_frequency_chart(summaries["jtf_distribution"]),
        ]

    def render_joint_tour_detail(self):
        summaries = self._summaries()
        if summaries is None:
            return []
        party_size = self.party_size_sel.value
        joint_tours_hhsize_data = [
            (label, df.with_columns(pl.col("household_size").cast(pl.Utf8)))
            for label, df in nonempty(summaries["joint_tours_by_household_size"])
        ]
        party_size_data = joint_party_size_data(
            summaries["joint_tour_party_size_distribution"]
        )
        household_size_values = joint_household_size_values(
            joint_tours_hhsize_data,
            summaries["person_jtp_by_household_size"],
        )
        party_size_values = JOINT_SIZE_VALUES.copy()
        composition_label_values = self.config.ordered_labels(
            "tour_composition",
            [
                str(value)
                for _, df in nonempty(summaries["joint_tour_composition_by_party_size"])
                for value in (df["tour_composition"].cast(pl.Utf8).to_list() if "tour_composition" in df.columns else [])
            ],
        )
        comp_party_data = self.get_filtered_view(
            "joint_tour_composition_by_party_size",
            party_size,
            factory=lambda: composition_by_party_size_data(
                summaries["joint_tour_composition_by_party_size"], party_size
            ),
        )
        return [
            pn.pane.Markdown("### Joint Tour Characteristics"),
            pn.Column(
                selector_row(self.party_size_sel),
                pn.Row(
                    self.render_household_size_chart(
                        complete_joint_household_size_data(
                            joint_tours_hhsize_data,
                            value_col="joint_tour_hh_count",
                            household_size_values=household_size_values,
                        ),
                        household_size_values,
                    ),
                    self.render_party_size_chart(
                        party_size_data,
                        party_size_values,
                    ),
                    self.render_composition_chart(
                        comp_party_data,
                        composition_label_values,
                        party_size,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]

    def render_participation(self):
        summaries = self._summaries()
        if summaries is None:
            return []
        hhsize = self.hhsize_sel.value
        person_participation = self.get_filtered_view(
            "person_jtp_by_household_size",
            self.as_percent,
            factory=lambda: person_participation_data(
                summaries["person_jtp_by_household_size"],
                as_percent=self.as_percent,
            ),
        )
        household_participation = self.get_filtered_view(
            "household_jtp_by_household_size_and_jtf",
            hhsize,
            factory=lambda: household_participation_data(
                summaries["household_jtp_by_household_size_and_jtf"], hhsize
            ),
        )
        household_size_values = joint_household_size_values(
            person_participation,
            summaries["joint_tours_by_household_size"],
        )
        jtf_values = self.config.ordered_labels(
            "jtf",
            [
                str(value)
                for _, df in nonempty(summaries["household_jtp_by_household_size_and_jtf"])
                for value in (df["jtf"].cast(pl.Utf8).to_list() if "jtf" in df.columns else [])
            ],
        )
        return [
            pn.pane.Markdown("### Joint Tour Participation"),
            pn.Column(
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(control_row(self.hhsize_sel)),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    self.render_person_participation_chart(
                        complete_joint_household_size_data(
                            person_participation,
                            value_col="person_value",
                            household_size_values=household_size_values,
                        ),
                        household_size_values,
                    ),
                    self.render_household_participation_chart(
                        household_participation,
                        jtf_values,
                        hhsize,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]

    def render_joint_tour_frequency_chart(self, summary_data):
        """Render joint tour frequency by joint tour pattern."""
        frequency_data = self.get_filtered_view(
            "joint_tour_frequency",
            bool(self.hide_no_joint_tours.value),
            factory=lambda: joint_tour_frequency_data(
                summary_data,
                hide_no_joint_tours=bool(self.hide_no_joint_tours.value),
            ),
        )
        return bar_chart(
            frequency_data,
            x_col="jtf_label",
            y_col="household_count",
            title="Joint Tour Frequency by Joint Tour Pattern",
            xaxis_title="Joint Tour Pattern",
            yaxis_title="Households",
            height=450,
            percent_y_col="household_count_percent",
            as_percent=self.as_percent,
        )

    def render_household_size_chart(self, summary_data, household_size_values: list[str]):
        """Render joint tours by household size."""
        return bar_chart(
            summary_data,
            "household_size",
            "joint_tour_hh_count",
            "Joint Tours by Household Size",
            "Household Size",
            yaxis_title="Households with a Joint Tour",
            as_percent=self.as_percent,
            xaxis_categoryarray=household_size_values,
        )

    def render_party_size_chart(self, summary_data, party_size_values: list[str]):
        """Render joint tours by party size."""
        return bar_chart(
            summary_data,
            "party_size",
            "joint_tour_count",
            "Joint Tours by Party Size",
            "Party Size",
            yaxis_title="Joint Tours",
            as_percent=self.as_percent,
            xaxis_categoryarray=party_size_values,
        )

    def render_composition_chart(
        self,
        summary_data,
        composition_label_values: list[str],
        party_size: str,
    ):
        """Render joint tour composition for one selected party size."""
        return bar_chart(
            label_category_data(
                summary_data,
                source_col="tour_composition",
                category_id="tour_composition",
                config=self.config,
                target_col="tour_composition_label",
            ),
            "tour_composition_label",
            "joint_tour_count",
            f"Joint Tour Composition by Party Size - {party_size}",
            "Tour Composition",
            yaxis_title="Joint Tours",
            as_percent=self.as_percent,
            xaxis_categoryarray=composition_label_values,
        )

    def render_person_participation_chart(
        self,
        summary_data,
        household_size_values: list[str],
    ):
        """Render people participating in joint travel by household size."""
        return bar_chart(
            summary_data,
            "household_size",
            "person_value",
            "People Taking Part in a Joint Tour by Household Size",
            "Household Size",
            yaxis_title=(
                "Percent of People (%)" if self.as_percent else "People Taking Joint Tours"
            ),
            as_percent=False,
            xaxis_categoryarray=household_size_values,
        )

    def render_household_participation_chart(
        self,
        summary_data,
        jtf_values: list[str],
        household_size: str,
    ):
        """Render household participation in joint tours for one household size."""
        return bar_chart(
            label_category_data(
                summary_data,
                source_col="jtf",
                category_id="jtf",
                config=self.config,
                target_col="jtf_label",
            ),
            "jtf_label",
            "household_percent",
            f"Households Taking Part in a Joint Tour - {household_size}",
            "Joint Tour Count",
            yaxis_title="Percent of Households (%)",
            as_percent=False,
            xaxis_categoryarray=jtf_values,
        )
