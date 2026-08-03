"""Serialize one dashboard page and its selector-driven export regions."""

from __future__ import annotations

from time import perf_counter
from typing import Any

import panel as pn

from runtime.logging import get_logger
from dashboard.export import selector_states, traversal
from dashboard.export.serializer import serialize_viewable, variant_key
from dashboard.export.types import PageContentPayload, SelectorMetadataPayload
from dashboard.page_definitions import DashboardPageDefinition

LOGGER = get_logger("dashboard.export")

EXPORT_SECTION_VARIANT_WARNING_COUNT = 500
EXPORT_REGION_PROGRESS_INTERVAL_SECONDS = 30.0
EXPORT_REGION_PROGRESS_VARIANT_INTERVAL = 25
VMT_EXPORT_DROPDOWN_NOTE = (
    "Greyed-out dropdowns are unavailable in this HTML export. "
    "Use the live dashboard to access all dropdowns."
)


def serialize_page_content(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
    widget_metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]],
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
    diagnostics_for_state: dict[str, Any] | None = None,
) -> PageContentPayload:
    """Serialize one page shell with explicit region nodes."""
    page_diagnostics: dict[str, Any] = {"default": _serialize_page_diagnostics(page)}
    enabled_part_defs = traversal.enabled_export_parts(
        page,
        page_def,
        page.config.export_html,
    )
    enabled_part_ids = {part_def.part_id for part_def in enabled_part_defs}
    enabled_selector_ids = {
        selector_id
        for part_def in enabled_part_defs
        for selector_id in part_def.selector_ids
    }
    interactive_selectors = [
        selector_meta
        for selector_meta in selector_metadata_by_id.values()
        if selector_meta["export_enabled"]
    ]
    if interactive_selectors and not traversal.page_export_parts(page):
        raise ValueError(
            f"Dashboard page {page_def.page_id!r} declares exportable selectors but no export parts."
        )

    region_nodes_by_id = build_region_nodes(
        page,
        page_def=page_def,
        widget_metadata=widget_metadata,
        selector_metadata_by_id=selector_metadata_by_id,
        page_diagnostics=page_diagnostics,
    )
    content = serialize_viewable(
        page.view,
        disable_widgets=False,
        widget_metadata=widget_metadata,
        region_nodes_by_id=region_nodes_by_id,
        hidden_widget_ids={
            id(widget)
            for selector_def in traversal.page_selectors(page)
            for widget in [traversal.selector_widget(selector_def)]
            if traversal.selector_id(selector_def) not in enabled_selector_ids
            and widget is not None
        },
        hidden_view_ids={
            id(part_def.view_for(page))
            for part_def in traversal.page_export_parts(page)
            if part_def.part_id not in enabled_part_ids
            and part_def.view_for(page) is not None
        },
    )
    content = _with_export_page_notes(page_def, content)
    if diagnostics_for_state is not None:
        diagnostics_for_state[page_def.page_id] = page_diagnostics
    return {"kind": "page", "content": content}


def _with_export_page_notes(
    page_def: DashboardPageDefinition,
    content: dict[str, Any],
) -> dict[str, Any]:
    if page_def.page_id != "vmt":
        return content
    note_node = {
        "kind": "html",
        "html": (
            "<p class='export-dropdown-note'>"
            f"{VMT_EXPORT_DROPDOWN_NOTE}"
            "</p>"
        ),
    }
    if content.get("kind") == "container":
        children = list(content.get("children", []))
        insert_at = 1 if children else 0
        return {
            **content,
            "children": [*children[:insert_at], note_node, *children[insert_at:]],
            "child_count": len(children) + 1,
        }
    return {
        "kind": "container",
        "layout": "column",
        "child_count": 2,
        "children": [content, note_node],
        "styles": {},
        "css_classes": ["export-page-note-wrapper"],
    }


