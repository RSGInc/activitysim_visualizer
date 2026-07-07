"""Transit validation page with boardings and transfer-rate operator charts."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart, selector_row
from dashboard.helpers.category_helpers import common_column_options, column_options, nonempty
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def filter_transit_data(
    data_list: list[tuple[str, pl.DataFrame]],
    technology: str,
    access_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter transit summaries and aggregate by operator for the chart-specific metric."""
    out = []
    for label, df in nonempty(data_list):
        filtered = df
        if "technology" in filtered.columns and technology != "All":
            filtered = filtered.with_columns(pl.col("technology").cast(pl.Utf8)).filter(
                pl.col("technology") == technology
            )
        if access_mode is not None and "access_mode" in filtered.columns and access_mode != "All":
            filtered = filtered.with_columns(pl.col("access_mode").cast(pl.Utf8)).filter(
                pl.col("access_mode") == access_mode
            )
        if {"operator", "boardings"}.issubset(filtered.columns):
            filtered = (
                filtered.group_by("operator")
                .agg(boardings=pl.col("boardings").sum())
                .with_columns(pl.col("operator").cast(pl.Utf8))
                .sort("operator")
            )
        elif {"operator", "transfer_rate"}.issubset(filtered.columns):
            filtered = (
                filtered.group_by("operator")
                .agg(transfer_rate=pl.col("transfer_rate").mean())
                .with_columns(pl.col("operator").cast(pl.Utf8))
                .sort("operator")
            )
        out.append((label, filtered))
    return out


class TransitValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        tech_opts, _ = common_column_options(
            self.state.get_summary_table_set(
                "transit_boardings_by_operator_and_technology", "weighted"
            ),
            self.state.get_summary_table_set("transit_transfer_rate", "weighted"),
            column="technology",
            total_raw="All",
            total_label="All",
        )
        access_opts, _ = column_options(
            self.state.get_summary_table_set("transit_transfer_rate", "weighted") or [],
            "access_mode",
            total_raw="All",
            total_label="All",
        )
        self.technology_sel = self.selector(
            "technology",
            widget=pn.widgets.Select(
                name="Transit Technology",
                options=tech_opts or ["All"],
                value=(tech_opts or ["All"])[0],
            ),
            label="Transit Technology",
        )
        self.access_mode_sel = self.selector(
            "access_mode",
            widget=pn.widgets.Select(
                name="Access Mode",
                options=access_opts or ["All"],
                value=(access_opts or ["All"])[0],
            ),
            label="Access Mode",
        )
        self._boardings_body = self.section(
            "transit_boardings_body",
            selectors=("technology",),
            render=self.render_boardings_section,
        )
        self._transfer_body = self.section(
            "transit_transfer_body",
            selectors=("technology", "access_mode"),
            render=self.render_transfer_section,
        )
        return self.new_section(
            pn.pane.Markdown("## Transit Validation"),
            selector_row(self.technology_sel, self.access_mode_sel),
            self._boardings_body,
            self._transfer_body,
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
        tech_opts, _ = common_column_options(
            boarding_list,
            transfer_list,
            column="technology",
            total_raw="All",
            total_label="All",
        )
        access_opts, _ = column_options(
            transfer_list or [],
            "access_mode",
            total_raw="All",
            total_label="All",
        )
        self.technology_sel.options = tech_opts or ["All"]
        if self.technology_sel.value not in self.technology_sel.options:
            self.technology_sel.value = self.technology_sel.options[0]
        self.access_mode_sel.options = access_opts or ["All"]
        if self.access_mode_sel.value not in self.access_mode_sel.options:
            self.access_mode_sel.value = self.access_mode_sel.options[0]

    def _operator_values(
        self,
        *data_lists: list[tuple[str, pl.DataFrame]] | None,
    ) -> list[str]:
        return sorted(
            {
                str(value)
                for data_list in data_lists
                for _, df in nonempty(data_list or [])
                for value in (
                    df["operator"].cast(pl.Utf8).to_list()
                    if "operator" in df.columns
                    else []
                )
            }
        )

    def render_boardings_chart(
        self, operator_values: list[str]
    ) -> pn.viewable.Viewable:
        boarding_list = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        if boarding_list is None:
            return self.data_not_available_card(
                detail="Transit boarding summaries are unavailable.",
                missing_items=["transit_boardings_by_operator_and_technology"],
            )
        technology = self.technology_sel.value
        boarding_data = self.get_filtered_view(
            "transit_boardings",
            technology,
            factory=lambda: filter_transit_data(boarding_list, technology),
        )
        return bar_chart(
            boarding_data,
            x_col="operator",
            y_col="boardings",
            title=f"Total Transit Boardings by Operator - {technology}",
            xaxis_title="Operator",
            yaxis_title="Transit Boardings",
            pct_col="pct",
            as_percent=self.as_percent,
            xaxis_categoryarray=operator_values,
        )

    def render_transfer_chart(
        self, operator_values: list[str]
    ) -> pn.viewable.Viewable:
        transfer_list = self.state.get_summary_table_set(
            "transit_transfer_rate",
            self.weighting_key,
        )
        if transfer_list is None:
            return self.data_not_available_card(
                detail="Transit transfer summaries are unavailable.",
                missing_items=["transit_transfer_rate"],
            )
        technology = self.technology_sel.value
        access_mode = self.access_mode_sel.value
        transfer_data = self.get_filtered_view(
            "transit_transfer_rate",
            (technology, access_mode),
            factory=lambda: filter_transit_data(transfer_list, technology, access_mode),
        )
        return bar_chart(
            transfer_data,
            x_col="operator",
            y_col="transfer_rate",
            title=f"Transit Transfer Rate - {technology}, {access_mode}",
            xaxis_title="Operator",
            yaxis_title="Boardings per Linked Trip",
            as_percent=False,
            xaxis_categoryarray=operator_values,
        )

    def render_boardings_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        boarding_list = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        transfer_list = self.state.get_summary_table_set(
            "transit_transfer_rate",
            self.weighting_key,
        )
        operator_values = self._operator_values(boarding_list, transfer_list)
        return [self.render_boardings_chart(operator_values)]

    def render_transfer_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        boarding_list = self.state.get_summary_table_set(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        transfer_list = self.state.get_summary_table_set(
            "transit_transfer_rate",
            self.weighting_key,
        )
        operator_values = self._operator_values(boarding_list, transfer_list)
        return [self.render_transfer_chart(operator_values)]


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
