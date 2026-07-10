"""Live-only distance range controls for distance distribution charts."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re
from typing import Any

import panel as pn
import polars as pl

from dashboard.components import control_row
from dashboard.helpers.category_helpers import nonempty


_DISTANCE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def distance_bin_value(value: object) -> float | None:
    """Return the numeric position for a distance-bin label such as ``40+``."""
    if value is None:
        return None
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if isfinite(numeric) else None
    match = _DISTANCE_NUMBER_RE.search(str(value).strip())
    if match is None:
        return None
    numeric = float(match.group(0))
    return numeric if isfinite(numeric) else None


def with_distance_axis(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    source_col: str = "distance_bin",
    axis_col: str = "_distance_axis",
) -> list[tuple[str, pl.DataFrame]]:
    """Add a numeric distance-axis column while preserving distance-bin labels."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        if source_col not in df.columns:
            out.append((label, df))
            continue
        axis_values = [distance_bin_value(value) for value in df[source_col].to_list()]
        out.append((label, df.with_columns(pl.Series(axis_col, axis_values))))
    return out


def distance_axis_bounds(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    source_col: str = "distance_bin",
) -> tuple[float, float] | None:
    """Return finite min/max distance-axis bounds across chart-ready data."""
    values: list[float] = []
    for _, df in nonempty(data_list):
        if source_col not in df.columns:
            continue
        values.extend(
            numeric
            for numeric in (distance_bin_value(value) for value in df[source_col].to_list())
            if numeric is not None
        )
    if not values:
        return None
    lower = min(values)
    upper = max(values)
    if lower == upper:
        upper = lower + 1.0
    return (float(lower), float(upper))


def distance_axis_ticks(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    source_col: str = "distance_bin",
) -> tuple[list[float], list[str]]:
    """Return stable numeric tick positions and original distance-bin labels."""
    tick_labels: dict[float, str] = {}
    for _, df in nonempty(data_list):
        if source_col not in df.columns:
            continue
        for value in df[source_col].to_list():
            numeric = distance_bin_value(value)
            if numeric is not None and numeric not in tick_labels:
                tick_labels[numeric] = str(value)
    tickvals = sorted(tick_labels)
    return (tickvals, [tick_labels[value] for value in tickvals])


def fixed_distance_axis_ticks(
    *,
    max_value: int = 40,
    step: int = 2,
    plus_label: bool = True,
) -> tuple[list[float], list[str]]:
    """Return fixed whole-mile distance ticks, labeling the max as ``40+``."""
    tickvals = [float(value) for value in range(0, max_value + 1, step)]
    ticktext = [str(int(value)) for value in tickvals]
    if plus_label and ticktext:
        ticktext[-1] = f"{int(tickvals[-1])}+"
    return tickvals, ticktext


def resolve_distance_range(
    min_value: object,
    max_value: object,
) -> tuple[float, float] | None:
    """Return a valid finite distance range, or None."""
    try:
        lower = float(min_value)
        upper = float(max_value)
    except (TypeError, ValueError):
        return None
    if not isfinite(lower) or not isfinite(upper) or lower >= upper:
        return None
    return (lower, upper)


def _ranges_equal(
    left: tuple[float, float] | None,
    right: tuple[float, float] | None,
) -> bool:
    if left is None or right is None:
        return False
    return abs(left[0] - right[0]) < 1e-9 and abs(left[1] - right[1]) < 1e-9


@dataclass
class DistanceRangeControls:
    """A pair of min/max widgets plus reset behavior for one distance chart group."""

    page: Any
    prefix: str
    min_widget: pn.widgets.FloatInput
    max_widget: pn.widgets.FloatInput
    reset_button: pn.widgets.Button
    selector_ids: tuple[str, ...]

    @classmethod
    def create(
        cls,
        page: Any,
        prefix: str,
        *,
        min_label: str = "Distance Min",
        max_label: str = "Distance Max",
        reset_label: str = "Reset distance range",
        step: float = 1.0,
    ) -> "DistanceRangeControls":
        """Create registered live controls, or disabled export-only clones."""
        min_widget = pn.widgets.FloatInput(name=min_label, step=step, value=0.0)
        max_widget = pn.widgets.FloatInput(name=max_label, step=step, value=1.0)
        selector_ids: tuple[str, ...] = ()
        if page.state.export_mode:
            min_widget.disabled = True
            max_widget.disabled = True
        else:
            min_widget = page.selector(
                f"{prefix}_min",
                widget=min_widget,
                label=min_label,
                exportable=False,
            )
            max_widget = page.selector(
                f"{prefix}_max",
                widget=max_widget,
                label=max_label,
                exportable=False,
            )
            selector_ids = (f"{prefix}_min", f"{prefix}_max")
        reset_button = pn.widgets.Button(
            name=reset_label,
            button_type="default",
            width=175,
            disabled=page.state.export_mode,
        )
        controls = cls(
            page=page,
            prefix=prefix,
            min_widget=min_widget,
            max_widget=max_widget,
            reset_button=reset_button,
            selector_ids=selector_ids,
        )
        if not page.state.export_mode:
            reset_button.on_click(lambda event: controls.reset())
        return controls

    def row(self) -> pn.Row:
        """Return a standard controls row for this range group."""
        return control_row(self.min_widget, self.max_widget, self.reset_button)

    def current_range(self) -> tuple[float, float] | None:
        """Return the currently selected valid range, or None."""
        return resolve_distance_range(self.min_widget.value, self.max_widget.value)

    def sync(
        self,
        context_key: object,
        bounds: tuple[float, float] | None,
    ) -> None:
        """Initialize or update controls for the current chart context."""
        if bounds is None:
            self.min_widget.disabled = True
            self.max_widget.disabled = True
            self.reset_button.disabled = True
            return

        if self.page.state.export_mode:
            self.min_widget.value = float(bounds[0])
            self.max_widget.value = float(bounds[1])
            self.min_widget.disabled = True
            self.max_widget.disabled = True
            self.reset_button.disabled = True
            return

        self.min_widget.disabled = False
        self.max_widget.disabled = False
        self.reset_button.disabled = False
        state_key = f"{self.prefix}_range_context"
        auto_key = f"{self.prefix}_auto_range"
        last_context = self.page._page_state.get(state_key)
        last_auto_range = self.page._page_state.get(auto_key)
        current_range = self.current_range()
        should_reset = last_auto_range is None or _ranges_equal(
            current_range, last_auto_range
        )
        if should_reset:
            self.min_widget.value = float(bounds[0])
            self.max_widget.value = float(bounds[1])
        self.page._page_state[state_key] = context_key
        self.page._page_state[auto_key] = tuple(bounds)

    def reset(self) -> None:
        """Restore the controls to the last observed auto range."""
        auto_range = self.page._page_state.get(f"{self.prefix}_auto_range")
        if not auto_range:
            return
        self.min_widget.value = float(auto_range[0])
        self.max_widget.value = float(auto_range[1])
