"""UI-neutral Plotly figure helpers for the Quarto migration."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import plotly.graph_objects as go
import polars as pl

from quarto_visualizer.summary_bundle import RunFrameList

DEFAULT_RUN_COLORS = (
    "#4E79A7",
    "#F28E2B",
    "#59A14F",
    "#E15759",
    "#76B7B2",
    "#EDC948",
    "#B07AA1",
    "#9C755F",
)


def resolve_run_colors(run_colors: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(run_colors) if run_colors else DEFAULT_RUN_COLORS


def run_color(index: int, run_colors: Sequence[str] | None = None) -> str:
    colors = resolve_run_colors(run_colors)
    return colors[index % len(colors)]


def make_empty_figure(message: str = "No data available") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, showarrow=False, xref="paper", yref="paper")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=40, b=20), height=280)
    return fig


def make_bar_figure(
    frames: RunFrameList,
    x_col: str,
    y_col: str,
    *,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "Count",
    barmode: str = "group",
    pct_col: str | None = None,
    height: int = 400,
    value_mode: str = "Count",
    run_colors: Sequence[str] | None = None,
) -> go.Figure:
    fig = go.Figure()
    colors = resolve_run_colors(run_colors)
    percent_mode = _is_percent_mode(value_mode)

    for idx, (label, df) in enumerate(frames):
        if df is None or len(df) == 0 or x_col not in df.columns or y_col not in df.columns:
            continue
        x_vals = df[x_col].to_list()
        y_vals = _display_values(df[y_col].to_list(), percent_mode=percent_mode)
        hover_title = "Percent (%)" if percent_mode else yaxis_title
        hover = [f"{label}<br>{xaxis_title or x_col}: {x}<br>{hover_title}: {y:,.1f}" for x, y in zip(x_vals, y_vals)]
        if pct_col and pct_col in df.columns:
            pct_vals = df[pct_col].to_list()
            hover = [f"{h}<br>Pct: {p:.1f}%" for h, p in zip(hover, pct_vals)]
        fig.add_trace(
            go.Bar(
                name=label,
                x=x_vals,
                y=y_vals,
                marker_color=run_color(idx, colors),
                customdata=hover,
                hovertemplate="%{customdata}<extra></extra>",
            )
        )

    if not fig.data:
        return make_empty_figure()

    _apply_layout(
        fig,
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title="Percent (%)" if percent_mode else yaxis_title,
        height=height,
        barmode=barmode,
    )
    return fig


def make_line_figure(
    frames: RunFrameList,
    x_col: str,
    y_col: str,
    *,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    height: int = 350,
    value_mode: str = "Count",
    run_colors: Sequence[str] | None = None,
) -> go.Figure:
    fig = go.Figure()
    colors = resolve_run_colors(run_colors)
    percent_mode = _is_percent_mode(value_mode)

    for idx, (label, df) in enumerate(frames):
        if df is None or len(df) == 0 or x_col not in df.columns or y_col not in df.columns:
            continue
        y_vals = _display_values(df[y_col].to_list(), percent_mode=percent_mode)
        fig.add_trace(
            go.Scatter(
                name=label,
                x=df[x_col].to_list(),
                y=y_vals,
                mode="lines",
                line=dict(color=run_color(idx, colors), width=2),
            )
        )

    if not fig.data:
        return make_empty_figure()

    _apply_layout(
        fig,
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title="Percent (%)" if percent_mode else yaxis_title,
        height=height,
    )
    return fig


def make_density_figure(
    frames: RunFrameList,
    x_col: str,
    y_col: str,
    *,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "Frequency",
    normalize: bool = True,
    height: int = 350,
    value_mode: str = "Count",
    run_colors: Sequence[str] | None = None,
) -> go.Figure:
    fig = go.Figure()
    colors = resolve_run_colors(run_colors)
    percent_mode = _is_percent_mode(value_mode) or normalize

    for idx, (label, df) in enumerate(frames):
        if df is None or len(df) == 0 or x_col not in df.columns or y_col not in df.columns:
            continue
        color = run_color(idx, colors)
        y_vals = _display_values(df[y_col].to_list(), percent_mode=percent_mode)
        fig.add_trace(
            go.Scatter(
                name=label,
                x=df[x_col].to_list(),
                y=y_vals,
                mode="lines",
                line=dict(color=color, width=2),
                fill="tozeroy",
                fillcolor=_with_alpha(color, 0.12),
            )
        )

    if not fig.data:
        return make_empty_figure()

    _apply_layout(
        fig,
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title="Percent (%)" if percent_mode else yaxis_title,
        height=height,
    )
    return fig


def _apply_layout(
    fig: go.Figure,
    *,
    title: str,
    xaxis_title: str,
    yaxis_title: str,
    height: int,
    barmode: str | None = None,
) -> None:
    layout_kwargs: dict[str, object] = {
        "template": "plotly_white",
        "title": dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top"),
        "height": height,
        "xaxis_title": xaxis_title,
        "yaxis_title": yaxis_title,
        "legend": dict(orientation="h", yanchor="bottom", y=1.12, x=0),
        "margin": dict(l=60, r=20, t=90, b=90),
        "title_font": dict(size=16),
        "font": dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
        "hoverlabel": dict(font=dict(size=12)),
    }
    if barmode is not None:
        layout_kwargs["barmode"] = barmode
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(automargin=True, tickangle=-20)
    fig.update_yaxes(automargin=True)
    fig.update_traces(marker_line_width=0.4)


def _display_values(values: Sequence[object], *, percent_mode: bool) -> list[float]:
    numeric = np.array(values, dtype=float)
    if percent_mode and numeric.sum() > 0:
        numeric = numeric / numeric.sum() * 100.0
    return numeric.tolist()


def _is_percent_mode(value_mode: str) -> bool:
    return str(value_mode).strip().lower() == "percent"


def _with_alpha(color: str, alpha: float) -> str | None:
    if color.startswith("#") and len(color) == 7:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return f"rgba({r},{g},{b},{alpha})"
    if color.startswith("rgb(") and color.endswith(")"):
        return color.replace("rgb(", "rgba(").replace(")", f",{alpha})")
    return None
