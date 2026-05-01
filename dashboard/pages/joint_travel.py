"""Joint travel page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, control_row, control_row_spacer, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def party_size_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "party_size" not in first_df.columns:
        return ["All"]

    vals = (
        first_df.select("party_size")
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return ["All"] + sorted(v for v in vals if v != "All")


def household_size_options(data_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or "household_size" not in first_df.columns:
        return ["All"]

    vals = (
        first_df.select("household_size")
        .drop_nulls()
        .unique()
        .to_series()
        .cast(pl.Utf8)
        .to_list()
    )
    return ["All"] + sorted(v for v in vals if v != "All")


def _ordered_composition(df: pl.DataFrame) -> pl.DataFrame:
    if len(df) == 0 or "tour_composition" not in df.columns:
        return df

    return (
        df.with_columns(
            pl.col("tour_composition")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .alias("tour_composition")
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
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(pl.col("party_size").cast(pl.Utf8))
        if party_size == "All":
            df = (
                df.group_by("tour_composition")
                .agg(joint_tour_count=pl.col("joint_tour_count").sum())
                .with_columns(pl.col("tour_composition").cast(pl.Utf8))
                .sort("tour_composition")
            )
        else:
            df = df.filter(pl.col("party_size") == party_size)
        out.append((label, _ordered_composition(df)))
    return out


def household_participation_data(
    data_list: list[tuple[str, pl.DataFrame]],
    household_size: str,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in _nonempty(data_list):
        df = df.with_columns(
            pl.col("household_size").cast(pl.Utf8),
            pl.col("jtf").cast(pl.Utf8),
        )

        if household_size == "All":
            df = (
                df.group_by("jtf")
                .agg(household_percent=pl.col("household_percent").mean())
                .with_columns(pl.col("jtf").cast(pl.Utf8))
                .sort("jtf")
            )
        else:
            df = df.filter(pl.col("household_size") == household_size)

        out.append((label, df))
    return out


class JointTravelPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Joint Travel", state, config)

        party_opts = self._party_size_options()
        self.party_size_sel = pn.widgets.Select(
            name="Party Size",
            options=party_opts,
            value=party_opts[0],
        )
        self._watch_widget(self.party_size_sel)

        hh_opts = self._household_size_options()
        self.hhsize_sel = pn.widgets.Select(
            name="Household Size",
            options=hh_opts,
            value=hh_opts[0],
        )
        self._watch_widget(self.hhsize_sel)

        self._frequency_section = self.new_section()
        self._joint_tour_detail_section = self.new_section()
        self._participation_section = self.new_section()

        self.view = self.new_section(
            pn.pane.Markdown("## Joint Travel"),
            self._frequency_section,
            self._joint_tour_detail_section,
            self._participation_section,
        )

    def _party_size_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "joint_tour_composition_by_party_size", "weighted"
        )
        if data is None:
            return ["All"]
        return party_size_options(data)

    def _household_size_options(self) -> list[str]:
        data = self.state.get_summary_table_set(
            "household_jtp_by_household_size_and_jtf", "weighted"
        )
        if data is None:
            return ["All"]
        return household_size_options(data)

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._frequency_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._joint_tour_detail_section.objects = []
            self._participation_section.objects = []
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._frequency_section.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            self._joint_tour_detail_section.objects = []
            self._participation_section.objects = []
            return

        party_opts = party_size_options(
            summaries["joint_tour_composition_by_party_size"]
        )
        self.party_size_sel.options = party_opts
        if self.party_size_sel.value not in party_opts:
            self.party_size_sel.value = party_opts[0]
        party_size = self.party_size_sel.value

        hh_opts = household_size_options(
            summaries["household_jtp_by_household_size_and_jtf"]
        )
        self.hhsize_sel.options = hh_opts
        if self.hhsize_sel.value not in hh_opts:
            self.hhsize_sel.value = hh_opts[0]
        hhsize = self.hhsize_sel.value

        jtf_data = _nonempty(summaries["jtf_distribution"])

        joint_tours_hhsize_data = [
            (
                label,
                df.with_columns(pl.col("household_size").cast(pl.Utf8)),
            )
            for label, df in _nonempty(summaries["joint_tours_by_household_size"])
        ]

        party_size_data = [
            (
                label,
                df.with_columns(pl.col("party_size").cast(pl.Utf8)),
            )
            for label, df in _nonempty(summaries["joint_tour_party_size_distribution"])
        ]

        comp_party_data = self.get_filtered_view(
            "joint_tour_composition_by_party_size",
            party_size,
            factory=lambda: composition_by_party_size_data(
                summaries["joint_tour_composition_by_party_size"],
                party_size,
            ),
        )

        person_participation_data = [
            (
                label,
                df.with_columns(pl.col("household_size").cast(pl.Utf8)),
            )
            for label, df in _nonempty(summaries["person_jtp_by_household_size"])
        ]

        household_participation = self.get_filtered_view(
            "household_jtp_by_household_size_and_jtf",
            hhsize,
            factory=lambda: household_participation_data(
                summaries["household_jtp_by_household_size_and_jtf"],
                hhsize,
            ),
        )

        jtf_chart = bar_chart(
            jtf_data,
            x_col="jtf_label",
            y_col="household_count",
            title="Joint Tour Frequency by Joint Tour Pattern",
            xaxis_title="Joint Tour Pattern",
            yaxis_title="Households",
            height=450,
            as_percent=self.as_percent,
        )

        joint_tours_hhsize_chart = bar_chart(
            joint_tours_hhsize_data,
            x_col="household_size",
            y_col="joint_tour_count",
            title="Joint Tours by Household Size",
            xaxis_title="Household Size",
            yaxis_title="Joint Tours",
            as_percent=self.as_percent,
        )

        party_size_chart = bar_chart(
            party_size_data,
            x_col="party_size",
            y_col="joint_tour_count",
            title="Joint Tours by Party Size",
            xaxis_title="Party Size",
            yaxis_title="Joint Tours",
            as_percent=self.as_percent,
        )

        comp_party_chart = bar_chart(
            comp_party_data,
            x_col="tour_composition",
            y_col="joint_tour_count",
            title=f"Joint Tour Composition by Party Size - {party_size}",
            xaxis_title="Tour Composition",
            yaxis_title="Joint Tours",
            as_percent=self.as_percent,
        )

        person_participation_chart = bar_chart(
            person_participation_data,
            x_col="household_size",
            y_col="person_percent",
            title="People Taking Part in a Joint Tour by Household Size",
            xaxis_title="Household Size",
            yaxis_title="% Persons",
            as_percent=False,
        )

        household_participation_chart = bar_chart(
            household_participation,
            x_col="jtf",
            y_col="household_percent",
            title=f"Households Taking Part in a Joint Tour - {hhsize}",
            xaxis_title="Joint Tour Count",
            yaxis_title="% Households",
            as_percent=False,
        )

        self._frequency_section.objects = [
            pn.pane.Markdown("### Joint Tour Frequency"),
            jtf_chart,
        ]

        self._joint_tour_detail_section.objects = [
            pn.pane.Markdown("### Joint Tour Characteristics"),
            pn.Column(
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(control_row_spacer()),
                    pn.Column(
                        control_row(
                            pn.pane.Markdown("**Party Size:**"),
                            self.party_size_sel,
                        )
                    ),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    joint_tours_hhsize_chart,
                    party_size_chart,
                    comp_party_chart,
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
        ]

        self._participation_section.objects = [
            pn.pane.Markdown("### Joint Tour Participation"),
            pn.Column(
                pn.Row(
                    pn.Column(control_row_spacer()),
                    pn.Column(
                        control_row(
                            pn.pane.Markdown("**Household Size:**"),
                            self.hhsize_sel,
                        )
                    ),
                    sizing_mode="stretch_width",
                ),
                pn.Row(
                    person_participation_chart,
                    household_participation_chart,
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
    selectors=(
        PageSelectorDefinition(
            selector_id="party_size",
            widget_attr="party_size_sel",
            label="Party Size",
        ),
        PageSelectorDefinition(
            selector_id="household_size",
            widget_attr="hhsize_sel",
            label="Household Size",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="joint_travel_detail",
            view_attr="_joint_tour_detail_section",
            selector_ids=("party_size",),
        ),
        PageExportRegionDefinition(
            region_id="joint_travel_participation",
            view_attr="_participation_section",
            selector_ids=("household_size",),
        ),
    ),
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

