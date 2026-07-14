"""Regional validation page for demo flow summaries."""

from __future__ import annotations

from dataclasses import dataclass

import panel as pn
import polars as pl
import plotly.graph_objects as go

from dashboard.rendering import selector_row
from dashboard.helpers.category_helpers import nonempty
from dashboard import DashboardPage, dashboard_page

TOTAL_FLOW_LABELS = {"total", "all", "all_geographies"}
FLOW_COMPARISON_OPTIONS = [
    "Observed",
    "Difference",
    "Percent Difference",
    "Absolute Percent Difference",
    "Modeled",
]
FLOW_VALUE_COLUMNS = {
    "Modeled": "modeled",
    "Observed": "observed",
    "Difference": "difference",
    "Percent Difference": "percent_difference",
    "Absolute Percent Difference": "absolute_percent_difference",
}


@dataclass(frozen=True)
class FlowOption:
    summary_id: str
    modeled_geography_types: tuple[str, ...]


FLOW_OPTIONS = {
    "District flows": FlowOption(
        summary_id="county_flows_validation_summary",
        modeled_geography_types=("district", "home_district"),
    ),
    "County flows": FlowOption(
        summary_id="county_flows_joja_validation_summary",
        modeled_geography_types=("county", "home_county"),
    ),
}


def _is_total_label(value: object) -> bool:
    return str(value).strip().lower() in TOTAL_FLOW_LABELS


def _is_total_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.to_lowercase()
        .is_in(TOTAL_FLOW_LABELS)
    )


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


def flow_matrix_to_long(
    df: pl.DataFrame,
    *,
    include_totals: bool,
    value_col: str,
) -> pl.DataFrame:
    """Return a long OD table from a demo wide flow matrix."""
    matrix = normalize_flow_matrix(df, include_totals=include_totals)
    destinations = [column for column in matrix.columns if column != "Origin"]
    if not destinations:
        return pl.DataFrame(
            {
                "Origin": pl.Series([], dtype=pl.Utf8),
                "Destination": pl.Series([], dtype=pl.Utf8),
                value_col: pl.Series([], dtype=pl.Float64),
            }
        )
    return (
        matrix.with_columns(pl.col("Origin").cast(pl.Utf8))
        .unpivot(
            index="Origin",
            on=destinations,
            variable_name="Destination",
            value_name=value_col,
        )
        .with_columns(
            pl.col("Destination").cast(pl.Utf8),
            pl.col(value_col).cast(pl.Float64, strict=False).fill_null(0.0),
        )
    )


def _flow_label_order(values: list[str], *, include_totals: bool) -> list[str]:
    """Return stable matrix axis labels, keeping totals at the end."""
    unique_values = list(dict.fromkeys(str(value) for value in values))
    non_totals = sorted(value for value in unique_values if not _is_total_label(value))
    totals = [value for value in unique_values if _is_total_label(value)]
    if include_totals and totals:
        return [*non_totals, totals[0]]
    return non_totals


def modeled_flow_long(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    geography_type: str,
    include_totals: bool,
) -> list[tuple[str, pl.DataFrame]]:
    """Return modeled commuting flows as long OD rows for one geography type."""
    out: list[tuple[str, pl.DataFrame]] = []
    required = {
        "origin_geography_type",
        "origin_geography_id",
        "destination_geography_type",
        "destination_geography_id",
        "commuter_count",
    }
    for label, df in nonempty(data_list or []):
        if not required.issubset(df.columns):
            continue
        base = (
            df.with_columns(
                pl.col("origin_geography_type").cast(pl.Utf8),
                pl.col("origin_geography_id").cast(pl.Utf8),
                pl.col("destination_geography_type").cast(pl.Utf8),
                pl.col("destination_geography_id").cast(pl.Utf8),
                pl.col("commuter_count").cast(pl.Float64, strict=False).fill_null(0.0),
            )
            .filter(
                (pl.col("origin_geography_type") == geography_type)
                & (pl.col("destination_geography_type") == geography_type)
            )
            .rename(
                {
                    "origin_geography_id": "Origin",
                    "destination_geography_id": "Destination",
                    "commuter_count": "modeled",
                }
            )
            .select("Origin", "Destination", "modeled")
            .filter(~_is_total_expr("Origin") & ~_is_total_expr("Destination"))
            .group_by("Origin", "Destination")
            .agg(pl.col("modeled").sum().alias("modeled"))
        )
        if include_totals and not base.is_empty():
            row_totals = (
                base.group_by("Origin")
                .agg(pl.col("modeled").sum().alias("modeled"))
                .with_columns(pl.lit("Total").alias("Destination"))
                .select("Origin", "Destination", "modeled")
            )
            column_totals = (
                base.group_by("Destination")
                .agg(pl.col("modeled").sum().alias("modeled"))
                .with_columns(pl.lit("Total").alias("Origin"))
                .select("Origin", "Destination", "modeled")
            )
            grand_total = pl.DataFrame(
                {
                    "Origin": ["Total"],
                    "Destination": ["Total"],
                    "modeled": [base["modeled"].sum()],
                }
            )
            base = pl.concat(
                [base, row_totals, column_totals, grand_total],
                how="vertical",
            )
        out.append((label, base))
    return out


