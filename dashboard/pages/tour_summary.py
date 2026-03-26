"""Tour summary page: DAP, MTF, INM, tour rates."""
from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart
from summarize.reader import RunData, Config
from summarize import tours as tour_sums


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    dap_list = [(l, tour_sums.dap_summary(rd, config)) for l, rd in runs]
    mtf_list = [(l, tour_sums.mandatory_tour_freq(rd, config)) for l, rd in runs]
    inm_list = [(l, tour_sums.indiv_nm_summary(rd, config)) for l, rd in runs]

    # Collect ptype values from first run
    ptype_set = set()
    for _, df in dap_list:
        if "ptype" in df.columns:
            ptype_set.update(df["ptype"].unique().to_list())
    ptype_opts = sorted(ptype_set) if ptype_set else ["Total"]
    ptype_label_map = {p: ("Total" if str(p) == "Total" else config.ptype_label(p)) for p in ptype_opts}
    label_to_ptype = {lbl: p for p, lbl in ptype_label_map.items()}
    ptype_display_opts = [ptype_label_map[p] for p in ptype_opts]
    ptype_sel = pn.widgets.Select(
        name="Person Type",
        options=ptype_display_opts,
        value=("Total" if "Total" in ptype_display_opts else ptype_display_opts[0]),
    )

    @pn.depends(ptype_sel)
    def dap_chart(ptype_label):
        ptype = label_to_ptype.get(ptype_label, ptype_label)
        def _ordered(df: pl.DataFrame) -> pl.DataFrame:
            d = df.filter(pl.col("ptype") == ptype)
            base = pl.DataFrame({"DAP": ["M", "N", "H"]})
            d = base.join(
                d.select([pl.col("DAP").cast(pl.Utf8).alias("DAP"), "freq"]),
                on="DAP",
                how="left",
            ).with_columns(pl.col("freq").fill_null(0.0))
            d = d.with_columns(
                pl.when(pl.col("DAP") == "M").then(0)
                .when(pl.col("DAP") == "N").then(1)
                .otherwise(2).alias("_ord")
            ).sort("_ord").drop("_ord")
            return d
        data = [(l, _ordered(df)) for l, df in dap_list]
        return bar_chart(data, "DAP", "freq", f"Daily Activity Pattern — {ptype_label}", "Pattern")

    @pn.depends(ptype_sel)
    def mtf_chart(ptype_label):
        ptype = label_to_ptype.get(ptype_label, ptype_label)
        def _ordered(df: pl.DataFrame) -> pl.DataFrame:
            d = (df.filter(pl.col("ptype") == ptype)
                 .with_columns(pl.col("MTF").cast(pl.Int64).alias("MTF")))
            base = pl.DataFrame({"MTF": [1, 2, 3, 4, 5]})
            labels = pl.DataFrame({
                "MTF": [1, 2, 3, 4, 5],
                "MTF_label": ["work1", "work2", "school1", "school2", "work and school"],
            })
            return (base
                    .join(d.select(["MTF", "freq"]), on="MTF", how="left")
                    .with_columns(pl.col("freq").fill_null(0.0))
                    .join(labels, on="MTF", how="left")
                    .select(["MTF_label", "freq"]))
        data = [(l, _ordered(df)) for l, df in mtf_list]
        return bar_chart(
            data,
            "MTF_label", "freq", f"Mandatory Tour Frequency — {ptype_label}", "Alternative",
        )

    @pn.depends(ptype_sel)
    def inm_chart(ptype_label):
        ptype = label_to_ptype.get(ptype_label, ptype_label)
        def _ordered(df: pl.DataFrame) -> pl.DataFrame:
            d = df.filter(pl.col("ptype") == ptype).with_columns(pl.col("nmtours").cast(pl.Utf8).alias("nmtours"))
            base = pl.DataFrame({"nmtours": ["0", "1", "2", "3pl"]})
            return (base
                    .join(d.select(["nmtours", "freq"]), on="nmtours", how="left")
                    .with_columns(pl.col("freq").fill_null(0.0)))
        data = [(l, _ordered(df)) for l, df in inm_list]
        return bar_chart(data, "nmtours", "freq", f"Individual NM Tours — {ptype_label}", "# Tours")

    return pn.Column(
        pn.pane.Markdown("## Tour Summary"),
        pn.Row(pn.pane.Markdown("**Person Type:**"), ptype_sel),
        pn.Row(dap_chart, mtf_chart),
        inm_chart,
        sizing_mode="stretch_width",
    )
