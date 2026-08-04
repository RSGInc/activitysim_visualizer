"""Joint travel page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import control_row, control_row_spacer, selector_row
from dashboard.helpers.category_helpers import (
    label_category_data,
    nonempty,
)
from dashboard import DashboardPage, dashboard_page
from dashboard.pages._joint_travel_data import (
    JOINT_SIZE_VALUES,
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
        self.hide_no_joint_tours = self.selector(
            "hide_no_joint_tours",
            widget=pn.widgets.Checkbox(name='Hide "No Joint Tours"', value=False),
            label='Hide "No Joint Tours"',
        )
        self.party_size_sel = self.select(
            "party_size",
            "Party Size",
            options=self._party_size_options,
        )
        self.hhsize_sel = self.select(
            "household_size",
            "Household Size",
            options=self._household_size_options,
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
            pn.pane.Markdown("### Joint Tour Frequency"),
            self._frequency_section,
            pn.pane.Markdown("### Joint Tour Characteristics"),
            self._joint_tour_detail_section,
            pn.pane.Markdown("### Joint Tour Participation"),
            self._participation_section,
        )

    def _party_size_options(self) -> list[str]:
        data = self.data.summary(
            "joint_tour_composition_by_party_size",
            self.weighting_key,
        )
        return party_size_options(data) if data else ["All"]

    def _household_size_options(self) -> list[str]:
        data = self.data.summary(
            "household_jtp_by_household_size_and_jtf",
            self.weighting_key,
        )
        return household_size_options(data) if data else ["All"]

    def _summaries(self):
        return self.data.summaries(*self.required_summary_ids)

    def _values_for_column(
        self,
        data_list: list[tuple[str, pl.DataFrame]],
        column: str,
    ) -> list[str]:
        return sorted(
            {
                str(value)
                for _, df in data_list
                for value in (
                    df[column].cast(pl.Utf8).to_list() if column in df.columns else []
                )
            }
        )

    def render_frequency(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        summaries = self._summaries()
        if not summaries["jtf_distribution"]:
            return [
                self.summary_only_unavailable_card(
                    summary_ids=("jtf_distribution",),
                )
            ]
        return [
            selector_row(self.hide_no_joint_tours, height=48),
            self.noted_view(
                "joint_travel.frequency",
                self.render_joint_tour_frequency_chart(summaries["jtf_distribution"]),
            ),
        ]

    def render_joint_tour_detail(self):
        summaries = self._summaries()
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
                for value in (
                    df["tour_composition"].cast(pl.Utf8).to_list()
                    if "tour_composition" in df.columns
                    else []
                )
            ],
        )
        comp_party_data = self.query(
            lambda: composition_by_party_size_data(
                summaries["joint_tour_composition_by_party_size"], party_size
            )
        )
        household_size_view = (
            self.render_household_size_chart(
                complete_joint_household_size_data(
                    joint_tours_hhsize_data,
                    value_col="joint_tour_hh_count",
                    household_size_values=household_size_values,
                ),
                household_size_values,
            )
            if summaries["joint_tours_by_household_size"]
            else self.summary_only_unavailable_card(
                summary_ids=("joint_tours_by_household_size",),
            )
        )
        party_size_view = (
            self.render_party_size_chart(party_size_data, party_size_values)
            if summaries["joint_tour_party_size_distribution"]
            else self.summary_only_unavailable_card(
                summary_ids=("joint_tour_party_size_distribution",),
            )
        )
        composition_view = (
            self.render_composition_chart(
                comp_party_data,
                composition_label_values,
                party_size,
            )
            if summaries["joint_tour_composition_by_party_size"]
            else self.summary_only_unavailable_card(
                summary_ids=("joint_tour_composition_by_party_size",),
            )
        )
        return [
            pn.Column(
                selector_row(self.party_size_sel),
                pn.Row(
                    self.noted_view(
                        "joint_travel.household_size",
                        household_size_view,
                    ),
                    self.noted_view(
                        "joint_travel.party_size",
                        party_size_view,
                    ),
                    self.noted_view(
                        "joint_travel.composition",
                        composition_view,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]

    def render_participation(self):
        summaries = self._summaries()
        hhsize = self.hhsize_sel.value
        person_participation = self.query(
            lambda: person_participation_data(
                summaries["person_jtp_by_household_size"],
                as_percent=self.as_percent,
            )
        )
        household_participation = self.query(
            lambda: household_participation_data(
                summaries["household_jtp_by_household_size_and_jtf"], hhsize
            )
        )
        household_size_values = joint_household_size_values(
            person_participation,
            summaries["joint_tours_by_household_size"],
        )
        jtf_values = self.config.ordered_labels(
            "jtf",
            [
                str(value)
                for _, df in nonempty(
                    summaries["household_jtp_by_household_size_and_jtf"]
                )
                for value in (
                    df["jtf"].cast(pl.Utf8).to_list() if "jtf" in df.columns else []
                )
            ],
        )
        person_view = (
            self.render_person_participation_chart(
                complete_joint_household_size_data(
                    person_participation,
                    value_col="person_value",
                    household_size_values=household_size_values,
                ),
                household_size_values,
            )
            if summaries["person_jtp_by_household_size"]
            else self.summary_only_unavailable_card(
                summary_ids=("person_jtp_by_household_size",),
            )
        )
        household_view = (
            self.render_household_participation_chart(
                household_participation,
                jtf_values,
                hhsize,
            )
            if any(not df.is_empty() for _, df in household_participation)
            else self.summary_only_unavailable_card(
                summary_ids=("household_jtp_by_household_size_and_jtf",),
                detail=(
                    "The household joint-tour participation summary has no data "
                    f"for household size `{hhsize}`."
                ),
            )
        )
        return [
            pn.Column(
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(control_row(self.hhsize_sel)),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    self.noted_view(
                        "joint_travel.person_participation",
                        person_view,
                    ),
                    self.noted_view(
                        "joint_travel.household_participation",
                        household_view,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]

    def render_joint_tour_frequency_chart(self, summary_data):
        """Render joint tour frequency by joint tour pattern."""
        frequency_data = self.query(
            lambda: joint_tour_frequency_data(
                summary_data,
                hide_no_joint_tours=bool(self.hide_no_joint_tours.value),
            )
        )
        return self.plot.bar(
            frequency_data,
            x="jtf_label",
            y="household_count",
            title="Joint Tour Frequency by Joint Tour Pattern",
            x_title="Joint Tour Pattern",
            y_title="Households",
            height=450,
            share_y="household_count_percent",
        )

    def render_household_size_chart(
        self, summary_data, household_size_values: list[str]
    ):
        """Render joint tours by household size."""
        return self.plot.bar(
            summary_data,
            x="household_size",
            y="joint_tour_hh_count",
            title="Joint Tours by Household Size",
            x_title="Household Size",
            y_title="Households with a Joint Tour",
            category_order=household_size_values,
        )

    def render_party_size_chart(self, summary_data, party_size_values: list[str]):
        """Render joint tours by party size."""
        return self.plot.bar(
            summary_data,
            x="party_size",
            y="joint_tour_count",
            title="Joint Tours by Party Size",
            x_title="Party Size",
            y_title="Joint Tours",
            category_order=party_size_values,
        )

    def render_composition_chart(
        self,
        summary_data,
        composition_label_values: list[str],
        party_size: str,
    ):
        """Render joint tour composition for one selected party size."""
        return self.plot.bar(
            label_category_data(
                summary_data,
                source_col="tour_composition",
                category_id="tour_composition",
                config=self.config,
                target_col="tour_composition_label",
            ),
            x="tour_composition_label",
            y="joint_tour_count",
            title=f"Joint Tour Composition by Party Size - {party_size}",
            x_title="Tour Composition",
            y_title="Joint Tours",
            category_order=composition_label_values,
        )

    def render_person_participation_chart(
        self,
        summary_data,
        household_size_values: list[str],
    ):
        """Render people participating in joint travel by household size."""
        return self.plot.bar(
            summary_data,
            x="household_size",
            y="person_value",
            title="People Taking Part in a Joint Tour by Household Size",
            x_title="Household Size",
            y_title=(
                "Percent of People (%)"
                if self.as_percent
                else "People Taking Joint Tours"
            ),
            value_mode="count",
            category_order=household_size_values,
        )

    def render_household_participation_chart(
        self,
        summary_data,
        jtf_values: list[str],
        household_size: str,
    ):
        """Render household participation in joint tours for one household size."""
        return self.plot.bar(
            label_category_data(
                summary_data,
                source_col="jtf",
                category_id="jtf",
                config=self.config,
                target_col="jtf_label",
            ),
            x="jtf_label",
            y="household_percent",
            title=f"Households Taking Part in a Joint Tour - {household_size}",
            x_title="Joint Tour Count",
            y_title="Percent of Households (%)",
            value_mode="count",
            category_order=jtf_values,
        )