def available_modeled_geography_type(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    candidates: tuple[str, ...],
) -> str | None:
    """Return the first configured modeled geography type present in the data."""
    available: set[str] = set()
    for _, df in nonempty(data_list or []):
        if {
            "origin_geography_type",
            "destination_geography_type",
        }.issubset(df.columns):
            origin_types = {
                str(value)
                for value in df["origin_geography_type"].drop_nulls().cast(pl.Utf8)
            }
            destination_types = {
                str(value)
                for value in df["destination_geography_type"].drop_nulls().cast(pl.Utf8)
            }
            available.update(origin_types & destination_types)
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


def flow_comparison_data(
    observed_data: list[tuple[str, pl.DataFrame]] | None,
    modeled_data: list[tuple[str, pl.DataFrame]] | None,
    *,
    geography_type: str,
    include_totals: bool,
) -> list[tuple[str, pl.DataFrame]]:
    """Align observed and modeled OD flows into comparison-ready long rows."""
    observed_runs = [
        (
            label,
            flow_matrix_to_long(
                df, include_totals=include_totals, value_col="observed"
            ),
        )
        for label, df in nonempty(observed_data or [])
    ]
    modeled_runs = modeled_flow_long(
        modeled_data,
        geography_type=geography_type,
        include_totals=include_totals,
    )
    if not observed_runs:
        return []

    observed_by_label = {label: df for label, df in observed_runs}
    default_observed = observed_runs[0][1]
    labels = [label for label, _ in modeled_runs] or [
        label for label, _ in observed_runs
    ]
    modeled_by_label = {label: df for label, df in modeled_runs}
    out: list[tuple[str, pl.DataFrame]] = []
    for label in labels:
        observed = observed_by_label.get(label, default_observed)
        modeled = modeled_by_label.get(
            label,
            pl.DataFrame(
                {
                    "Origin": pl.Series([], dtype=pl.Utf8),
                    "Destination": pl.Series([], dtype=pl.Utf8),
                    "modeled": pl.Series([], dtype=pl.Float64),
                }
            ),
        )
        origins = _flow_label_order(
            [
                *(observed["Origin"].to_list() if "Origin" in observed.columns else []),
                *(modeled["Origin"].to_list() if "Origin" in modeled.columns else []),
            ],
            include_totals=include_totals,
        )
        destinations = _flow_label_order(
            [
                *(
                    observed["Destination"].to_list()
                    if "Destination" in observed.columns
                    else []
                ),
                *(
                    modeled["Destination"].to_list()
                    if "Destination" in modeled.columns
                    else []
                ),
            ],
            include_totals=include_totals,
        )
        if not origins or not destinations:
            continue
        scaffold = pl.DataFrame({"Origin": origins}).join(
            pl.DataFrame({"Destination": destinations}),
            how="cross",
        )
        comparison = (
            scaffold.join(observed, on=["Origin", "Destination"], how="left")
            .join(modeled, on=["Origin", "Destination"], how="left")
            .with_columns(
                pl.col("observed").fill_null(0.0).cast(pl.Float64),
                pl.col("modeled").fill_null(0.0).cast(pl.Float64),
            )
            .with_columns(
                (pl.col("modeled") - pl.col("observed")).alias("difference"),
                pl.when(pl.col("observed") != 0)
                .then(
                    (pl.col("modeled") - pl.col("observed"))
                    / pl.col("observed")
                    * 100.0
                )
                .otherwise(None)
                .alias("percent_difference"),
            )
            .with_columns(
                pl.col("percent_difference").abs().alias("absolute_percent_difference")
            )
        )
        out.append((label, comparison))
    return out


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


