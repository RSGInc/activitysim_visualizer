"""Shared selector and automatic-range state transitions for skim pages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def repair_selector_options(widget, options: Sequence[Any]) -> None:
    """Replace one selector domain and repair an invalid current value."""
    resolved = list(options)
    if not resolved:
        raise ValueError(f"Selector {widget.name!r} requires at least one option.")
    widget.options = resolved
    if widget.value not in resolved:
        widget.value = resolved[0]


def sync_auto_range_state(
    page_state: dict[str, object],
    *,
    state_prefix: str,
    context_key: tuple[object, ...],
    bounds: tuple[float, float] | None,
    current_range: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """Record an observed range and return it only when controls should reset."""
    context_state_key = f"{state_prefix}_range_context"
    auto_state_key = f"{state_prefix}_auto_range"
    if bounds is None:
        page_state[context_state_key] = context_key
        page_state[auto_state_key] = None
        return None

    target = tuple(bounds)
    last_context = page_state.get(context_state_key)
    last_auto_range = page_state.get(auto_state_key)
    should_reset = (
        last_context != context_key
        or last_auto_range is None
        or current_range is None
        or tuple(current_range) == tuple(last_auto_range)
    )
    page_state[context_state_key] = context_key
    page_state[auto_state_key] = target
    return target if should_reset else None
