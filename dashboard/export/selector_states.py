"""Resolve and safely enumerate page-selector states for offline export."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import panel as pn

from dashboard.export.serializer import variant_key
from dashboard.export.types import SelectorMetadataPayload
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import ExportSelectorRequest


def selector_options(widget: pn.widgets.Widget) -> list[str]:
    if isinstance(widget, pn.widgets.Checkbox):
        return ["False", "True"]
    options = getattr(widget, "options", None)
    return [] if options is None else [str(option) for option in options]


def supports_option_enumeration(widget: pn.widgets.Widget) -> bool:
    return isinstance(widget, pn.widgets.Checkbox) or hasattr(widget, "options")


def resolve_selector_values(
    *,
    request: ExportSelectorRequest,
    options: list[str],
    default_value: str,
    field_name: str,
) -> list[str]:
    """Resolve a configured selector request against current widget options."""
    if request.mode == "default":
        return [default_value]
    if request.mode == "all":
        if not options:
            raise ValueError(f"{field_name} resolved to no values.")
        return list(options)

    option_lookup = {option.strip().lower(): option for option in options}
    resolved: list[str] = []
    invalid: list[str] = []
    for token in request.values:
        option = option_lookup.get(token)
        if option is None and token == "all":
            option = next(
                (
                    candidate
                    for candidate in options
                    if candidate.strip().lower() == "all"
                    or candidate.strip().lower().startswith("all ")
                ),
                None,
            )
        if option is None:
            invalid.append(token)
        elif option not in resolved:
            resolved.append(option)
    if invalid:
        raise ValueError(
            f"Unsupported {field_name} values: "
            + ", ".join(repr(token) for token in invalid)
            + ". Supported values: "
            + ", ".join(repr(option) for option in options)
        )
    if not resolved:
        raise ValueError(f"{field_name} resolved to no values.")
    return resolved


def apply_selector_dependencies(
    page: Any,
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> None:
    """Attach page-declared dependent selector domains to export metadata."""
    dependency_provider = getattr(page, "export_selector_dependencies", None)
    if not callable(dependency_provider):
        return

    dependencies = dependency_provider() or {}
    for selector_id, dependency in dependencies.items():
        selector_meta = selector_metadata_by_id.get(str(selector_id))
        parent_selector_id = str(dependency.get("parent_selector_id", ""))
        parent_meta = selector_metadata_by_id.get(parent_selector_id)
        if selector_meta is None or parent_meta is None:
            continue

        raw_options_by_parent = dependency.get("options_by_parent_value", {})
        if not isinstance(raw_options_by_parent, dict):
            continue
        parent_values = [str(value) for value in parent_meta["resolved_values"]]
        options_by_parent_value = {
            parent_value: [
                str(option)
                for option in raw_options_by_parent.get(parent_value, [])
            ]
            for parent_value in parent_values
        }
        allowed_options = list(
            dict.fromkeys(
                option
                for parent_value in parent_values
                for option in options_by_parent_value[parent_value]
            )
        )
        if not allowed_options:
            continue

        original_resolved = {
            str(value) for value in selector_meta["resolved_values"]
        }
        resolved_values = (
            allowed_options
            if selector_meta["request_mode"] == "all"
            else [
                option for option in allowed_options if option in original_resolved
            ]
        )
        if not resolved_values:
            resolved_values = [allowed_options[0]]

        selector_meta["options"] = allowed_options
        selector_meta["resolved_values"] = resolved_values
        if str(selector_meta["default_value"]) not in allowed_options:
            selector_meta["default_value"] = allowed_options[0]
        selector_meta["export_enabled"] = bool(
            selector_meta["available"] and len(resolved_values) > 1
        )
        selector_meta["parent_selector_id"] = parent_selector_id
        selector_meta["options_by_parent_value"] = options_by_parent_value
        selector_meta["disabled_parent_values"] = [
            str(value)
            for value in dependency.get("disabled_parent_values", [])
            if str(value) in parent_values
        ]


def resolve_export_section_states(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
    part_def: Any,
    active_selector_ids: list[str],
    selector_widgets: dict[str, pn.widgets.Widget | None],
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Return canonical section states and aliases for collapsed raw states."""
    if not active_selector_ids:
        return [], {}

    states_by_key: dict[str, dict[str, str]] = {}
    aliases: dict[str, str] = {}

    def visit(
        index: int,
        canonical_values: dict[str, str],
        raw_values: dict[str, str],
    ) -> None:
        with suppress_page_selector_refresh(page), scoped_widget_values(
            selector_widgets, canonical_values
        ):
            sync_page_controls(page)
            if index >= len(active_selector_ids):
                effective_values = effective_selector_values(
                    active_selector_ids, selector_widgets
                )
                state_key = variant_key(
                    [effective_values[item] for item in active_selector_ids]
                )
                raw_key = variant_key(
                    [
                        raw_values.get(item, effective_values[item])
                        for item in active_selector_ids
                    ]
                )
                states_by_key.setdefault(state_key, effective_values)
                if raw_key != state_key:
                    aliases[raw_key] = state_key
                return

            selector_id = active_selector_ids[index]
            widget = selector_widgets.get(selector_id)
            if widget is None:
                return
            ignored = export_ignored_selectors(page, part_def.part_id, canonical_values)
            candidates = selector_values_for_current_state(
                selector_id=selector_id,
                widget=widget,
                selector_metadata=selector_metadata_by_id[selector_id],
                selected_values=canonical_values,
            )
            if not candidates:
                return
            collapsed = (
                bool(getattr(widget, "disabled", False)) or selector_id in ignored
            )
            for raw_value in candidates:
                canonical_value = export_canonical_selector_value(
                    page,
                    part_def.part_id,
                    selector_id,
                    raw_value,
                    canonical_values,
                )
                if collapsed and canonical_value == raw_value:
                    canonical_value = str(widget.value)
                visit(
                    index + 1,
                    {**canonical_values, selector_id: canonical_value},
                    {**raw_values, selector_id: raw_value},
                )

    visit(0, {}, {})
    aliases = {
        raw_key: canonical_key
        for raw_key, canonical_key in aliases.items()
        if canonical_key in states_by_key and raw_key != canonical_key
    }
    if not states_by_key:
        raise ValueError(
            f"Dashboard page {page_def.page_id!r} export region "
            f"{part_def.part_id!r} resolved to no valid selector states."
        )
    return list(states_by_key.values()), aliases