def flow_comparison_heatmap(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    metric: str,
    title: str,
) -> pn.viewable.Viewable:
    """Render aligned observed/modeled flow comparisons as heatmaps."""
    value_col = FLOW_VALUE_COLUMNS[metric]
    tabs = pn.Tabs()
    for label, df in nonempty(data_list):
        if df.is_empty():
            continue
        origins = _flow_label_order(df["Origin"].to_list(), include_totals=True)
        destinations = _flow_label_order(
            df["Destination"].to_list(),
            include_totals=True,
        )
        lookup = {
            (row["Origin"], row["Destination"]): row[value_col]
            for row in df.select("Origin", "Destination", value_col).to_dicts()
        }
        z = [
            [lookup.get((origin, destination)) for destination in destinations]
            for origin in origins
        ]
        if metric in {"Percent Difference", "Absolute Percent Difference"}:
            text = [
                ["" if value is None else f"{float(value):,.1f}%" for value in row]
                for row in z
            ]
        else:
            text = [
                ["" if value is None else f"{float(value):,.0f}" for value in row]
                for row in z
            ]
        colorscale = (
            "RdBu_r" if metric in {"Difference", "Percent Difference"} else "Blues"
        )
        z_values = [
            abs(float(value)) for row in z for value in row if value is not None
        ]
        zmax = max(z_values) if z_values else None
        heatmap_kwargs = {
            "z": z,
            "text": text,
            "texttemplate": "%{text}",
            "textfont": {"size": 12},
            "x": destinations,
            "y": origins,
            "colorscale": colorscale,
            "hovertemplate": (
                "Origin: %{y}<br>Destination: %{x}<br>"
                f"{metric}: %{{text}}<extra></extra>"
            ),
        }
        if metric in {"Difference", "Percent Difference"} and zmax is not None:
            heatmap_kwargs.update(zmid=0, zmin=-zmax, zmax=zmax)
        fig = go.Figure(data=go.Heatmap(**heatmap_kwargs))
        fig.update_layout(
            title=dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top"),
            height=460,
            xaxis_title="Destination",
            yaxis_title="Origin",
            margin=dict(l=70, r=20, t=80, b=70),
            font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
        )
        tabs.append((label, pn.pane.Plotly(fig, sizing_mode="stretch_width")))
    return tabs


@dashboard_page(
    page_id="regional_validation",
    title="Regional Validation",
    group_id="validation",
    order=55,
    default_enabled=False,
    optional_summary_ids=(
        "county_flows_validation_summary",
        "county_flows_joja_validation_summary",
        "commuting_flows",
    ),
)
class RegionalValidationPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self.flow_matrix_sel = self.select(
            "flow_matrix",
            "Flow Matrix",
            options=self._available_flow_options,
        )
        self.comparison_metric_sel = self.select(
            "comparison_metric",
            "Comparison Metric",
            options=FLOW_COMPARISON_OPTIONS,
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
            selectors=("flow_matrix", "comparison_metric", "include_totals"),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Regional Validation"),
            selector_row(
                self.flow_matrix_sel,
                self.comparison_metric_sel,
                self.include_totals_sel,
            ),
            self._body,
            sizing_mode="stretch_width",
        )

    def _available_flow_options(self) -> list[str]:
        options = [
            label
            for label, flow_option in FLOW_OPTIONS.items()
            if any(
                not df.is_empty()
                for _, df in nonempty(
                    self.data.summary(
                        flow_option.summary_id,
                        self.weighting_key,
                    )
                    or []
                )
            )
        ]
        return options or list(FLOW_OPTIONS)

    def render_flow_section(self) -> pn.viewable.Viewable:
        flow_label = str(self.flow_matrix_sel.value)
        flow_option = FLOW_OPTIONS[flow_label]
        observed_data = self.data.summary(
            flow_option.summary_id,
            self.weighting_key,
        )
        if observed_data is None:
            return self.data_not_available_card(
                detail="External regional flow summaries are unavailable.",
                missing_items=[flow_option.summary_id],
            )
        include_totals = bool(self.include_totals_sel.value)
        metric = str(self.comparison_metric_sel.value)
        if metric == "Observed":
            return pn.Column(
                flow_heatmap(
                    observed_data,
                    include_totals=include_totals,
                    title=f"Observed {flow_label}",
                ),
                sizing_mode="stretch_width",
            )
        modeled_data = self.data.summary(
            "commuting_flows",
            self.weighting_key,
        )
        geography_type = available_modeled_geography_type(
            modeled_data,
            flow_option.modeled_geography_types,
        )
        if modeled_data is None or geography_type is None:
            return self.data_not_available_card(
                detail=(
                    "Modeled commuting flows are unavailable for the selected "
                    "regional flow geography."
                ),
                missing_items=["commuting_flows"],
            )
        comparison_data = self.query(
            lambda: flow_comparison_data(
                observed_data,
                modeled_data,
                geography_type=geography_type,
                include_totals=include_totals,
            )
        )
        return pn.Column(
            flow_comparison_heatmap(
                comparison_data,
                metric=metric,
                title=f"{metric} {flow_label}",
            ),
            sizing_mode="stretch_width",
        )

    def render_body(self):
        if not self.state.run_labels:
            return [self.no_runs_message()]
        return [
            self.render_flow_section(),
        ]
