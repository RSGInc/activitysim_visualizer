"""Joint tours page: JTF, composition, party size, by HH size."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from summarize.reader import Config


class JointToursPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Joint Tours", state, config)
        self.hhsize_sel = pn.widgets.Select(
            name="HH Size", options=["Total", "2", "3", "4", "5"], value="Total"
        )
        self._watch_widget(self.hhsize_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Joint Tours"),
            pn.Row(pn.pane.Markdown("**HH Size:**"), self.hhsize_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        jtf_list = summaries["joint_tour_freq"]

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
            for label, df in summaries["joint_composition"]
        ]
        party_list = [
            (
                label,
                df.with_columns(pl.col("NUMBER_HH").cast(pl.Utf8)),
            )
            for label, df in summaries["joint_party_size"]
        ]
        hhsize_list = summaries["joint_tours_hhsize"]

        def _ordered_presence(df: pl.DataFrame) -> pl.DataFrame:
            base = pl.DataFrame({"jointTours": ["0", "1", "2+"]})
            if len(df) == 0:
                return base.with_columns(pl.lit(0.0).alias("freq"))
            d = (
                df.with_columns(pl.col("jointTours").cast(pl.Utf8).alias("jointTours"))
                .group_by("jointTours")
                .agg(pl.col("freq").sum().alias("freq"))
            )
            return base.join(d, on="jointTours", how="left").with_columns(
                pl.col("freq").fill_null(0.0)
            )

        def _presence_for_hhsize(
            label: str, df: pl.DataFrame
        ) -> tuple[str, pl.DataFrame]:
            if hhsize == "Total":
                agg = _ordered_presence(df)
                total = float(agg["freq"].sum()) if len(agg) > 0 else 0.0
                if total > 0:
                    agg = agg.with_columns((pl.col("freq") / total * 100).alias("freq"))
                return (label, agg)
            return (
                label,
                _ordered_presence(df.filter(pl.col("hhsize").cast(pl.Utf8) == hhsize)),
            )

        hhsize = self.hhsize_sel.value
        hhsize_data = self.get_filtered_view(
            "joint_tours_hhsize",
            hhsize,
            factory=lambda: [
                _presence_for_hhsize(label, df) for label, df in hhsize_list
            ],
        )

        self._body.objects = [
            bar_chart(
                jtf_list,
                x_col="alt_name",
                y_col="freq",
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
                    y_col="freq",
                    title="Joint Tour Composition",
                    xaxis_title="Composition",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    party_list,
                    x_col="NUMBER_HH",
                    y_col="freq",
                    title="Joint Tour Party Size",
                    xaxis_title="Party Size",
                    yaxis_title="Tours",
                    as_percent=self.as_percent,
                ),
            ),
            bar_chart(
                hhsize_data,
                "jointTours",
                "freq",
                f"Joint Tour Presence by HH Size ({hhsize})",
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
            label="HH Size",
        ),
    ),
    required_summary_ids=(
        "joint_tour_freq",
        "joint_composition",
        "joint_party_size",
        "joint_tours_hhsize",
    ),
)

JointToursPage.definition = PAGE
