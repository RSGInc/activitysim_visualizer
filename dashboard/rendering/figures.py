"""Plotly figure construction without Panel or process-global state."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import plotly.graph_objects as go
import polars as pl

from dashboard.data_access import RunTableData, RunTables
from dashboard.rendering.context import RenderContext

ChartTables = RunTables | RunTableData
ChartValueMode = Literal["dashboard", "count", "share"]


def _share_mode(context: RenderContext, value_mode: ChartValueMode) -> bool:
    return context.value_mode == "share" if value_mode == "dashboard" else value_mode == "share"


def _require_columns(data: ChartTables, chart: str, *columns: str) -> None:
    for label, frame in data:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(
                f"{chart} chart for run {label!r} is missing columns: {', '.join(missing)}"
            )


def _layout(
    figure: go.Figure,
    *,
    title: str,
    x_title: str,
    y_title: str,
    height: int,
    barmode: str | None = None,
) -> None:
    kwargs = {
        "title": dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top"),
        "height": height,
        "xaxis_title": x_title,
        "yaxis_title": y_title,
        "legend": dict(orientation="h", yanchor="bottom", y=1.12, x=0),
        "margin": dict(l=60, r=20, t=90, b=90),
        "title_font": dict(size=16),
        "font": dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
        "hoverlabel": dict(font=dict(size=12)),
    }
    if barmode is not None:
        kwargs["barmode"] = barmode
    figure.update_layout(**kwargs)
    figure.update_xaxes(automargin=True, tickangle=-20)
    figure.update_yaxes(automargin=True)
    figure.update_traces(marker_line_width=0.4)


def _y_title(title: str, share: bool) -> str:
    return f"Percent of {title} (%)" if share else title


def _hover_value(value: float, y_title: str, share: bool) -> str:
    if share:
        return f"{value:,.2f}%"
    if str(y_title).strip().lower() in {"trips", "tours", "stops"}:
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _point_hover(
    label: str,
    x_value: object,
    y_value: float,
    *,
    x: str,
    y: str,
    x_title: str,
    y_title: str,
    share: bool,
) -> str:
    return (
        f"{label}<br>{x_title or x}: {x_value}"
        f"<br>{_y_title(y_title or y, share)}: {_hover_value(y_value, y_title, share)}"
    )


def bar_figure(
    context: RenderContext,
    data: ChartTables,
    *,
    x: str,
    y: str,
    title: str = "",
    x_title: str = "",
    y_title: str = "Count",
    barmode: str = "group",
    share_y: str | None = None,
    value_mode: ChartValueMode = "dashboard",
    height: int = 400,
    category_order: list[object] | None = None,
    show_legend: bool | None = None,
) -> go.Figure:
    """Build a grouped/stacked categorical figure."""
    _require_columns(data, "bar", x, y)
    share = _share_mode(context, value_mode)
    figure = go.Figure()
    observed_order: list[object] = []
    for index, (label, frame) in enumerate(data):
        if frame.is_empty():
            continue
        if category_order is not None:
            category_frame = pl.DataFrame({x: [str(value) for value in category_order]})
            frame = category_frame.join(
                frame.with_columns(pl.col(x).cast(pl.Utf8)), on=x, how="left"
            )
            fill = [pl.col(y).fill_null(0.0).cast(pl.Float64)]
            if share_y and share_y in frame.columns:
                fill.append(pl.col(share_y).fill_null(0.0).cast(pl.Float64))
            frame = frame.with_columns(fill)
        x_values = frame[x].to_list()
        observed_order.extend(value for value in x_values if value not in observed_order)
        source = share_y if share and share_y and share_y in frame.columns else y
        values = np.asarray(frame[source].to_list(), dtype=float)
        if share and source == y and values.sum() > 0:
            values = values / values.sum() * 100.0
        y_values = values.tolist()
        hover = [
            _point_hover(
                str(label), x_value, y_value, x=x, y=y,
                x_title=x_title, y_title=y_title, share=share,
            )
            for x_value, y_value in zip(x_values, y_values)
        ]
        figure.add_trace(
            go.Bar(
                name=str(label), x=x_values, y=y_values,
                marker_color=context.color(str(label), index),
                hovertemplate="%{customdata}<extra></extra>", customdata=hover,
            )
        )
    _layout(
        figure, title=title, x_title=x_title,
        y_title=_y_title(y_title, share), height=height, barmode=barmode,
    )
    if context.bar_hover_mode == "all":
        figure.update_layout(hovermode="x unified")
    if show_legend is not None:
        figure.update_layout(showlegend=show_legend)
    final_order = category_order or observed_order
    if final_order:
        figure.update_xaxes(type="category", categoryorder="array", categoryarray=final_order)
    return figure


def line_figure(
    context: RenderContext,
    data: ChartTables,
    *,
    x: str,
    y: str,
    title: str = "",
    x_title: str = "",
    y_title: str = "",
    value_mode: ChartValueMode = "dashboard",
    height: int = 350,
) -> go.Figure:
    _require_columns(data, "line", x, y)
    share = _share_mode(context, value_mode)
    figure = go.Figure()
    for index, (label, frame) in enumerate(data):
        values = np.asarray(frame[y].to_list(), dtype=float)
        if share and values.sum() > 0:
            values = values / values.sum() * 100.0
        figure.add_trace(go.Scatter(
            name=str(label), x=frame[x].to_list(), y=values.tolist(), mode="lines",
            line=dict(color=context.color(str(label), index), width=2),
        ))
    _layout(figure, title=title, x_title=x_title, y_title=_y_title(y_title, share), height=height)
    return figure


def _clock_ticks(values: list[object]) -> tuple[list[str], list[str]] | None:
    parsed = []
    for value in dict.fromkeys(str(value) for value in values):
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return None
        hour, minute = map(int, parts)
        if hour > 23 or minute not in {0, 30}:
            return None
        parsed.append((value, hour, minute))
    tick_values = [value for value, _, minute in parsed if minute == 0]
    return (tick_values, [f"{hour}:00" for _, hour, minute in parsed if minute == 0]) if tick_values else None


def density_figure(
    context: RenderContext,
    data: ChartTables,
    *,
    x: str,
    y: str,
    title: str = "",
    x_title: str = "",
    y_title: str = "Frequency",
    value_mode: ChartValueMode = "dashboard",
    height: int = 350,
    x_range: tuple[float, float] | None = None,
    category_order: list[object] | None = None,
    tick_values: list[object] | None = None,
    tick_text: list[str] | None = None,
    hover_x_title: str | None = None,
) -> go.Figure:
    _require_columns(data, "density", x, y)
    share = _share_mode(context, value_mode)
    figure = go.Figure()
    observed_x: list[object] = []
    for index, (label, frame) in enumerate(data):
        x_values = frame[x].to_list()
        observed_x.extend(x_values)
        values = np.asarray(frame[y].to_list(), dtype=float)
        if share and values.sum() > 0:
            values = values / values.sum() * 100.0
        y_values = values.tolist()
        color = context.color(str(label), index)
        hover = [
            _point_hover(str(label), xv, yv, x=x, y=y,
                         x_title=hover_x_title or x_title, y_title=y_title, share=share)
            for xv, yv in zip(x_values, y_values)
        ]
        figure.add_trace(go.Scatter(
            name=str(label), x=x_values, y=y_values, mode="lines",
            line=dict(color=color, width=2), fill="tozeroy",
            hovertemplate="%{customdata}<extra></extra>", customdata=hover,
        ))
    _layout(figure, title=title, x_title=x_title, y_title=_y_title(y_title, share), height=height)
    if context.density_hover_mode == "all":
        figure.update_layout(hovermode="x unified")
    if x_range is not None:
        figure.update_xaxes(range=[float(x_range[0]), float(x_range[1])])
    if category_order is not None:
        figure.update_xaxes(type="category", categoryorder="array", categoryarray=category_order)
    if tick_values is not None:
        kwargs = {"tickmode": "array", "tickvals": tick_values}
        if tick_text is not None:
            kwargs["ticktext"] = tick_text
        figure.update_xaxes(**kwargs)
    elif ticks := _clock_ticks(observed_x):
        figure.update_xaxes(tickmode="array", tickvals=ticks[0], ticktext=ticks[1])
    return figure


def _finite(values: list[object]) -> list[float]:
    output = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append(number)
    return output


def scatter_figure(
    context: RenderContext,
    data: ChartTables,
    *,
    x: str,
    y: str,
    title: str = "",
    x_title: str = "",
    y_title: str = "",
    height: int = 400,
    drop_zero_y: bool = False,
    fit_overlays: ChartTables | None = None,
    fit_annotation: str = "annotation",
    one_to_one: bool = False,
) -> go.Figure:
    _require_columns(data, "scatter", x, y)
    figure = go.Figure()
    label_indices = {str(label): index for index, (label, _) in enumerate(data)}
    axis_values: list[float] = []
    for index, (label, frame) in enumerate(data):
        if drop_zero_y:
            frame = frame.filter(pl.col(y).fill_null(0) != 0)
        if frame.is_empty():
            continue
        x_values, y_values = frame[x].to_list(), frame[y].to_list()
        if one_to_one:
            axis_values.extend(_finite([*x_values, *y_values]))
        figure.add_trace(go.Scatter(
            name=str(label), x=x_values, y=y_values, mode="markers",
            marker=dict(color=context.color(str(label), index), size=8, line=dict(width=0.4)),
        ))
    for index, (label, frame) in enumerate(fit_overlays or []):
        if frame.is_empty() or x not in frame.columns or y not in frame.columns:
            continue
        color = context.color(str(label), label_indices.get(str(label), index))
        figure.add_trace(go.Scatter(
            name=f"{label} fit", x=frame[x].to_list(), y=frame[y].to_list(),
            mode="lines", line=dict(color=color, width=2),
        ))
        if fit_annotation in frame.columns and str(frame[fit_annotation][0] or "").strip():
            figure.add_annotation(
                text=str(frame[fit_annotation][0]), xref="paper", yref="paper",
                x=0.02, y=max(0.05, 0.98 - 0.12 * index), showarrow=False,
                font=dict(color=color, size=12), bgcolor="rgba(255,255,255,0.75)",
                bordercolor=color, borderwidth=1,
            )
    if one_to_one:
        maximum = max([value for value in axis_values if value >= 0], default=1.0) or 1.0
        figure.add_trace(go.Scatter(
            name="1:1 line", x=[0.0, maximum], y=[0.0, maximum], mode="lines",
            line=dict(color="#BDBDBD", width=1.5, dash="dash"),
            hoverinfo="skip", showlegend=False,
        ))
    _layout(figure, title=title, x_title=x_title, y_title=y_title, height=height)
    return figure
