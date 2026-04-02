"""Joint tours page: JTF, composition, party size, by HH size."""

from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart
from summarize.reader import RunData, Config
from summarize import tours as tour_sums


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    jtf_list = [(l, tour_sums.joint_tour_freq(rd)) for l, rd in runs]
    comp_order = ["adults", "mixed", "children"]

    def _ordered_comp(df: pl.DataFrame) -> pl.DataFrame:
        if len(df) == 0:
            return df
        d = df.with_columns(
            pl.col("tour_composition")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .alias("tour_composition")
        )
        d = (
            d.with_columns(
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
        return d

    comp_list = [(l, _ordered_comp(tour_sums.joint_composition(rd))) for l, rd in runs]
    party_list = [
        (
            l,
            tour_sums.joint_party_size(rd).with_columns(
                pl.col("NUMBER_HH").cast(pl.Utf8)
            ),
        )
        for l, rd in runs
    ]
    hhsize_list = [(l, tour_sums.joint_tours_hhsize(rd)) for l, rd in runs]

    jtf_chart = bar_chart(
        jtf_list,
        x_col="alt_name",
        y_col="freq",
        title="Joint Tour Frequency (21 alternatives)",
        xaxis_title="Alternative",
        yaxis_title="Households",
        height=450,
    )

    comp_chart = bar_chart(
        comp_list,
        x_col="tour_composition",
        y_col="freq",
        title="Joint Tour Composition",
        xaxis_title="Composition",
        yaxis_title="Tours",
    )

    party_chart = bar_chart(
        party_list,
        x_col="NUMBER_HH",
        y_col="freq",
        title="Joint Tour Party Size",
        xaxis_title="Party Size",
        yaxis_title="Tours",
    )

    hhsize_opts = ["Total", "2", "3", "4", "5"]
    hhsize_sel = pn.widgets.Select(name="HH Size", options=hhsize_opts, value="Total")

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

    @pn.depends(hhsize_sel)
    def hhsize_chart(hhsize):
        if hhsize == "Total":
            data = []
            for l, df in hhsize_list:
                agg = _ordered_presence(df)
                tot = float(agg["freq"].sum()) if len(agg) > 0 else 0.0
                if tot > 0:
                    agg = agg.with_columns((pl.col("freq") / tot * 100).alias("freq"))
                data.append((l, agg))
        else:
            data = [
                (
                    l,
                    _ordered_presence(
                        df.filter(pl.col("hhsize").cast(pl.Utf8) == hhsize)
                    ),
                )
                for l, df in hhsize_list
            ]
        return bar_chart(
            data,
            "jointTours",
            "freq",
            f"Joint Tour Presence by HH Size ({hhsize})",
            "Joint Tours",
            "% HH",
        )

    return pn.Column(
        pn.pane.Markdown("## Joint Tours"),
        jtf_chart,
        pn.Row(comp_chart, party_chart),
        pn.Row(pn.pane.Markdown("**HH Size:**"), hhsize_sel),
        hhsize_chart,
        sizing_mode="stretch_width",
    )
