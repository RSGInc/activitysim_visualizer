"""Immutable rendering policy for one dashboard state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ValueMode = Literal["count", "share"]
HoverMode = Literal["closest", "all"]

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


def _hover_mode(value: str | None) -> HoverMode:
    return "all" if str(value or "").strip().lower() == "all" else "closest"


@dataclass(frozen=True)
class RenderContext:
    """All presentation policy needed to render figures and run-aware UI."""

    run_colors: tuple[str, ...] = DEFAULT_RUN_COLORS
    run_labels: tuple[str, ...] = ()
    value_mode: ValueMode = "count"
    bar_hover_mode: HoverMode = "closest"
    density_hover_mode: HoverMode = "closest"

    @classmethod
    def from_dashboard(cls, config, state) -> "RenderContext":
        return cls(
            run_colors=tuple(config.run_colors or DEFAULT_RUN_COLORS),
            run_labels=tuple(str(label) for label in state.run_labels),
            value_mode="share" if state.value_mode == "Percent" else "count",
            bar_hover_mode=_hover_mode(config.bar_hover_mode),
            density_hover_mode=_hover_mode(config.density_hover_mode),
        )

    def color(self, label: str, fallback_index: int = 0) -> str:
        label = str(label)
        index = (
            self.run_labels.index(label)
            if label in self.run_labels
            else fallback_index
        )
        colors = self.run_colors or DEFAULT_RUN_COLORS
        return colors[index % len(colors)]
