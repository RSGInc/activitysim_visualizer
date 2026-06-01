"""Shared chart builders, layout helpers, and color palette for ActivitySim visualizer."""

from __future__ import annotations
import html
import math
import panel as pn
import plotly.graph_objects as go
import polars as pl
import numpy as np

# Color palette for multiple runs (colorblind-friendly)
_DEFAULT_RUN_COLORS = [
    "#4E79A7",
    "#F28E2B",
    "#59A14F",
    "#E15759",
    "#76B7B2",
    "#EDC948",
    "#B07AA1",
    "#9C755F",
]
RUN_COLORS = list(_DEFAULT_RUN_COLORS)
RUN_LABEL_ORDER: list[str] = []
_DISPLAY_PERCENT_MODE = False


def _percent_mode(as_percent: bool | None) -> bool:
    return _DISPLAY_PERCENT_MODE if as_percent is None else bool(as_percent)


def run_color(idx: int) -> str:
    return RUN_COLORS[idx % len(RUN_COLORS)]


def run_color_for_label(label: str, fallback_idx: int) -> str:
    label_str = str(label)
    if label_str in RUN_LABEL_ORDER:
        return run_color(RUN_LABEL_ORDER.index(label_str))
    return run_color(fallback_idx)


def set_run_colors(colors: list[str] | None) -> None:
    global RUN_COLORS
    RUN_COLORS = list(colors) if colors else list(_DEFAULT_RUN_COLORS)


def set_run_label_order(labels: list[str] | None) -> None:
    global RUN_LABEL_ORDER
    RUN_LABEL_ORDER = [str(label) for label in (labels or [])]


def set_percent_mode(enabled: bool) -> None:
    global _DISPLAY_PERCENT_MODE
    _DISPLAY_PERCENT_MODE = bool(enabled)


def build_run_legend_entries(run_labels: list[str]) -> list[dict[str, str]]:
    """Return ordered run legend entries with the configured display colors."""
    return [
        {"label": str(label), "color": run_color(index)}
        for index, label in enumerate(run_labels)
    ]


def run_legend_item_html(label: str, color: str) -> str:
    """Return the shared HTML used for one run legend item."""
    safe_label = html.escape(str(label))
    safe_color = html.escape(str(color), quote=True)
    return (
        f'<div class="run-legend-item" data-run-label="{safe_label}" '
        f'data-run-color="{safe_color}" '
        f'style="padding:8px 10px;border-left:4px solid {safe_color};margin:6px 0;'
        f'border-radius:6px;background:rgba(127,127,127,0.06)">'
        f'<b style="color:{safe_color}">{safe_label}</b></div>'
    )


def build_run_legend_panes(run_labels: list[str]) -> list[pn.pane.HTML]:
    """Return sidebar-ready panes for the configured run legend."""
    return [
        pn.pane.HTML(run_legend_item_html(entry["label"], entry["color"]))
        for entry in build_run_legend_entries(run_labels)
    ]


def _layout(
    fig: go.Figure,
    title: str,
    xaxis_title: str,
    yaxis_title: str,
    height: int,
    barmode: str | None = None,
) -> None:
    layout_kwargs = dict(
        title=dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top"),
        height=height,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        legend=dict(orientation="h", yanchor="bottom", y=1.12, x=0),
        margin=dict(l=60, r=20, t=90, b=90),
        title_font=dict(size=16),
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
        hoverlabel=dict(font=dict(size=12)),
    )
    if barmode is not None:
        layout_kwargs["barmode"] = barmode
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(automargin=True, tickangle=-20)
    fig.update_yaxes(automargin=True)
    fig.update_traces(marker_line_width=0.4)


