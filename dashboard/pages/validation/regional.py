"""Regional validation page for externally supplied flow and WFH summaries."""

from __future__ import annotations

import panel as pn
import polars as pl
import plotly.graph_objects as go

from dashboard.components import bar_chart, data_table, selector_row
from dashboard.helpers.category_helpers import nonempty
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition

FLOW_OPTIONS = {
    "District flows": "external_county_flows",
    "County flows": "external_county_flows_joja",
}


def normalize_flow_matrix(df: pl.DataFrame, *, include_totals: bool) -> pl.DataFrame:
    """Return a flow matrix with an explicit origin column."""
    if "" in df.columns:
        matrix = df.rename({"": "Origin"})
    elif "Origin" in df.columns:
        matrix = df
    else:
        first_column = df.columns[0]
        matrix = df.rename({first_column: "Origin"})
    if not include_totals:
        non_total_columns = [
            column
            for column in matrix.columns
            if column == "Origin" or str(column).lower() != "total"
        ]
        matrix = matrix.select(non_total_columns).filter(
            pl.col("Origin").cast(pl.Utf8).str.to_lowercase() != "total"
        )
    return matrix


def flow_heatmap(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    include_totals: bool,
    title: str,
) -> pn.viewable.Viewable:
    tabs = pn.Tabs()
    for label, df in nonempty(data_list):
        matrix = normalize_flow_matrix(df, include_totals=include_totals)
        destinations = [column for column in matrix.columns if column != "Origin"]
        z = matrix.select(destinations).to_numpy().tolist()
        text = [[f"{value:,.0f}" for value in row] for row in z]
        fig = go.Figure(
            data=go.Heatmap(
                z=z,
                text=text,
                texttemplate="%{text}",
                textfont=dict(size=12),
                x=destinations,
                y=matrix["Origin"].cast(pl.Utf8).to_list(),
                colorscale="Blues",
                hovertemplate=(
                    "Origin: %{y}<br>Destination: %{x}<br>Flow: %{z:,.0f}<extra></extra>"
                ),
            )
        )
        fig.update_layout(
            title=dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top"),
            height=420,
            xaxis_title="Destination",
            yaxis_title="Origin",
            margin=dict(l=70, r=20, t=80, b=70),
            font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
        )
        tabs.append((label, pn.pane.Plotly(fig, sizing_mode="stretch_width")))
    return tabs


def wfh_rate_data(
    data_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        if not {"District", "Workers", "WFH"}.issubset(df.columns):
            continue
        chart_df = (
            df.with_columns(
                [
                    pl.col("District").cast(pl.Utf8),
                    (pl.col("WFH") / pl.col("Workers") * 100.0).alias("wfh_rate"),
                ]
            )
            .filter(pl.col("District").str.to_lowercase() != "total")
            .select("District", "Workers", "WFH", "wfh_rate")
        )
        out.append((label, chart_df))
    return out


class RegionalValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        flow_options = self._available_flow_options()
        self.flow_matrix_sel = self.selector(
            "flow_matrix",
            widget=pn.widgets.Select(
                name="Flow Matrix",
                options=flow_options,
                value=flow_options[0],
            ),
            label="Flow Matrix",
        )
        self.include_totals_sel = self.selector(
            "include_totals",
            widget=pn.widgets.Checkbox(
                name="Include Totals",
                value=False,
            ),
            label="Include Totals",
        )
        self._body = self.section(
            "regional_validation_body",
            selectors=("flow_matrix", "include_totals"),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Regional Validation"),
            selector_row(self.flow_matrix_sel, self.include_totals_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _available_flow_options(self) -> list[str]:
        options = [
            label
            for label, summary_id in FLOW_OPTIONS.items()
            if self.state.get_summary_table_set(summary_id, self.weighting_key)
            is not None
        ]
        return options or list(FLOW_OPTIONS)

    def sync_controls(self) -> None:
        options = self._available_flow_options()
        self.flow_matrix_sel.options = options
        if self.flow_matrix_sel.value not in options:
            self.flow_matrix_sel.value = options[0]

    def render_flow_section(self) -> pn.viewable.Viewable:
        flow_label = str(self.flow_matrix_sel.value)
        summary_id = FLOW_OPTIONS[flow_label]
        flow_data = self.state.get_summary_table_set(summary_id, self.weighting_key)
        if flow_data is None:
            return self.data_not_available_card(
                detail="External regional flow summaries are unavailable.",
                missing_items=[summary_id],
            )
        include_totals = bool(self.include_totals_sel.value)
        return pn.Column(
            flow_heatmap(
                flow_data,
                include_totals=include_totals,
                title=flow_label,
            ),
            sizing_mode="stretch_width",
        )

    def render_wfh_section(self) -> pn.viewable.Viewable:
        wfh_data = self.state.get_summary_table_set(
            "external_work_from_home_summary",
            self.weighting_key,
        )
        if wfh_data is None:
            return self.data_not_available_card(
                detail="External work-from-home summaries are unavailable.",
                missing_items=["external_work_from_home_summary"],
            )
        chart_data = self.get_filtered_view(
            "external_wfh_rate",
            self.weighting_key,
            factory=lambda: wfh_rate_data(wfh_data),
        )
        return pn.Column(
            bar_chart(
                chart_data,
                x_col="District",
                y_col="wfh_rate",
                title="Work From Home Rate by District",
                xaxis_title="District",
                yaxis_title="WFH Rate (%)",
                as_percent=False,
            ),
            data_table(chart_data, "Work From Home by District"),
            sizing_mode="stretch_width",
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        return [
            self.render_flow_section(),
            self.render_wfh_section(),
        ]


PAGE = DashboardPageDefinition(
    page_id="regional_validation",
    title="Regional Validation",
    group_id="validation",
    order=55,
    page_cls=RegionalValidationPage,
    default_enabled=False,
    optional_summary_ids=(
        "external_county_flows",
        "external_county_flows_joja",
        "external_work_from_home_summary",
    ),
)

RegionalValidationPage.definition = PAGE