def build_widget_metadata(
    page: Any,
    *,
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> dict[int, tuple[str | None, SelectorMetadataPayload | None]]:
    """Build selector metadata keyed by widget identity for serialization."""
    metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]] = {}
    for selector_def in traversal.page_selectors(page):
        selector_id = traversal.selector_id(selector_def)
        selector_meta = selector_metadata_by_id[selector_id]
        widget = traversal.selector_widget(selector_def)
        if widget is not None:
            metadata[id(widget)] = (selector_id, selector_meta)
    return metadata


def build_region_nodes(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
    widget_metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]],
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
    page_diagnostics: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Build serialized region nodes keyed by region-root object id."""
    if page.view is None:
        return {}

    resolved_parts = traversal.resolve_page_parts(page, page_def=page_def)
    if not resolved_parts:
        return {}

    interactive_selector_ids = {
        selector_id
        for selector_id, selector_meta in selector_metadata_by_id.items()
        if selector_meta["export_enabled"]
    }
    referenced_selector_ids = {
        selector_id
        for part_def, _ in resolved_parts
        for selector_id in part_def.selector_ids
    }
    unused_selector_ids = sorted(interactive_selector_ids - referenced_selector_ids)
    if unused_selector_ids:
        raise ValueError(
            f"Dashboard page {page_def.page_id!r} does not assign export regions to selector ids: "
            + ", ".join(repr(selector_id) for selector_id in unused_selector_ids)
        )

    selector_widgets = {
        traversal.selector_id(selector_def): traversal.selector_widget(selector_def)
        for selector_def in traversal.page_selectors(page)
    }
    region_nodes: dict[int, dict[str, Any]] = {}
    for part_def, part_view in resolved_parts:
        region_start = perf_counter()
        region_label = f"{page_def.page_id}.{part_def.part_id}"
        active_selector_ids = [
            selector_id
            for selector_id in part_def.selector_ids
            if selector_metadata_by_id.get(selector_id, {}).get("export_enabled")
        ]
        LOGGER.info(
            "Export region %s: start (%s).",
            region_label,
            (
                "selectors: " + ", ".join(active_selector_ids)
                if active_selector_ids
                else "static/no exported selectors"
            ),
        )
        default_values = [
            selector_metadata_by_id[selector_id]["default_value"]
            for selector_id in active_selector_ids
        ]
        default_key = variant_key(default_values)
        variants: dict[str, Any] = {}
        variant_aliases: dict[str, str] = {}

        if active_selector_ids:
            state_specs, variant_aliases = selector_states.resolve_export_section_states(
                page,
                page_def=page_def,
                part_def=part_def,
                active_selector_ids=active_selector_ids,
                selector_widgets=selector_widgets,
                selector_metadata_by_id=selector_metadata_by_id,
            )
            selector_counts = {
                selector_id: len(selector_metadata_by_id[selector_id]["resolved_values"])
                for selector_id in active_selector_ids
            }
            raw_state_count = 1
            for count in selector_counts.values():
                raw_state_count *= count
            diagnostics_key = f"export_region:{part_def.part_id}"
            page_diagnostics[diagnostics_key] = {
                "selector_ids": list(active_selector_ids),
                "selector_counts": selector_counts,
                "raw_state_count": raw_state_count,
                "valid_state_count": len(state_specs),
                "alias_count": len(variant_aliases),
                "pruned_state_count": max(
                    raw_state_count - len(state_specs) - len(variant_aliases),
                    0,
                ),
            }
            diagnostic_message = (
                f"Export region {region_label}: "
                f"{len(state_specs)} valid states from {raw_state_count} raw selector combinations "
                f"({len(variant_aliases)} aliases, "
                f"{max(raw_state_count - len(state_specs) - len(variant_aliases), 0)} pruned)."
            )
            if len(state_specs) > EXPORT_SECTION_VARIANT_WARNING_COUNT:
                LOGGER.warning("Warning: " + diagnostic_message)
            else:
                LOGGER.info(diagnostic_message)
            last_progress_log = perf_counter()
            total_states = len(state_specs)
            for state_index, state_spec in enumerate(state_specs, start=1):
                state_values = [
                    state_spec[selector_id] for selector_id in active_selector_ids
                ]
                state_key = variant_key(state_values)
                with (
                    selector_states.suppress_page_selector_refresh(page),
                    selector_states.scoped_widget_values(
                        selector_widgets,
                        state_spec,
                    ),
                ):
                    refreshed_part_view = _refresh_page_part_view(
                        page,
                        part_def,
                        page_id=page_def.page_id,
                        context_label="during variant serialization",
                    )
                    page_diagnostics[
                        f"region:{part_def.part_id}:{state_key}"
                    ] = _serialize_page_diagnostics(page)
                    variants[state_key] = serialize_viewable(
                        refreshed_part_view,
                        disable_widgets=False,
                        widget_metadata=widget_metadata,
                    )
                now = perf_counter()
                if (
                    state_index == total_states
                    or state_index % EXPORT_REGION_PROGRESS_VARIANT_INTERVAL == 0
                    or now - last_progress_log >= EXPORT_REGION_PROGRESS_INTERVAL_SECONDS
                ):
                    LOGGER.info(
                        "Export region %s: serialized %s/%s variants in %.1fs.",
                        region_label,
                        state_index,
                        total_states,
                        now - region_start,
                    )
                    last_progress_log = now
        else:
            LOGGER.info(
                "Export region %s: static region, serializing default content.",
                region_label,
            )

        with (
            selector_states.suppress_page_selector_refresh(page),
            selector_states.scoped_widget_values(
                selector_widgets,
                dict(zip(active_selector_ids, default_values)),
            ),
        ):
            refreshed_part_view = _refresh_page_part_view(
                page,
                part_def,
                page_id=page_def.page_id,
                context_label="after restoring defaults",
            )
            default_content = serialize_viewable(
                refreshed_part_view,
                disable_widgets=False,
                widget_metadata=widget_metadata,
            )
        region_nodes[id(part_view)] = {
            "kind": "region",
            "region_id": part_def.part_id,
            "selector_ids": active_selector_ids,
            "content_mode": "snapshot",
            "default_key": default_key,
            "default_content": default_content,
            "variants": variants,
            "variant_aliases": variant_aliases,
        }
        LOGGER.info(
            "Export region %s: finished in %.1fs (variants: %s, aliases: %s).",
            region_label,
            perf_counter() - region_start,
            len(variants),
            len(variant_aliases),
        )

    return region_nodes


def _refresh_page_part_view(
    page: Any,
    part_def: Any,
    *,
    page_id: str,
    context_label: str,
) -> pn.viewable.Viewable:
    """Refresh one export section and resolve its current subtree."""
    if hasattr(page, "clear_query_cache"):
        page.clear_query_cache()
    if hasattr(page, "mark_section_stale"):
        page.mark_section_stale(part_def.part_id)
        page.refresh(force=False)
    else:
        page.refresh(force=True)
    refreshed_part_view = part_def.view_for(page)
    if refreshed_part_view is None:
        raise ValueError(
            f"Dashboard page {page_id!r} export region {part_def.part_id!r} "
            f"resolved to no view {context_label}."
        )
    return refreshed_part_view


def _serialize_page_diagnostics(page: Any) -> list[dict[str, Any]]:
    diagnostics = getattr(page, "visualization_diagnostics", [])
    serialized: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        serialized.append(
            {
                "visualization_id": diagnostic.visualization_id,
                "render_state": diagnostic.render_state,
                "input_kind": diagnostic.input_kind,
                "input_ids": list(diagnostic.input_ids),
                "usable_run_labels": list(diagnostic.usable_run_labels),
                "excluded_runs": [
                    {
                        "label": issue.label,
                        "status": issue.status,
                        "detail": issue.detail,
                        "source_kind": issue.source_kind,
                        "source_id": issue.source_id,
                        "missing_columns": list(issue.missing_columns),
                    }
                    for issue in diagnostic.excluded_runs
                ],
            }
        )
    return serialized