def bar_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "Count",
    barmode: str = "group",
    pct_col: str | None = None,
    height: int = 400,
    as_percent: bool | None = None,
    xaxis_categoryarray: list[object] | None = None,
) -> pn.pane.Plotly:
    """
    Create a grouped bar chart comparing multiple runs.

    Args:
        data_list: list of (run_label, DataFrame) tuples
        x_col: column for x-axis categories
        y_col: column for y-axis values
        title: chart title
        xaxis_title: x-axis label
        yaxis_title: y-axis label
        barmode: 'group' or 'stack'
        pct_col: optional column for percentage values (shown in hover)
        height: chart height in pixels
    """
    def _align_categories(
        df: pl.DataFrame,
        categories: list[object],
    ) -> pl.DataFrame:
        if x_col not in df.columns:
            return df
        category_frame = pl.DataFrame({x_col: categories}, schema={x_col: pl.Utf8})
        aligned = category_frame.join(
            df.with_columns(pl.col(x_col).cast(pl.Utf8)),
            on=x_col,
            how="left",
        )
        fill_exprs = []
        if y_col in aligned.columns:
            fill_exprs.append(pl.col(y_col).fill_null(0.0).cast(pl.Float64).alias(y_col))
        return aligned.with_columns(fill_exprs) if fill_exprs else aligned

    fig = go.Figure()
    percent_mode = _percent_mode(as_percent)
    category_order: list[object] = []
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        if xaxis_categoryarray is not None:
            df = _align_categories(df, [str(value) for value in xaxis_categoryarray])
        color = run_color_for_label(label, i)
        x = df[x_col].to_list()
        for value in x:
            if value not in category_order:
                category_order.append(value)
        y = np.array(df[y_col].to_list(), dtype=float)
        if percent_mode and y.sum() > 0:
            y = y / y.sum() * 100.0
        y_list = y.tolist()
        yy_title = f"Percent of {yaxis_title} (%)" if percent_mode else yaxis_title
        hover = [
            f"{label}<br>{xaxis_title or x_col}: {xi}<br>{yy_title}: {yi:,.1f}"
            for xi, yi in zip(x, y_list)
        ]
        fig.add_trace(
            go.Bar(
                name=label,
                x=x,
                y=y_list,
                marker_color=color,
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover,
            )
        )
    _layout(
        fig,
        title,
        xaxis_title,
        f"Percent of {yaxis_title} (%)" if percent_mode else yaxis_title,
        height,
        barmode=barmode,
    )
    final_category_order = xaxis_categoryarray or category_order
    if final_category_order:
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=final_category_order,
        )
    return pn.pane.Plotly(fig, sizing_mode="stretch_width")


def line_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    height: int = 350,
    as_percent: bool | None = None,
) -> pn.pane.Plotly:
    """Create an overlaid line chart for density/profile comparisons."""
    fig = go.Figure()
    percent_mode = _percent_mode(as_percent)
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        color = run_color_for_label(label, i)
        y = np.array(df[y_col].to_list(), dtype=float)
        if percent_mode and y.sum() > 0:
            y = y / y.sum() * 100.0
        fig.add_trace(
            go.Scatter(
                name=label,
                x=df[x_col].to_list(),
                y=y.tolist(),
                mode="lines",
                line=dict(color=color, width=2),
            )
        )
    _layout(
        fig,
        title,
        xaxis_title,
        f"Percent of {yaxis_title} (%)" if percent_mode else yaxis_title,
        height,
    )
    return pn.pane.Plotly(fig, sizing_mode="stretch_width")


def density_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "Frequency",
    normalize: bool = False,
    height: int = 350,
    as_percent: bool | None = None,
    xaxis_range: tuple[float, float] | None = None,
    xaxis_categoryarray: list[object] | None = None,
    xaxis_tickvals: list[object] | None = None,
    xaxis_ticktext: list[str] | None = None,
) -> pn.pane.Plotly:
    """
    Create an overlaid density/histogram line chart.
    If normalize=True, convert to proportions (sum=100%).
    """
    fig = go.Figure()
    percent_mode = _percent_mode(as_percent)
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        color = run_color_for_label(label, i)
        x = df[x_col].to_list()
        y = np.array(df[y_col].to_list(), dtype=float)
        if (percent_mode or normalize) and y.sum() > 0:
            y = y / y.sum() * 100
        fig.add_trace(
            go.Scatter(
                name=label,
                x=x,
                y=y.tolist(),
                mode="lines",
                line=dict(color=color, width=2),
                fill="tozeroy",
                fillcolor=(
                    color.replace(")", ",0.1)").replace("rgb", "rgba")
                    if "rgb" in color
                    else None
                ),
            )
        )
    _layout(
        fig,
        title,
        xaxis_title,
        f"Percent of {yaxis_title} (%)" if (percent_mode or normalize) else yaxis_title,
        height,
    )
    if xaxis_range is not None:
        fig.update_xaxes(range=[float(xaxis_range[0]), float(xaxis_range[1])])
    if xaxis_categoryarray is not None:
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=xaxis_categoryarray,
        )
    if xaxis_tickvals is not None:
        tick_kwargs = {"tickmode": "array", "tickvals": xaxis_tickvals}
        if xaxis_ticktext is not None:
            tick_kwargs["ticktext"] = xaxis_ticktext
        fig.update_xaxes(**tick_kwargs)
    return pn.pane.Plotly(fig, sizing_mode="stretch_width")


