"""Joint tours page: JTF, composition, party size, by HH size."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from runtime.config import Config


class JointToursPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Joint Tours", state, config)
        self.hhsize_sel = pn.widgets.Select(
            name="Household Size", options=["Total", "2", "3", "4", "5"], value="Total"
        )
        self._watch_widget(self.hhsize_sel)
        self._summary_section = self.new_section()
        self._presence_section = self.new_section()
        self.view = self.new_section(
            pn.pane.Markdown("## Joint Tours"),
            self._summary_section,
            self._presence_section,
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._summary_section.objects = [pn.pane.Markdown("No runs loaded.")]
            self._presence_section.objects = []
            return

        summary_result = self.resolve_summary_visualization(
            "joint_tours_summary",
            summary_requirements={
                "jtf_distribution": ("jtf_label", "household_count"),
                "joint_tour_composition_distribution": (
                    "tour_composition",
                    "joint_tour_count",
                ),
                "joint_tour_party_size_distribution": (
                    "party_size",
                    "joint_tour_count",
                ),
                "household_jtp_by_household_size_and_jtf": (
                    "household_size",
                    "jtf",
                    "household_percent",
                ),
            },
        )
        if not summary_result.has_usable_runs:
            self._summary_section.objects = [
                self.unavailable_visualization(
                    summary_result,
                    detail="Joint-tour summaries are unavailable.",
                )
            ]
            self._presence_section.objects = []
            return

        jtf_list = summary_result.usable_by_input["jtf_distribution"]

        def _ordered_comp(df: pl.DataFrame) -> pl.DataFrame:
            if len(df) == 0:
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

        comp_list = [
            (label, _ordered_comp(df))
            for label, df in summary_result.usable_by_input[
                "joint_tour_composition_distribution"
            ]
        ]
        party_list = [
            (
                label,
                df.with_columns(pl.col("party_size").cast(pl.Utf8)),
            )
            for label, df in summary_result.usable_by_input[
                "joint_tour_party_size_distribution"
            ]
        ]
        hhsize_list = summary_result.usable_by_input[
            "household_jtp_by_household_size_and_jtf"
        ]

        def _ordered_presence(df: pl.DataFrame) -> pl.DataFrame:
            base = pl.DataFrame({"jtf": ["0", "1", "2+"]})
            if len(df) == 0:
                return base.with_columns(pl.lit(0.0).alias("household_percent"))
            d = (
                df.with_columns(pl.col("jtf").cast(pl.Utf8).alias("jtf"))
                .group_by("jtf")
                .agg(pl.col("household_percent").sum().alias("household_percent"))
            )
            return base.join(d, on="jtf", how="left").with_columns(
                pl.col("household_percent").fill_null(0.0)
            )

        def _presence_for_hhsize(
            label: str, df: pl.DataFrame
        ) -> tuple[str, pl.DataFrame]:
            if hhsize == "Total":
                agg = _ordered_presence(df)
                total = float(agg["household_percent"].sum()) if len(agg) > 0 else 0.0
                if total > 0:
                    agg = agg.with_columns(
                        (pl.col("household_percent") / total * 100).alias(
                            "household_percent"
                        )
                    )
                return (label, agg)
            return (
                label,
                _ordered_presence(
                    df.filter(pl.col("household_size").cast(pl.Utf8) == hhsize)
                ),
            )

        hhsize = self.hhsize_sel.value
        hhsize_data = self.get_filtered_view(
            "household_jtp_by_household_size_and_jtf",
            hhsize,
            factory=lambda: [
                _presence_for_hhsize(label, df) for label, df in hhsize_list
            ],
        )

        self._summary_section.objects = [
            bar_chart(
                jtf_list,
                x_col="jtf_label",
                y_col="household_count",
                title="Joint Tour Frequency (21 alternatives)",
                xaxis_title="Alternative",
                yaxis_title="Households",
                height=450,
                as_percent=self.as_percent,
            ),
            pn.Row(
                bar_chart(
                    comp_list,
                    x_col="tour_composition",
                    y_col="joint_tour_count",
                    title="Joint Tour Composition",
                    xaxis_title="Composition",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    party_list,
                    x_col="party_size",
                    y_col="joint_tour_count",
                    title="Joint Tour Party Size",
                    xaxis_title="Party Size",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                ),
            ),
        ]
        self._presence_section.objects = [
            pn.pane.Markdown(
                "### Percentage of Households Taking Part in a Joint Tour"
            ),
            pn.Row(pn.pane.Markdown("**Household Size:**"), self.hhsize_sel),
            bar_chart(
                hhsize_data,
                "jtf",
                "household_percent",
                f"Household Size: {hhsize}",
                "Joint Tours",
                "% HH",
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="joint_tours",
    title="Joint Tours",
    order=40,
    controller_cls=JointToursPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="hh_size",
            widget_attr="hhsize_sel",
            label="Household Size",
        ),
    ),
    export_regions=(
        PageExportRegionDefinition(
            region_id="joint_tours_presence",
            view_attr="_presence_section",
            selector_ids=("hh_size",),
        ),
    ),
    required_summary_ids=(
        "jtf_distribution",
        "joint_tour_composition_distribution",
        "joint_tour_party_size_distribution",
        "household_jtp_by_household_size_and_jtf",
    ),
)

JointToursPage.definition = PAGE
