"""Shared chart builders, layout helpers, and color palette for ActivitySim visualizer."""

from __future__ import annotations
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
_DISPLAY_PERCENT_MODE = False


def _percent_mode(as_percent: bool | None) -> bool:
    return _DISPLAY_PERCENT_MODE if as_percent is None else bool(as_percent)


def run_color(idx: int) -> str:
    return RUN_COLORS[idx % len(RUN_COLORS)]


def set_run_colors(colors: list[str] | None) -> None:
    global RUN_COLORS
    RUN_COLORS = list(colors) if colors else list(_DEFAULT_RUN_COLORS)


def set_percent_mode(enabled: bool) -> None:
    global _DISPLAY_PERCENT_MODE
    _DISPLAY_PERCENT_MODE = bool(enabled)


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
    fig = go.Figure()
    percent_mode = _percent_mode(as_percent)
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        x = df[x_col].to_list()
        y = np.array(df[y_col].to_list(), dtype=float)
        if percent_mode and y.sum() > 0:
            y = y / y.sum() * 100.0
        y_list = y.tolist()
        yy_title = "Percent (%)" if percent_mode else yaxis_title
        hover = [
            f"{label}<br>{xaxis_title or x_col}: {xi}<br>{yy_title}: {yi:,.1f}"
            for xi, yi in zip(x, y_list)
        ]
        if pct_col and pct_col in df.columns:
            pct = df[pct_col].to_list()
            hover = [h + f"<br>Pct: {p:.1f}%" for h, p in zip(hover, pct)]
        fig.add_trace(
            go.Bar(
                name=label,
                x=x,
                y=y_list,
                marker_color=run_color(i),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover,
            )
        )
    _layout(
        fig,
        title,
        xaxis_title,
        "Percent (%)" if percent_mode else yaxis_title,
        height,
        barmode=barmode,
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
        y = np.array(df[y_col].to_list(), dtype=float)
        if percent_mode and y.sum() > 0:
            y = y / y.sum() * 100.0
        fig.add_trace(
            go.Scatter(
                name=label,
                x=df[x_col].to_list(),
                y=y.tolist(),
                mode="lines",
                line=dict(color=run_color(i), width=2),
            )
        )
    _layout(
        fig, title, xaxis_title, "Percent (%)" if percent_mode else yaxis_title, height
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
                line=dict(color=run_color(i), width=2),
                fill="tozeroy",
                fillcolor=(
                    run_color(i).replace(")", ",0.1)").replace("rgb", "rgba")
                    if "rgb" in run_color(i)
                    else None
                ),
            )
        )
    _layout(
        fig,
        title,
        xaxis_title,
        "Percent (%)" if (percent_mode or normalize) else yaxis_title,
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
        color = run_color(i)
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


def data_table(
    data_list: list[tuple[str, pl.DataFrame]],
    title: str = "",
    height: int = 300,
) -> pn.viewable.Viewable:
    """
    Display a data table. If multiple runs, show side by side.
    """
    tabs = pn.Tabs()
    for label, df in data_list:
        if df is not None and len(df) > 0:
            tabs.append(
                (
                    label,
                    pn.widgets.Tabulator(
                        _to_pandas(df),
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