# TODO: Consider changing to a grid of plots
def scatter_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    height: int = 400,
    drop_zero_y: bool = False,
) -> pn.pane.Plotly:
    """Create a scatterplot comparing multiple runs."""
    fig = go.Figure()

    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        if drop_zero_y and y_col in df.columns:
            df = df.filter(pl.col(y_col).fill_null(0) != 0)
            if len(df) == 0:
                continue
        color = run_color_for_label(label, i)

        x = df[x_col].to_list()
        y = df[y_col].to_list()

        hover = [
            f"{label}<br>{xaxis_title or x_col}: {xi:,.1f}<br>{yaxis_title or y_col}: {yi:,.1f}"
            for xi, yi in zip(x, y)
        ]

        fig.add_trace(
            go.Scatter(
                name=label,
                x=x,
                y=y,
                mode="markers",
                marker=dict(
                    color=color,
                    size=8,
                    line=dict(width=0.4),
                ),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover,
            )
        )

    _layout(
        fig,
        title,
        xaxis_title,
        yaxis_title,
        height,
    )

    return pn.pane.Plotly(fig, sizing_mode="stretch_width")


def kpi_box(
    label: str, values: list[tuple[str, float]], format_fn=None, icon: str = ""
) -> pn.viewable.Viewable:
    """
    Create a KPI value box showing the metric for each run.

    Args:
        label: metric name
        values: list of (run_label, value) tuples
        format_fn: optional formatter function
    """
    if format_fn is None:
        format_fn = lambda v: f"{v:,.0f}"
    max_v = max([v for _, v in values], default=0) or 1

    items = []
    for i, (run_label, val) in enumerate(values):
        color = run_color_for_label(run_label, i)
        mini = int((float(val) / max_v) * 100)
        items.append(
            pn.pane.HTML(
                f"""<div style="padding:10px 12px;border-left:4px solid {color};margin:6px 0;border-radius:6px;background:rgba(127,127,127,0.06)">
                <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em">{run_label}</div>
                <div style="font-size:22px;font-weight:700;color:{color};line-height:1.1">{format_fn(val)}</div>
                <div style="height:5px;border-radius:3px;background:rgba(0,0,0,0.08);margin-top:6px;">
                  <div style="width:{mini}%;height:5px;border-radius:3px;background:{color};"></div>
                </div>
             </div>"""
            )
        )

    return pn.Card(
        *items,
        title=f"{icon}  {label}" if icon else label,
        sizing_mode="stretch_width",
        min_width=260,
        styles={"border-radius": "10px"},
    )


def _to_pandas(df: pl.DataFrame):
    """Convert Polars DataFrame to pandas, casting categoricals to strings first."""
    cat_cols = [c for c in df.columns if df[c].dtype == pl.Categorical]
    if cat_cols:
        df = df.with_columns([pl.col(c).cast(pl.Utf8) for c in cat_cols])
    return df.to_pandas()


def format_numeric_for_display(
    value,
    *,
    precision: int | None = 2,
):
    """Format numbers using significant digits while preserving integers.

    `precision` means significant digits, not fixed decimal places.
    """
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return value
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        if numeric.is_integer():
            return str(int(numeric))
        if precision is None:
            return str(numeric)
        if precision <= 0:
            return str(int(round(numeric)))
        magnitude = math.floor(math.log10(abs(numeric)))
        decimals = precision - 1 - magnitude
        rounded = round(numeric, decimals)
        if float(rounded).is_integer():
            return str(int(rounded))
        decimal_places = max(decimals, 0)
        return f"{rounded:.{decimal_places}f}".rstrip("0").rstrip(".")
    return value


