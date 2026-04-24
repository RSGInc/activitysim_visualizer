"""Transit validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, data_table
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from runtime.config import Config


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [(label, df) for label, df in data_list if df is not None and len(df) > 0]


def _options(
    data_list: list[tuple[str, pl.DataFrame]],
    col: str,
    total_label: str = "All",
) -> list[str]:
    first_df = next((df for _, df in data_list if df is not None and len(df) > 0), None)
    if first_df is None or col not in first_df.columns:
        return [total_label]

    vals = (
        first_df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
    )
    return [total_label] + sorted(v for v in vals if v != total_label)


def _filter_transit(
    data_list: list[tuple[str, pl.DataFrame]],
    technology: str,
    access_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in _nonempty(data_list):
        if "technology" in df.columns:
            df = df.with_columns(pl.col("technology").cast(pl.Utf8))
            if technology != "All":
                df = df.filter(pl.col("technology") == technology)

        if access_mode is not None and "access_mode" in df.columns:
            df = df.with_columns(pl.col("access_mode").cast(pl.Utf8))
            if access_mode != "All":
                df = df.filter(pl.col("access_mode") == access_mode)

        out.append((label, df))

    return out


class TransitValidationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Transit Validation", state, config)

        boarding_data = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            "weighted",
        )
        transfer_data = self.state.get_summary_table_set(
            "transit_transfer_rate",
            "weighted",
        )

        tech_opts = _options(boarding_data or [], "technology")
        access_opts = _options(transfer_data or [], "access_mode")

        self.technology_sel = pn.widgets.Select(
            name="Transit Technology",
            options=tech_opts,
            value=tech_opts[0],
        )
        self._watch_widget(self.technology_sel)

        self.access_mode_sel = pn.widgets.Select(
            name="Access Mode",
            options=access_opts,
            value=access_opts[0],
        )
        self._watch_widget(self.access_mode_sel)

        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Transit Validation"),
            pn.Row(
                pn.pane.Markdown("**Transit Technology:**"),
                self.technology_sel,
            ),
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

        boarding_list = summaries["transit_boardings_by_operator_and_technology"]
        transfer_list = summaries["transit_transfer_rate"]

        tech_opts = _options(boarding_list, "technology")
        self.technology_sel.options = tech_opts
        if self.technology_sel.value not in tech_opts:
            self.technology_sel.value = tech_opts[0]

        access_opts = _options(transfer_list, "access_mode")
        self.access_mode_sel.options = access_opts
        if self.access_mode_sel.value not in access_opts:
            self.access_mode_sel.value = access_opts[0]

        technology = self.technology_sel.value
        access_mode = self.access_mode_sel.value

        boarding_data = self.get_filtered_view(
            "transit_boardings",
            technology,
            factory=lambda: _filter_transit(
                boarding_list,
                technology,
            ),
        )

        transfer_data = self.get_filtered_view(
            "transit_transfer_rate",
            (technology, access_mode),
            factory=lambda: _filter_transit(
                transfer_list,
                technology,
                access_mode,
            ),
        )

        boarding_chart = bar_chart(
            boarding_data,
            x_col="operator",
            y_col="boarding_count",
            title=f"Total Transit Boardings by Operator - {technology}",
            xaxis_title="Operator",
            yaxis_title="Transit Boardings",
            pct_col="pct",
            as_percent=self.as_percent,
        )

        transfer_chart = bar_chart(
            transfer_data,
            x_col="operator",
            y_col="transfer_rate",
            title=f"Transit Transfer Rate - {technology}, {access_mode}",
            xaxis_title="Operator",
            yaxis_title="Boardings per Linked Trip",
            as_percent=False,
        )

        self._body.objects = [
            pn.Row(
                boarding_chart,
                pn.Column(
                    pn.Row(
                        pn.pane.Markdown("**Access Mode:**"),
                        self.access_mode_sel,
                    ),
                    transfer_chart,
                ),
                sizing_mode="stretch_width",
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="transit",
    title="Transit Validation",
    order=53,
    controller_cls=TransitValidationPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="technology",
            widget_attr="technology_sel",
            label="Transit Technology",
        ),
        PageSelectorDefinition(
            selector_id="access_mode",
            widget_attr="access_mode_sel",
            label="Access Mode",
        ),
    ),
    required_summary_ids=(
        "transit_boardings_by_operator_and_technology",
        "transit_transfer_rate",
    ),
)

TransitValidationPage.definition = PAGE
