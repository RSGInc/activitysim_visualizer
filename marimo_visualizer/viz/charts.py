"""Shared Plotly chart builders for the marimo ActivitySim visualizer."""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import plotly.graph_objects as go
import polars as pl

from .models import DEFAULT_RUN_COLORS


def run_color(idx: int, run_colors: Sequence[str] | None = None) -> str:
    """Return the configured color for a run index."""
    palette = list(run_colors) if run_colors else list(DEFAULT_RUN_COLORS)
    return palette[idx % len(palette)]


def apply_standard_layout(
    fig: go.Figure,
    title: str,
    xaxis_title: str,
    yaxis_title: str,
    height: int,
    barmode: str | None = None,
) -> go.Figure:
    """Apply the shared Plotly layout used across charts."""
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
    return fig


def bar_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "Count",
    as_percent: bool = False,
    run_colors: Sequence[str] | None = None,
    barmode: str = "group",
    pct_col: str | None = None,
    height: int = 400,
) -> go.Figure:
    """Create a grouped bar chart comparing multiple runs."""
    fig = go.Figure()
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        x = df[x_col].to_list()
        y = np.array(df[y_col].to_list(), dtype=float)
        if as_percent and y.sum() > 0:
            y = y / y.sum() * 100.0
        y_list = y.tolist()
        yy_title = "Percent (%)" if as_percent else yaxis_title
        hover = [f"{label}<br>{xaxis_title or x_col}: {xi}<br>{yy_title}: {yi:,.1f}" for xi, yi in zip(x, y_list)]
        if pct_col and pct_col in df.columns:
            pct_vals = df[pct_col].to_list()
            hover = [h + f"<br>Pct: {pct:.1f}%" for h, pct in zip(hover, pct_vals)]
        fig.add_trace(
            go.Bar(
                name=label,
                x=x,
                y=y_list,
                marker_color=run_color(i, run_colors),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover,
            )
        )
    return apply_standard_layout(fig, title, xaxis_title, "Percent (%)" if as_percent else yaxis_title, height, barmode=barmode)


def line_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    as_percent: bool = False,
    run_colors: Sequence[str] | None = None,
    height: int = 350,
) -> go.Figure:
    """Create an overlaid line chart for profile comparisons."""
    fig = go.Figure()
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        y = np.array(df[y_col].to_list(), dtype=float)
        if as_percent and y.sum() > 0:
            y = y / y.sum() * 100.0
        fig.add_trace(
            go.Scatter(
                name=label,
                x=df[x_col].to_list(),
                y=y.tolist(),
                mode="lines",
                line=dict(color=run_color(i, run_colors), width=2),
            )
        )
    return apply_standard_layout(fig, title, xaxis_title, "Percent (%)" if as_percent else yaxis_title, height)


def density_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "Frequency",
    as_percent: bool = False,
    run_colors: Sequence[str] | None = None,
    normalize: bool = True,
    height: int = 350,
) -> go.Figure:
    """Create an overlaid density chart.

    This intentionally preserves the current Panel behavior:
    if `normalize=True`, the chart is normalized even when `as_percent=False`.
    """
    fig = go.Figure()
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        x = df[x_col].to_list()
        y = np.array(df[y_col].to_list(), dtype=float)
        if (as_percent or normalize) and y.sum() > 0:
            y = y / y.sum() * 100.0
        color = run_color(i, run_colors)
        fig.add_trace(
            go.Scatter(
                name=label,
                x=x,
                y=y.tolist(),
                mode="lines",
                line=dict(color=color, width=2),
                fill="tozeroy",
                fillcolor=_hex_to_rgba(color, 0.12),
            )
        )
    y_title = "Percent (%)" if (as_percent or normalize) else yaxis_title
    return apply_standard_layout(fig, title, xaxis_title, y_title, height)


def kpi_card_html(
    label: str,
    values: list[tuple[str, float]],
    run_colors: Sequence[str] | None = None,
    format_fn: Callable[[float], str] | None = None,
    icon: str = "",
) -> str:
    """Return a lightweight HTML KPI card for later marimo layout composition."""
    if format_fn is None:
        format_fn = lambda value: f"{value:,.0f}"
    max_v = max([value for _, value in values], default=0) or 1

    items: list[str] = []
    for i, (run_label, value) in enumerate(values):
        color = run_color(i, run_colors)
        mini = int((float(value) / max_v) * 100)
        items.append(
            (
                f"<div style=\"padding:10px 12px;border-left:4px solid {color};margin:6px 0;"
                f"border-radius:6px;background:rgba(127,127,127,0.06)\">"
                f"<div style=\"font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em\">{run_label}</div>"
                f"<div style=\"font-size:22px;font-weight:700;color:{color};line-height:1.1\">{format_fn(value)}</div>"
                f"<div style=\"height:5px;border-radius:3px;background:rgba(0,0,0,0.08);margin-top:6px;\">"
                f"<div style=\"width:{mini}%;height:5px;border-radius:3px;background:{color};\"></div>"
                "</div></div>"
            )
        )

    title = f"{icon} {label}".strip()
    return (
        "<div style=\"border:1px solid rgba(0,0,0,0.08);border-radius:10px;padding:8px 12px;\">"
        f"<div style=\"font-size:16px;font-weight:700;margin-bottom:6px;\">{title}</div>"
        f"{''.join(items)}"
        "</div>"
    )


def _hex_to_rgba(color: str, alpha: float) -> str | None:
    """Convert a hex color to an rgba() string for Plotly fills."""
    if not color.startswith("#") or len(color) not in (4, 7):
        return None
    if len(color) == 4:
        color = "#" + "".join(ch * 2 for ch in color[1:])
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"
