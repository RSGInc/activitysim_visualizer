"""Transit validation page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import (
    bar_chart,
    control_row,
    control_row_spacer,
)
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


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


def _common_options(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
    col: str,
    total_label: str = "All",
) -> list[str]:
    available_sets: list[set[str]] = []
    for data_list in data_lists:
        if data_list is None:
            continue
        per_run_sets: list[set[str]] = []
        for _, df in _nonempty(data_list):
            if col not in df.columns:
                continue
            values = (
                df.select(col).drop_nulls().unique().to_series().cast(pl.Utf8).to_list()
            )
            per_run_sets.append(set(values))
        if per_run_sets:
            available_sets.append(set.intersection(*per_run_sets))
    if not available_sets:
        return [total_label]
    common = set.intersection(*available_sets)
    return [total_label] + sorted(v for v in common if v != total_label)


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


class TransitValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        boarding_data = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            "weighted",
        )
        transfer_data = self.state.get_summary_table_set(
            "transit_transfer_rate",
            "weighted",
        )
        tech_opts = _common_options(
            boarding_data,
            transfer_data,
            col="technology",
        )
        access_opts = _options(transfer_data or [], "access_mode")
        self.technology_sel = self.selector(
            "technology",
            widget=pn.widgets.Select(
                name="Transit Technology",
                options=tech_opts,
                value=tech_opts[0],
            ),
            label="Transit Technology",
        )
        self.access_mode_sel = self.selector(
            "access_mode",
            widget=pn.widgets.Select(
                name="Access Mode",
                options=access_opts,
                value=access_opts[0],
            ),
            label="Access Mode",
        )
        self._body = self.section(
            "transit_body",
            selectors=("technology", "access_mode"),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Transit Validation"),
            pn.Row(
                pn.pane.Markdown("**Transit Technology:**"),
                self.technology_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        boarding_list = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        transfer_list = self.state.get_summary_table_set(
            "transit_transfer_rate",
            self.weighting_key,
        )
        tech_opts = _common_options(
            boarding_list,
            transfer_list,
            col="technology",
        )
        self.technology_sel.options = tech_opts
        if self.technology_sel.value not in tech_opts:
            self.technology_sel.value = tech_opts[0]
        access_opts = _options(transfer_list or [], "access_mode")
        self.access_mode_sel.options = access_opts
        if self.access_mode_sel.value not in access_opts:
            self.access_mode_sel.value = access_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        boarding_list = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        transfer_list = self.state.get_summary_table_set(
            "transit_transfer_rate",
            self.weighting_key,
        )
        technology = self.technology_sel.value
        access_mode = self.access_mode_sel.value

        if boarding_list is not None:
            boarding_data = self.get_filtered_view(
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
            transfer_data = self.get_filtered_view(
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
            pn.Row(
                pn.Column(control_row_spacer(), boarding_chart),
                pn.Column(
                    control_row(
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
    group_id="validation",
    order=53,
    page_cls=TransitValidationPage,
    required_summary_ids=(
        "transit_boardings_by_operator_and_technology",
        "transit_transfer_rate",
    ),
)

TransitValidationPage.definition = PAGE
