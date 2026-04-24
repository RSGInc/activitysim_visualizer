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
            ptype_set.update(df["person_type"].cast(pl.Utf8).unique().to_list())
    return (
        sorted(str(ptype) for ptype in ptype_set) if ptype_set else ["all_person_types"]
    )


def ptype_maps(
    ptype_opts: list[str], config: Config
) -> tuple[list[str], dict[str, str | None]]:
    """Return display and reverse mappings for person-type selectors."""
    label_to_ptype: dict[str, str | None] = {}
    if "all_person_types" in ptype_opts:
        label_to_ptype["Total"] = "all_person_types"
    else:
        label_to_ptype["Total"] = None
    for ptype in ptype_opts:
        if ptype in {"all_person_types", "Total"}:
            continue
        label_to_ptype[config.person_type_label(ptype)] = ptype
    return list(label_to_ptype), label_to_ptype


def _ptype_filter(df: pl.DataFrame, ptype: str | None) -> pl.DataFrame:
    ptype_col = pl.col("person_type").cast(pl.Utf8)
    if ptype is None:
        return df.filter(~ptype_col.is_in(["all_person_types", "Total"]))
    return df.filter(ptype_col == ptype)


def ordered_dap(df: pl.DataFrame, ptype: str | None) -> pl.DataFrame:
    """Return ordered DAP rows for one person type."""
    d = _ptype_filter(df, ptype)
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


def ordered_mtf(df: pl.DataFrame, ptype: str | None) -> pl.DataFrame:
    """Return ordered mandatory-tour-frequency rows for one person type."""
    d = _ptype_filter(df, ptype).with_columns(
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


def ordered_inm(df: pl.DataFrame, ptype: str | None) -> pl.DataFrame:
    """Return ordered individual non-mandatory-tour rows for one person type."""
    d = _ptype_filter(df, ptype).with_columns(
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
    ptype: str | None,
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
        display_opts, self._label_to_ptype = ptype_maps(ptype_opts, config)
        default_value = "Total" if "Total" in display_opts else display_opts[0]
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
        if dap_list is None or not dap_list:
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
        display_opts, self._label_to_ptype = ptype_maps(ptype_opts, self.config)
        self.ptype_sel.options = display_opts
        if self.ptype_sel.value not in display_opts:
            self.ptype_sel.value = "Total" if "Total" in display_opts else display_opts[0]
        ptype_label = self.ptype_sel.value
        ptype = self._label_to_ptype.get(ptype_label, ptype_label)

        dap_data, mtf_data, inm_data = self.get_filtered_view(
            "tour_summary",
            ptype,
            factory=lambda: chart_data(dap_list, mtf_list, inm_list, ptype),
        )

        self._body.objects = [
            pn.Row(
                bar_chart(
                    dap_data,
                    "daily_activity_pattern",
                    "person_count",
                    f"Daily Activity Pattern - {ptype_label}",
                    "Pattern",
                    as_percent=self.as_percent,
                ),
                bar_chart(
                    mtf_data,
                    "mandatory_tour_frequency_label",
                    "person_count",
                    f"Mandatory Tour Frequency - {ptype_label}",
                    "Alternative",
                    as_percent=self.as_percent,
                ),
            ),
            bar_chart(
                inm_data,
                "nonmandatory_tour_frequency",
                "person_count",
                f"Individual Non-Mandatory Tours - {ptype_label}",
                "# Tours",
                as_percent=self.as_percent,
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="tour_summary",
    title="Tour Summary",
    group_id="tours",
    child_id="summary",
    child_order=10,
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
