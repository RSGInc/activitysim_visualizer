"""Transit validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import (
    bar_chart,
    control_row,
    control_row_spacer,
)
from dashboard.page_base import MultiSelectorComparisonPage, SectionSpec, SelectorSpec
from dashboard.page_definitions import DashboardPageDefinition
from dashboard.pages._shared.common import column_options, nonempty_runs


def _filter_transit(
    data_list: list[tuple[str, pl.DataFrame]],
    technology: str,
    access_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    out = []

    for label, df in nonempty_runs(data_list):
        if "technology" in df.columns:
            df = df.with_columns(pl.col("technology").cast(pl.Utf8))
            if technology != "All":
                df = df.filter(pl.col("technology") == technology)

        if access_mode is not None and "access_mode" in df.columns:
            df = df.with_columns(pl.col("access_mode").cast(pl.Utf8))
            if access_mode != "All":
                df = df.filter(pl.col("access_mode") == access_mode)

        if {"operator", "boardings"}.issubset(df.columns):
            df = (
                df.group_by("operator")
                .agg(boardings=pl.col("boardings").sum())
                .with_columns(pl.col("operator").cast(pl.Utf8))
                .sort("operator")
            )
        elif {"operator", "transfer_rate"}.issubset(df.columns):
            df = (
                df.group_by("operator")
                .agg(transfer_rate=pl.col("transfer_rate").mean())
                .with_columns(pl.col("operator").cast(pl.Utf8))
                .sort("operator")
            )

        out.append((label, df))

    return out


class TransitValidationPage(MultiSelectorComparisonPage):
    def selector_specs(self) -> tuple[SelectorSpec, ...]:
        return (
            SelectorSpec(
                selector_id="technology",
                label="Transit Technology",
                attr_name="technology_sel",
                options_factory=lambda page: page._technology_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Transit Technology",
                    options=options,
                    value=value,
                ),
            ),
            SelectorSpec(
                selector_id="access_mode",
                label="Access Mode",
                attr_name="access_mode_sel",
                options_factory=lambda page: page._access_mode_options(),
                widget_factory=lambda page, options, value: pn.widgets.Select(
                    name="Access Mode",
                    options=options,
                    value=value,
                ),
            ),
        )

    def _technology_options(self) -> list[object]:
        boarding_list = self.get_refresh_summary(
            "transit_boardings_by_operator_and_technology",
            optional=True,
        )
        transfer_list = self.get_refresh_summary(
            "transit_transfer_rate",
            optional=True,
        )
        return column_options(boarding_list or transfer_list or [], "technology")

    def _access_mode_options(self) -> list[object]:
        transfer_list = self.get_refresh_summary(
            "transit_transfer_rate",
            optional=True,
        )
        return column_options(transfer_list or [], "access_mode")

    def build_page(self) -> pn.viewable.Viewable:
        self.register_selectors(*self.selector_specs())
        self.register_sections(
            SectionSpec(
                section_id="transit_body",
                selector_ids=("technology", "access_mode"),
                render=lambda page: page.render_body(),
                attr_name="_body",
            )
        )
        return self.new_section(
            pn.pane.Markdown("## Transit Validation"),
            self.selector_row("technology"),
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        def _ready(_summaries):
            boarding_list = self.get_refresh_summary(
                "transit_boardings_by_operator_and_technology",
                optional=True,
            )
            transfer_list = self.get_refresh_summary(
                "transit_transfer_rate",
                optional=True,
            )
            technology = self.technology_sel.value
            access_mode = self.access_mode_sel.value

            if boarding_list is not None:
                boarding_data = self.filtered_view(
                    "transit_boardings",
                    technology,
                    factory=lambda: _filter_transit(
                        boarding_list,
                        technology,
                    ),
                )
                boarding_chart: pn.viewable.Viewable = bar_chart(
                    boarding_data,
                    x_col="operator",
                    y_col="boardings",
                    title=f"Total Transit Boardings by Operator - {technology}",
                    xaxis_title="Operator",
                    yaxis_title="Transit Boardings",
                    pct_col="pct",
                    as_percent=self.as_percent,
                )
            else:
                boarding_chart = self.data_not_available_card(
                    detail="Transit boarding summaries are unavailable.",
                    missing_items=["transit_boardings_by_operator_and_technology"],
                )

            if transfer_list is not None:
                transfer_data = self.filtered_view(
                    "transit_transfer_rate",
                    (technology, access_mode),
                    factory=lambda: _filter_transit(
                        transfer_list,
                        technology,
                        access_mode,
                    ),
                )
                transfer_chart: pn.viewable.Viewable = bar_chart(
                    transfer_data,
                    x_col="operator",
                    y_col="transfer_rate",
                    title=f"Transit Transfer Rate - {technology}, {access_mode}",
                    xaxis_title="Operator",
                    yaxis_title="Boardings per Linked Trip",
                    as_percent=False,
                )
            else:
                transfer_chart = self.data_not_available_card(
                    detail="Transit transfer summaries are unavailable.",
                    missing_items=["transit_transfer_rate"],
                )

            return [
                self.aligned_dual_column(
                    control_row_spacer(),
                    boarding_chart,
                    control_row(
                        pn.pane.Markdown("**Access Mode:**"),
                        self.access_mode_sel,
                    ),
                    transfer_chart,
                ),
            ]

        return self.render_summary_page(
            _ready,
            required_summary_ids=(),
            detail="Transit validation summaries are unavailable.",
        )


PAGE = DashboardPageDefinition(
    page_id="transit",
    title="Transit Validation",
    group_id="validation",
    order=53,
    page_cls=TransitValidationPage,
    required_summary_ids=(
        "transit_boardings_by_operator_and_technology",
        "transit_transfer_rate",
    ),
)

TransitValidationPage.definition = PAGE
