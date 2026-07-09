"""Joint travel page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer, selector_row
from dashboard.helpers.category_helpers import (
    cap_numeric_category_data,
    capped_numeric_category_expr,
    complete_category_counts,
    label_category_data,
    numeric_like_sort_expr,
    nonempty,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


PARTY_SIZE_ALL_LABEL = "All Party Sizes"
HOUSEHOLD_SIZE_ALL_LABEL = "All"
JOINT_SIZE_VALUES = ["2", "3", "4", "5+"]


def party_size_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    if not nonempty(data_list):
        return [PARTY_SIZE_ALL_LABEL]
    return [PARTY_SIZE_ALL_LABEL, *JOINT_SIZE_VALUES]


def household_size_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    if not nonempty(data_list):
        return [HOUSEHOLD_SIZE_ALL_LABEL]
    return [HOUSEHOLD_SIZE_ALL_LABEL, *JOINT_SIZE_VALUES]


def joint_household_size_values(
    *data_lists: list[tuple[str, pl.DataFrame]],
) -> list[str]:
    """Return the capped household-size axis used by joint-travel charts."""
    if any(nonempty(data_list) for data_list in data_lists):
        return JOINT_SIZE_VALUES.copy()
    return []


def complete_joint_household_size_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    value_col: str,
    household_size_values: list[str],
) -> list[tuple[str, pl.DataFrame]]:
    """Complete household-size categories so joint-travel charts show every bin."""
    normalized = [
        (
            label,
            cap_numeric_category_data(
                [(label, df.filter(pl.col("household_size").cast(pl.Int64, strict=False) >= 2))],
                category_col="household_size",
                cap_value=5,
                value_cols=(value_col,),
            )[0][1].select("household_size", value_col),
        )
        for label, df in nonempty(data_list)
    ]
    return complete_category_counts(
        normalized,
        category_col="household_size",
        category_values=household_size_values,
        value_cols=(value_col,),
    )


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
        filtered = df.with_columns(capped_numeric_category_expr("party_size", 5))
        if party_size == PARTY_SIZE_ALL_LABEL:
            filtered = (
                filtered.group_by("tour_composition")
                .agg(joint_tour_count=pl.col("joint_tour_count").sum())
                .with_columns(pl.col("tour_composition").cast(pl.Utf8))
                .sort("tour_composition")
            )
        else:
            filtered = (
                filtered.filter(pl.col("party_size") == party_size)
                .group_by("tour_composition")
                .agg(joint_tour_count=pl.col("joint_tour_count").sum())
                .with_columns(pl.col("tour_composition").cast(pl.Utf8))
                .sort("tour_composition")
            )
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
            capped_numeric_category_expr("household_size", 5),
            pl.col("jtf").cast(pl.Utf8),
        )
        if household_size == HOUSEHOLD_SIZE_ALL_LABEL:
            filtered = (
                filtered.group_by("jtf")
                .agg(household_percent=pl.col("household_percent").mean())
                .with_columns(pl.col("jtf").cast(pl.Utf8))
                .sort("jtf")
            )
        else:
            filtered = (
                filtered.filter(pl.col("household_size") == household_size)
                .group_by("jtf")
                .agg(household_percent=pl.col("household_percent").mean())
                .with_columns(pl.col("jtf").cast(pl.Utf8))
                .sort("jtf")
            )
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
        base = df.with_columns(capped_numeric_category_expr("household_size", 5))
        base = (
            base.group_by("household_size")
            .agg(
                pl.col("joint_tour_person_count").sum(),
                pl.col("total_person_count").sum(),
            )
            .sort(numeric_like_sort_expr("household_size"))
        )
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


def joint_tour_frequency_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    hide_no_joint_tours: bool,
) -> list[tuple[str, pl.DataFrame]]:
    """Return joint-tour frequency rows, optionally excluding the no-tour bucket."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(pl.col("jtf_label").cast(pl.Utf8))
        if hide_no_joint_tours:
            filtered = filtered.filter(
                pl.col("jtf_label").str.strip_chars().str.to_lowercase()
                != "no joint tours"
            )
        out.append((label, filtered))
    return out


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
        party_size_data = [
            (
                label,
                cap_numeric_category_data(
                    [(label, df)],
                    category_col="party_size",
                    cap_value=5,
                    value_cols=("joint_tour_count",),
                )[0][1],
            )
            for label, df in nonempty(summaries["joint_tour_party_size_distribution"])
        ]
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
