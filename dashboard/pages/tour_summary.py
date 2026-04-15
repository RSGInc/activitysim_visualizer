"""Tour summary page: DAP, MTF, INM, tour rates."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def ptype_options(dap_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    """Collect available person types from DAP summaries."""
    ptype_set = set()
    for _, df in dap_list:
        if "person_type" in df.columns:
            ptype_set.update(df["person_type"].unique().to_list())
    return sorted(ptype_set) if ptype_set else ["all_person_types"]


def ptype_maps(ptype_opts: list[str], config: Config) -> tuple[dict, dict[str, object]]:
    """Return display and reverse mappings for person-type selectors."""
    ptype_label_map = {
        p: (
            "All Person Types"
            if str(p) == "all_person_types"
            else config.person_type_label(p)
        )
        for p in ptype_opts
    }
    label_to_ptype = {lbl: p for p, lbl in ptype_label_map.items()}
    return ptype_label_map, label_to_ptype


def ordered_dap(df: pl.DataFrame, ptype) -> pl.DataFrame:
    """Return ordered DAP rows for one person type."""
    d = df.filter(pl.col("person_type") == ptype)
    base = pl.DataFrame({"daily_activity_pattern": ["M", "N", "H"]})
    return (
        base.join(
            d.select(
                [
                    pl.col("daily_activity_pattern")
                    .cast(pl.Utf8)
                    .alias("daily_activity_pattern"),
                    "person_count",
                ]
            ),
            on="daily_activity_pattern",
            how="left",
        )
        .with_columns(pl.col("person_count").fill_null(0.0))
        .with_columns(
            pl.when(pl.col("daily_activity_pattern") == "M")
            .then(0)
            .when(pl.col("daily_activity_pattern") == "N")
            .then(1)
            .otherwise(2)
            .alias("_ord")
        )
        .sort("_ord")
        .drop("_ord")
    )


def ordered_mtf(df: pl.DataFrame, ptype) -> pl.DataFrame:
    """Return ordered mandatory-tour-frequency rows for one person type."""
    d = df.filter(pl.col("person_type") == ptype).with_columns(
        pl.col("mandatory_tour_frequency")
        .cast(pl.Int64)
        .alias("mandatory_tour_frequency")
    )
    base = pl.DataFrame({"mandatory_tour_frequency": [1, 2, 3, 4, 5]})
    labels = pl.DataFrame(
        {
            "mandatory_tour_frequency": [1, 2, 3, 4, 5],
            "mandatory_tour_frequency_label": [
                "work1",
                "work2",
                "school1",
                "school2",
                "work and school",
            ],
        }
    )
    return (
        base.join(
            d.select(["mandatory_tour_frequency", "person_count"]),
            on="mandatory_tour_frequency",
            how="left",
        )
        .with_columns(pl.col("person_count").fill_null(0.0))
        .join(labels, on="mandatory_tour_frequency", how="left")
        .select(["mandatory_tour_frequency_label", "person_count"])
    )


def ordered_inm(df: pl.DataFrame, ptype) -> pl.DataFrame:
    """Return ordered individual non-mandatory-tour rows for one person type."""
    d = df.filter(pl.col("person_type") == ptype).with_columns(
        pl.col("nonmandatory_tour_frequency")
        .cast(pl.Utf8)
        .alias("nonmandatory_tour_frequency")
    )
    base = pl.DataFrame({"nonmandatory_tour_frequency": ["0", "1", "2", "3+"]})
    return base.join(
        d.select(["nonmandatory_tour_frequency", "person_count"]),
        on="nonmandatory_tour_frequency",
        how="left",
    ).with_columns(pl.col("person_count").fill_null(0.0))


def chart_data(
    dap_list: list[tuple[str, pl.DataFrame]],
    mtf_list: list[tuple[str, pl.DataFrame]],
    inm_list: list[tuple[str, pl.DataFrame]],
    ptype,
) -> tuple[
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
    list[tuple[str, pl.DataFrame]],
]:
    """Build ordered chart datasets for one person type."""
    return (
        [(label, ordered_dap(df, ptype)) for label, df in dap_list],
        [(label, ordered_mtf(df, ptype)) for label, df in mtf_list],
        [(label, ordered_inm(df, ptype)) for label, df in inm_list],
    )


class TourSummaryPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Tour Summary", state, config)
        ptype_opts = self._ptype_options()
        ptype_label_map, self._label_to_ptype = ptype_maps(ptype_opts, config)
        display_opts = [ptype_label_map[p] for p in ptype_opts] or ["All Person Types"]
        default_value = (
            "All Person Types"
            if "All Person Types" in display_opts
            else display_opts[0]
        )
        self.ptype_sel = pn.widgets.Select(
            name="Person Type",
            options=display_opts,
            value=default_value,
        )
        self._watch_widget(self.ptype_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Tour Summary"),
            pn.Row(pn.pane.Markdown("**Person Type:**"), self.ptype_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _ptype_options(self) -> list[str]:
        dap_list = self.state.get_summary_table_set(
            "daily_activity_pattern_by_person_type", "weighted"
        )
        if dap_list is None:
            return ["all_person_types"]
        if not dap_list:
            return ["all_person_types"]
        return ptype_options(dap_list)

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

        dap_list = summaries["daily_activity_pattern_by_person_type"]
        mtf_list = summaries["mandatory_tour_frequency_by_person_type"]
        inm_list = summaries["nonmandatory_tour_frequency_by_person_type"]
        ptype_opts = ptype_options(dap_list)
        ptype_label_map, self._label_to_ptype = ptype_maps(ptype_opts, self.config)
        display_opts = [ptype_label_map[p] for p in ptype_opts] or ["All Person Types"]
        self.ptype_sel.options = display_opts
        if self.ptype_sel.value not in display_opts:
            self.ptype_sel.value = (
                "All Person Types"
                if "All Person Types" in display_opts
                else display_opts[0]
            )
        ptype_label = self.ptype_sel.value
        ptype = self._label_to_ptype.get(ptype_label, ptype_label)

        dap_data, mtf_data, inm_data = self.get_filtered_view(
            "tour_summary",
            ptype,
            factory=lambda: chart_data(dap_list, mtf_list, inm_list, ptype),
        )

        dap_chart = bar_chart(
            dap_data,
            "daily_activity_pattern",
            "person_count",
            f"Daily Activity Pattern - {ptype_label}",
            "Pattern",
            as_percent=self.as_percent,
        )
        mtf_chart = bar_chart(
            mtf_data,
            "mandatory_tour_frequency_label",
            "person_count",
            f"Mandatory Tour Frequency - {ptype_label}",
            "Alternative",
            as_percent=self.as_percent,
        )
        inm_chart = bar_chart(
            inm_data,
            "nonmandatory_tour_frequency",
            "person_count",
            f"Individual NM Tours - {ptype_label}",
            "# Tours",
            as_percent=self.as_percent,
        )

        self._body.objects = [pn.Row(dap_chart, mtf_chart), inm_chart]


PAGE = DashboardPageDefinition(
    page_id="tour_summary",
    title="Tour Summary",
    order=30,
    controller_cls=TourSummaryPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="person_type",
            widget_attr="ptype_sel",
            label="Person Type",
        ),
    ),
    required_summary_ids=(
        "daily_activity_pattern_by_person_type",
        "mandatory_tour_frequency_by_person_type",
        "nonmandatory_tour_frequency_by_person_type",
    ),
)

TourSummaryPage.definition = PAGE