def sync_page_controls(page: Any) -> None:
    sync_declared = getattr(page, "_sync_declared_selectors", None)
    if callable(sync_declared):
        sync_declared()
    sync_controls = getattr(page, "sync_controls", None)
    if callable(sync_controls):
        sync_controls()


@contextmanager
def suppress_page_selector_refresh(page: Any) -> Iterator[None]:
    if not hasattr(page, "_is_refreshing"):
        yield
        return
    previous_refreshing = bool(getattr(page, "_is_refreshing"))
    previous_queue = set(getattr(page, "_queued_selector_ids", set()))
    page._is_refreshing = True
    try:
        yield
    finally:
        page._is_refreshing = previous_refreshing
        if hasattr(page, "_queued_selector_ids"):
            page._queued_selector_ids = previous_queue


@contextmanager
def scoped_widget_values(
    selector_widgets: dict[str, pn.widgets.Widget | None],
    values_by_selector_id: dict[str, Any],
) -> Iterator[None]:
    """Set selector widgets temporarily and restore them on every exit path."""
    original_values = {
        selector_id: widget.value
        for selector_id, widget in selector_widgets.items()
        if widget is not None
    }
    try:
        for selector_id, value in values_by_selector_id.items():
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = coerce_widget_value(widget, value)
        yield
    finally:
        for selector_id, original_value in original_values.items():
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = original_value


def coerce_widget_value(widget: pn.widgets.Widget, value: Any) -> Any:
    if isinstance(widget, pn.widgets.Checkbox) and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return value


def effective_selector_values(
    active_selector_ids: list[str],
    selector_widgets: dict[str, pn.widgets.Widget | None],
) -> dict[str, str]:
    return {
        selector_id: str(widget.value)
        for selector_id in active_selector_ids
        if (widget := selector_widgets.get(selector_id)) is not None
    }


def export_ignored_selectors(
    page: Any,
    section_id: str,
    selected_values: dict[str, str],
) -> set[str]:
    ignored = getattr(page, "export_ignored_selectors", None)
    if not callable(ignored):
        return set()
    return set(ignored(section_id, dict(selected_values)) or set())


def export_canonical_selector_value(
    page: Any,
    section_id: str,
    selector_id: str,
    value: str,
    selected_values: dict[str, str],
) -> str:
    canonical = getattr(page, "export_canonical_selector_value", None)
    if not callable(canonical):
        return value
    return str(canonical(section_id, selector_id, value, dict(selected_values)))


def selector_values_for_current_state(
    *,
    selector_id: str,
    widget: pn.widgets.Widget,
    selector_metadata: SelectorMetadataPayload,
    selected_values: dict[str, str] | None = None,
) -> list[str]:
    options = selector_options(widget)
    parent_selector_id = selector_metadata.get("parent_selector_id")
    if parent_selector_id and selected_values is not None:
        parent_value = selected_values.get(parent_selector_id)
        options_by_parent = selector_metadata.get("options_by_parent_value", {})
        if parent_value in options_by_parent:
            options = list(options_by_parent[parent_value])
    default_value = str(widget.value)
    request_mode = selector_metadata["request_mode"]
    if request_mode == "default":
        return [default_value]
    if request_mode == "all":
        return options or [default_value]

    option_lookup = {option.strip().lower(): option for option in options}
    resolved: list[str] = []
    for value in selector_metadata["resolved_values"]:
        option = option_lookup.get(str(value).strip().lower())
        if option is not None and option not in resolved:
            resolved.append(option)
    return resolved
