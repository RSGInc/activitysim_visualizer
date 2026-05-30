"""Joint travel page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer
from dashboard.helpers.category_helpers import column_options, label_category_data, nonempty
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def party_size_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    opts, _ = column_options(
        data_list,
        "party_size",
        total_raw="All",
        total_label="All",
    )
    return opts or ["All"]


def household_size_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    opts, _ = column_options(
        data_list,
        "household_size",
        total_raw="All",
        total_label="All",
    )
    return opts or ["All"]


def ordered_composition(df: pl.DataFrame) -> pl.DataFrame:
    """Order composition categories as adults, mixed, then children."""
    if len(df) == 0 or "tour_composition" not in df.columns:
        return df
    return (
        df.with_columns(
            pl.col("tour_composition").cast(pl.Utf8).str.to_lowercase().alias("tour_composition")
        )
        .with_columns(
            pl.when(pl.col("tour_composition") == "adults")
            .then(0)
            .when(pl.col("tour_composition") == "mixed")
            .then(1)
            .when(pl.col("tour_composition") == "children")
            .then(2)
            .otherwise(99)
            .alias("_ord")
        )
        .sort("_ord")
        .drop("_ord")
    )


def composition_by_party_size_data(
    data_list: list[tuple[str, pl.DataFrame]],
    party_size: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter or aggregate joint-tour composition data by party size."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("party_size").cast(pl.Utf8))
        if party_size == "All":
            filtered = (
                filtered.group_by("tour_composition")
                .agg(joint_tour_count=pl.col("joint_tour_count").sum())
                .with_columns(pl.col("tour_composition").cast(pl.Utf8))
                .sort("tour_composition")
            )
        else:
            filtered = filtered.filter(pl.col("party_size") == party_size)
        out.append((label, ordered_composition(filtered)))
    return out


def household_participation_data(
    data_list: list[tuple[str, pl.DataFrame]],
    household_size: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter household participation rows to one household size or aggregate all sizes."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(
            pl.col("household_size").cast(pl.Utf8),
            pl.col("jtf").cast(pl.Utf8),
        )
        if household_size == "All":
            filtered = (
                filtered.group_by("jtf")
                .agg(household_percent=pl.col("household_percent").mean())
                .with_columns(pl.col("jtf").cast(pl.Utf8))
                .sort("jtf")
            )
        else:
            filtered = filtered.filter(pl.col("household_size") == household_size)
        out.append((label, filtered))
    return out


def person_participation_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    as_percent: bool,
) -> list[tuple[str, pl.DataFrame]]:
    """Return joint-tour person participation counts or rates by household size."""
    out = []
    for label, df in nonempty(data_list):
        base = df.with_columns(pl.col("household_size").cast(pl.Utf8))
        if as_percent:
            base = base.with_columns(
                pl.when(pl.col("total_person_count") > 0)
                .then(pl.col("joint_tour_person_count") / pl.col("total_person_count") * 100.0)
                .otherwise(0.0)
                .alias("person_value")
            )
        else:
            base = base.with_columns(pl.col("joint_tour_person_count").alias("person_value"))
        out.append((label, base))
    return out


class JointTravelPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        party_opts = self._party_size_options()
        hh_opts = self._household_size_options()
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
            bar_chart(
                nonempty(summaries["jtf_distribution"]),
                x_col="jtf_label",
                y_col="household_count",
                title="Joint Tour Frequency by Joint Tour Pattern",
                xaxis_title="Joint Tour Pattern",
                yaxis_title="Households",
                height=450,
                as_percent=self.as_percent,
            ),
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
        party_size_data = [
            (label, df.with_columns(pl.col("party_size").cast(pl.Utf8)))
            for label, df in nonempty(summaries["joint_tour_party_size_distribution"])
        ]
        household_size_values = self._values_for_column(joint_tours_hhsize_data, "household_size")
        party_size_values = self._values_for_column(party_size_data, "party_size")
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
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(control_row_spacer()),
                    pn.Column(
                        control_row(
                            pn.pane.Markdown("**Party Size:**"), self.party_size_sel
                        )
                    ),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    bar_chart(
                        joint_tours_hhsize_data,
                        "household_size",
                        "joint_tour_hh_count",
                        "Joint Tours by Household Size",
                        "Household Size",
                        yaxis_title="Households with a Joint Tour",
                        as_percent=self.as_percent,
                        xaxis_categoryarray=household_size_values,
                    ),
                    bar_chart(
                        party_size_data,
                        "party_size",
                        "joint_tour_count",
                        "Joint Tours by Party Size",
                        "Party Size",
                        yaxis_title="Joint Tours",
                        as_percent=self.as_percent,
                        xaxis_categoryarray=party_size_values,
                    ),
                    bar_chart(
                        label_category_data(
                            comp_party_data,
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
        household_size_values = self._values_for_column(person_participation, "household_size")
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
                    pn.Column(
                        control_row(
                            pn.pane.Markdown("**Household Size:**"), self.hhsize_sel
                        )
                    ),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    bar_chart(
                        person_participation,
                        "household_size",
                        "person_value",
                        "People Taking Part in a Joint Tour by Household Size",
                        "Household Size",
                        yaxis_title=(
                            "Percent of People (%)"
                            if self.as_percent
                            else "People Taking Joint Tours"
                        ),
                        as_percent=False,
                        xaxis_categoryarray=household_size_values,
                    ),
                    bar_chart(
                        label_category_data(
                            household_participation,
                            source_col="jtf",
                            category_id="jtf",
                            config=self.config,
                            target_col="jtf_label",
                        ),
                        "jtf_label",
                        "household_percent",
                        f"Households Taking Part in a Joint Tour - {hhsize}",
                        "Joint Tour Count",
                        yaxis_title="Percent of Households (%)",
                        as_percent=False,
                        xaxis_categoryarray=jtf_values,
                    ),
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="joint_travel",
    title="Joint Travel",
    order=40,
    page_cls=JointTravelPage,
    required_summary_ids=(
        "jtf_distribution",
        "joint_tours_by_household_size",
        "joint_tour_party_size_distribution",
        "joint_tour_composition_by_party_size",
        "person_jtp_by_household_size",
        "household_jtp_by_household_size_and_jtf",
    ),
)

JointTravelPage.definition = PAGE
