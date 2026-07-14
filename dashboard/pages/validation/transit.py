"""Transit validation page with boardings and transfer-rate operator charts."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.rendering import selector_row
from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import (
    common_column_options,
    column_options,
    nonempty,
)
from dashboard import DashboardPage, dashboard_page


def filter_transit_data(
    data_list: list[tuple[str, pl.DataFrame]],
    technology: str,
    access_mode: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter transit summaries and aggregate by operator for the chart-specific metric."""

    def prepare(frame: pl.DataFrame) -> pl.DataFrame:
        filtered = frame
        if "technology" in filtered.columns and technology != "All":
            filtered = filtered.with_columns(pl.col("technology").cast(pl.Utf8)).filter(
                pl.col("technology") == technology
            )
        if (
            access_mode is not None
            and "access_mode" in filtered.columns
            and access_mode != "All"
        ):
            filtered = filtered.with_columns(
                pl.col("access_mode").cast(pl.Utf8)
            ).filter(pl.col("access_mode") == access_mode)
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
        return filtered

    return RunTables.from_runs(data_list).map(prepare)


@dashboard_page(
    page_id="transit",
    title="Transit Validation",
    group_id="validation",
    order=53,
    required_summary_ids=(
        "transit_boardings_by_operator_and_technology",
        "transit_transfer_rate",
    ),
)
class TransitValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self.technology_sel = self.select(
            "technology",
            "Transit Technology",
            options=self._technology_options,
        )
        self.access_mode_sel = self.select(
            "access_mode",
            "Access Mode",
            options=self._access_mode_options,
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

    def _technology_options(self) -> list[str]:
        options, _ = common_column_options(
            self.data.summary(
                "transit_boardings_by_operator_and_technology", self.weighting_key
            ),
            self.data.summary("transit_transfer_rate", self.weighting_key),
            column="technology",
            total_raw="All",
            total_label="All",
        )
        return options or ["All"]

    def _access_mode_options(self) -> list[str]:
        options, _ = column_options(
            self.data.summary("transit_transfer_rate", self.weighting_key) or [],
            "access_mode",
            total_raw="All",
            total_label="All",
        )
        return options or ["All"]

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
        boarding_list = self.data.summary(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        if boarding_list is None:
            return self.data_not_available_card(
                detail="Transit boarding summaries are unavailable.",
                missing_items=["transit_boardings_by_operator_and_technology"],
            )
        technology = self.technology_sel.value
        boarding_data = self.query(
            lambda: filter_transit_data(boarding_list, technology)
        )
        return self.plot.bar(
            boarding_data,
            x="operator",
            y="boardings",
            title=f"Total Transit Boardings by Operator - {technology}",
            x_title="Operator",
            y_title="Transit Boardings",
            category_order=operator_values,
        )

    def render_transfer_chart(self, operator_values: list[str]) -> pn.viewable.Viewable:
        transfer_list = self.data.summary(
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
        transfer_data = self.query(
            lambda: filter_transit_data(transfer_list, technology, access_mode)
        )
        return self.plot.bar(
            transfer_data,
            x="operator",
            y="transfer_rate",
            title=f"Transit Transfer Rate - {technology}, {access_mode}",
            x_title="Operator",
            y_title="Boardings per Linked Trip",
            value_mode="count",
            category_order=operator_values,
        )

    def render_boardings_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        boarding_list = self.data.summary(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        transfer_list = self.data.summary(
            "transit_transfer_rate",
            self.weighting_key,
        )
        operator_values = self._operator_values(boarding_list, transfer_list)
        return [self.render_boardings_chart(operator_values)]

    def render_transfer_section(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        boarding_list = self.data.summary(
            "transit_boardings_by_operator_and_technology",
            self.weighting_key,
        )
        transfer_list = self.data.summary(
            "transit_transfer_rate",
            self.weighting_key,
        )
        operator_values = self._operator_values(boarding_list, transfer_list)
        return [self.render_transfer_chart(operator_values)]
