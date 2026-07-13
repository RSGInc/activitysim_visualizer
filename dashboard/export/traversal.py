"""Traverse dashboard pages and resolve their exportable section subtrees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import panel as pn

from dashboard.page_definitions import DashboardPageDefinition


@dataclass(frozen=True)
class RuntimeExportPart:
    """Export-facing view of one section registered by a dashboard page."""

    part_id: str
    selector_ids: tuple[str, ...]
    export_data_mode: str
    view: pn.viewable.Viewable

    def view_for(self, page: Any) -> pn.viewable.Viewable:
        return self.view


def page_selectors(page: Any) -> tuple[Any, ...]:
    return tuple(getattr(page, "registered_selectors", ()))


def selector_id(selector: Any) -> str:
    return str(selector.selector_id)


def selector_label(selector: Any) -> str:
    return str(selector.label)


def selector_exportable(selector: Any) -> bool:
    return bool(getattr(selector, "exportable", True))


def selector_widget(selector: Any) -> pn.widgets.Widget | None:
    widget = getattr(selector, "widget", None)
    return widget if isinstance(widget, pn.widgets.Widget) else None


def selector_available(selector: Any) -> bool:
    return selector_widget(selector) is not None


def page_export_parts(page: Any) -> tuple[RuntimeExportPart, ...]:
    """Project registered page sections onto the export traversal contract."""
    exportable_selector_ids = {
        selector_id(selector)
        for selector in page_selectors(page)
        if selector_exportable(selector)
    }
    return tuple(
        RuntimeExportPart(
            part_id=section.section_id,
            selector_ids=tuple(
                item
                for item in section.selector_ids
                if item in exportable_selector_ids
            ),
            export_data_mode=section.export_data_mode,
            view=section.container,
        )
        for section in tuple(getattr(page, "registered_sections", ()))
        if section.export
    )


def enabled_export_parts(
    page: Any,
    page_definition: DashboardPageDefinition,
    export_config: Any,
) -> tuple[RuntimeExportPart, ...]:
    """Return sections enabled by both their page contract and export config."""
    override = export_config.page_override(
        page_definition.page_id,
        group_id=page_definition.group_id,
    )
    enabled: list[RuntimeExportPart] = []
    for part in page_export_parts(page):
        if part.export_data_mode != "none":
            continue
        part_override = override.parts.get(part.part_id)
        if part_override is not None and part_override.enabled is False:
            continue
        enabled.append(part)
    return tuple(enabled)


def resolve_page_parts(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
) -> list[tuple[RuntimeExportPart, pn.viewable.Viewable]]:
    """Resolve non-overlapping export section roots inside one page tree."""
    if page.view is None:
        return []

    paths = view_paths_by_id(page.view)
    resolved: list[tuple[RuntimeExportPart, pn.viewable.Viewable]] = []
    for part in enabled_export_parts(page, page_def, page.config.export_html):
        part_view = part.view_for(page)
        part_path = paths.get(id(part_view))
        if part_path is None:
            raise ValueError(
                f"Dashboard page {page_def.page_id!r} export region "
                f"{part.part_id!r} does not belong to the page view tree."
            )
        resolved.append((part, part_view))

    for index, (part, part_view) in enumerate(resolved):
        part_path = paths[id(part_view)]
        for other, other_view in resolved[index + 1 :]:
            other_path = paths[id(other_view)]
            if part_path == other_path:
                raise ValueError(
                    f"Dashboard page {page_def.page_id!r} export regions "
                    f"{part.part_id!r} and {other.part_id!r} resolve to the same subtree."
                )
            if is_prefix(part_path, other_path) or is_prefix(other_path, part_path):
                raise ValueError(
                    f"Dashboard page {page_def.page_id!r} export regions "
                    f"{part.part_id!r} and {other.part_id!r} must not overlap or nest."
                )
    return resolved


def view_paths_by_id(
    root: pn.viewable.Viewable,
    path: tuple[int, ...] = (),
    result: dict[int, tuple[int, ...]] | None = None,
) -> dict[int, tuple[int, ...]]:
    result = result or {}
    result[id(root)] = path
    for index, child in enumerate(child_viewables(root)):
        view_paths_by_id(child, path + (index,), result)
    return result


def child_viewables(view: pn.viewable.Viewable) -> list[pn.viewable.Viewable]:
    if isinstance(view, (pn.Column, pn.Row, pn.Card, pn.Tabs)):
        return [
            child for child in view.objects if isinstance(child, pn.viewable.Viewable)
        ]
    return []


def is_prefix(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    return len(left) < len(right) and right[: len(left)] == left