def format_numeric_frame_for_display(
    df: pl.DataFrame,
    *,
    numeric_precision: int | None = 2,
    numeric_precision_by_column: dict[str, int] | None = None,
) -> pl.DataFrame:
    """Return a copy with numeric columns converted to display-ready strings."""
    if numeric_precision is None and not numeric_precision_by_column:
        return df
    exprs: list[pl.Expr] = []
    for column, dtype in df.schema.items():
        if not getattr(dtype, "is_numeric", lambda: False)():
            continue
        column_precision = (
            numeric_precision_by_column.get(column)
            if numeric_precision_by_column and column in numeric_precision_by_column
            else numeric_precision
        )
        exprs.append(
            pl.col(column)
            .map_elements(
                lambda value, precision=column_precision: format_numeric_for_display(
                    value,
                    precision=precision,
                ),
                return_dtype=pl.Utf8,
            )
            .alias(column)
        )
    return df.with_columns(exprs) if exprs else df


def data_table(
    data_list: list[tuple[str, pl.DataFrame]],
    title: str = "",
    height: int = 300,
    numeric_precision: int | None = 2,
    numeric_precision_by_column: dict[str, int] | None = None,
) -> pn.viewable.Viewable:
    """
    Display a data table. If multiple runs, show side by side.
    """
    tabs = pn.Tabs()
    for label, df in data_list:
        if df is not None and len(df) > 0:
            display_df = format_numeric_frame_for_display(
                df,
                numeric_precision=numeric_precision,
                numeric_precision_by_column=numeric_precision_by_column,
            )
            tabs.append(
                (
                    label,
                    pn.widgets.Tabulator(
                        _to_pandas(display_df),
                        height=height,
                        sizing_mode="stretch_width",
                        theme="simple",
                    ),
                )
            )
    if title:
        return pn.Column(pn.pane.Markdown(f"### {title}"), tabs)
    return tabs


def get_standard_df(
    data_list: list[tuple[str, pl.DataFrame]],
    key_col: str,
    val_col: str,
) -> list[tuple[str, pl.DataFrame]]:
    """
    Normalize DataFrames across runs to same key set.
    Fills missing keys with 0.
    """
    if not data_list:
        return []
    all_keys = set()
    for _, df in data_list:
        if df is not None:
            all_keys.update(df[key_col].to_list())

    result = []
    for label, df in data_list:
        if df is None:
            df = pl.DataFrame({key_col: list(all_keys), val_col: [0.0] * len(all_keys)})
        else:
            base = pl.DataFrame({key_col: list(all_keys)})
            df = base.join(
                df.select([key_col, val_col]), on=key_col, how="left"
            ).fill_null(0)
        result.append((label, df.sort(key_col)))
    return result


def purpose_selector(
    purposes: list[str], name: str = "purpose_select"
) -> pn.widgets.Select:
    return pn.widgets.Select(name=name, options=purposes, value=purposes[0])


def district_selector(
    districts: list[str], name: str = "district_select"
) -> pn.widgets.Select:
    all_opts = ["All"] + districts
    return pn.widgets.Select(name=name, options=all_opts, value="All")


def data_unavailable_card(
    title: str,
    detail: str,
    missing_items: list[str] | tuple[str, ...] | None = None,
) -> pn.Card:
    """Return a standard placeholder card for unavailable page data."""
    detail_lines = [detail]
    if missing_items:
        detail_lines.append("")
        detail_lines.append("Required inputs:")
        detail_lines.extend(f"- `{item}`" for item in missing_items)
    return pn.Card(
        pn.pane.Markdown("\n".join(detail_lines)),
        title=title,
        sizing_mode="stretch_width",
        styles={"border-radius": "10px"},
    )


def control_row(*objects, height: int = 56) -> pn.Row:
    """Return a standard fixed-height control row for chart alignment."""
    return pn.Row(
        *objects,
        sizing_mode="stretch_width",
        min_height=height,
        height=height,
        margin=(0, 0, 8, 0),
    )


def control_row_spacer(height: int = 56) -> pn.pane.HTML:
    """Return a blank fixed-height row used to align sibling plots."""
    return pn.pane.HTML(
        f"<div style='height:{int(height)}px'></div>",
        sizing_mode="stretch_width",
        margin=(0, 0, 8, 0),
    )
