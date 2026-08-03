"""Panel adapters over the figure-first plotting API."""

from __future__ import annotations

import panel as pn

from dashboard.rendering.context import RenderContext
import dashboard.rendering.figures as figures
from dashboard.rendering.layout import kpi_box


class FigureBuilder:
    """Build testable Plotly figures using one immutable render context."""

    def __init__(self, context: RenderContext) -> None:
        self.context = context

    def bar(self, data, **kwargs):
        return figures.bar_figure(self.context, data, **kwargs)

    def line(self, data, **kwargs):
        return figures.line_figure(self.context, data, **kwargs)

    def density(self, data, **kwargs):
        return figures.density_figure(self.context, data, **kwargs)

    def scatter(self, data, **kwargs):
        return figures.scatter_figure(self.context, data, **kwargs)


class Plotter:
    """Concise page plotting API with an explicit figure escape hatch."""

    def __init__(self, context: RenderContext) -> None:
        self.context = context
        self.figure = FigureBuilder(context)

    @staticmethod
    def panel(figure, *, aspect_ratio: float | None = None) -> pn.pane.Plotly:
        if aspect_ratio is not None:
            return pn.pane.Plotly(
                figure,
                sizing_mode="scale_width",
                aspect_ratio=aspect_ratio,
            )
        return pn.pane.Plotly(figure, sizing_mode="stretch_width")

    def bar(self, data, **kwargs) -> pn.pane.Plotly:
        return self.panel(self.figure.bar(data, **kwargs))

    def line(self, data, **kwargs) -> pn.pane.Plotly:
        return self.panel(self.figure.line(data, **kwargs))

    def density(self, data, **kwargs) -> pn.pane.Plotly:
        return self.panel(self.figure.density(data, **kwargs))

    def scatter(
        self,
        data,
        *,
        panel_aspect_ratio: float | None = None,
        **kwargs,
    ) -> pn.pane.Plotly:
        return self.panel(
            self.figure.scatter(data, **kwargs),
            aspect_ratio=panel_aspect_ratio,
        )

    def kpi(self, label: str, values, **kwargs):
        return kpi_box(self.context, label, values, **kwargs)
