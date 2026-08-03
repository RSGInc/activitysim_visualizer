"""Run-aware cards, legends, and small Panel layout helpers."""

from __future__ import annotations

import html

import panel as pn

from dashboard.rendering.context import RenderContext


def run_legend_entries(
    context: RenderContext,
    run_labels: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    labels = tuple(str(label) for label in (run_labels or context.run_labels))
    return [
        {"label": label, "color": context.color(label, index)}
        for index, label in enumerate(labels)
    ]


def _legend_html(label: str, color: str) -> str:
    safe_label = html.escape(label)
    safe_color = html.escape(color, quote=True)
    return (
        f'<div class="run-legend-item" data-run-label="{safe_label}" '
        f'data-run-color="{safe_color}" '
        f'style="padding:8px 10px;border-left:4px solid {safe_color};margin:6px 0;'
        f'border-radius:6px;background:rgba(127,127,127,0.06)">'
        f'<b style="color:{safe_color}">{safe_label}</b></div>'
    )


def run_legend_panes(context: RenderContext) -> list[pn.pane.HTML]:
    return [
        pn.pane.HTML(_legend_html(entry["label"], entry["color"]))
        for entry in run_legend_entries(context)
    ]


def kpi_box(
    context: RenderContext,
    label: str,
    values: list[tuple[str, float]],
    format_fn=None,
    icon: str = "",
) -> pn.viewable.Viewable:
    if format_fn is None:
        format_fn = lambda value: f"{value:,.0f}"
    maximum = max([value for _, value in values], default=0) or 1
    items = []
    for index, (run_label, value) in enumerate(values):
        color = context.color(run_label, index)
        width = int((float(value) / maximum) * 100)
        items.append(pn.pane.HTML(
            f'<div style="padding:10px 12px;border-left:4px solid {color};margin:6px 0;'
            f'border-radius:6px;background:rgba(127,127,127,0.06)">'
            f'<div style="font-size:11px;color:#6b7280;text-transform:uppercase">{run_label}</div>'
            f'<div style="font-size:22px;font-weight:700;color:{color}">{format_fn(value)}</div>'
            f'<div style="height:5px;background:rgba(0,0,0,0.08);margin-top:6px">'
            f'<div style="width:{width}%;height:5px;background:{color}"></div></div></div>'
        ))
    return pn.Card(
        *items,
        title=f"{icon}  {label}" if icon else label,
        sizing_mode="stretch_width",
        min_width=260,
        styles={"border-radius": "10px"},
    )


def data_unavailable_card(
    title: str,
    detail: str,
    missing_items: list[str] | tuple[str, ...] | None = None,
) -> pn.Card:
    lines = [detail]
    if missing_items:
        lines.extend(("", "Required inputs:", *(f"- `{item}`" for item in missing_items)))
    return pn.Card(
        pn.pane.Markdown("\n".join(lines)),
        title=title,
        sizing_mode="stretch_width",
        styles={"border-radius": "10px"},
    )


def control_row(*objects, height: int = 72) -> pn.Row:
    return pn.Row(
        *objects,
        sizing_mode="stretch_width",
        min_height=height,
        margin=(0, 0, 8, 0),
        styles={
            "justify-content": "flex-end",
            "align-items": "flex-start",
            "flex-wrap": "wrap",
            "row-gap": "8px",
            "column-gap": "12px",
        },
    )


def selector_row(*objects, height: int = 72) -> pn.Row:
    return control_row(*objects, height=height)


def control_row_spacer(height: int = 56) -> pn.pane.HTML:
    return pn.pane.HTML(
        f"<div style='height:{int(height)}px'></div>",
        sizing_mode="stretch_width",
        margin=(0, 0, 8, 0),
    )
