"""Payload assembly for offline HTML export."""

from __future__ import annotations

from itertools import product
from typing import Any

from activitysim_viz_logging import get_logger
import panel as pn

from dashboard.components import (
    build_run_legend_entries,
    set_percent_mode,
    set_run_colors,
    set_run_label_order,
)
from dashboard.export.context import ExportBuildContext
from dashboard.export.protocols import validate_export_page
from dashboard.export.serializer import (
    page_definition_for_page,
    serialize_viewable,
    variant_key,
)
from dashboard.export.types import (
    EXPORT_CLIENT_RUNTIME,
    EXPORT_PAGE_SELECTOR_RUNTIME,
    EXPORT_SCHEMA_VERSION,
    ExportPayload,
    PageContentPayload,
    PageDescriptorPayload,
    PageSelectorReferencePayload,
    SelectorMetadataPayload,
)
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageExportRegionDefinition,
    PageSelectorDefinition,
)
from dashboard.page_registry import (
    all_page_definitions,
    build_export_prepared_run_provider,
    build_registered_export_pages,
    effective_export_parts,
    export_part_definition_by_id,
    exportable_page_selectors,
    group_definition_by_id,
    page_definition_by_id,
    page_definition_by_group_child,
    resolve_export_navigation_entries,
    selector_definition_by_id,
)
from processor.models import RunData
from processor.summarize.cache import SummaryRun
from runtime.config import Config, ExportSelectorRequest

LOGGER = get_logger("dashboard.export")


def build_export_artifacts(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> tuple[ExportPayload, dict[str, Any]]:
    """Build export payload plus sidecar diagnostics."""
    set_run_colors(config.run_colors)
    validate_page_export_config(config)
    export_weight_values = config.export_html.panel_weighting_values()
    export_value_values = config.export_html.panel_value_values()
    context = ExportBuildContext(
        config=config,
        summary_runs=summary_runs,
        prepared_run_provider=build_export_prepared_run_provider(runs, config),
    )
    chrome_state = context.build_dashboard_state()
    set_run_label_order(chrome_state.run_labels)
    state_payloads: dict[str, dict[str, Any]] = {}
    diagnostics_by_state: dict[str, Any] = {}

    page_order: list[PageDescriptorPayload] | None = None
    for weight_mode in export_weight_values:
        for value_mode in export_value_values:
            key = state_key(weight_mode, value_mode)
            state_payloads[key] = serialize_dashboard_state(
                context,
                weight_mode=weight_mode,
                value_mode=value_mode,
                diagnostics_by_state=diagnostics_by_state,
            )
            if page_order is None:
                page_order = state_payloads[key]["pages"]

    payload: ExportPayload = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "title": config.dashboard_title,
        "runs_loaded": build_run_legend_entries(chrome_state.run_labels),
        "chrome": {
            "layout": "left_rail",
            "rail_sections": ["runs_loaded", "display_options"],
            "controls_enabled": {
                "weighting": len(export_weight_values) > 1,
                "values": len(export_value_values) > 1,
            },
        },
        "dashboard_controls": {
            "weighting": export_weight_values,
            "values": export_value_values,
        },
        "default_state": {
            "weighting": export_weight_values[0],
            "values": export_value_values[0],
        },
        "pages": page_order or [],
        "states": {
            key: payload["content_by_page"] for key, payload in state_payloads.items()
        },
        "page_export_support": {
            "client_side_runtime": EXPORT_PAGE_SELECTOR_RUNTIME,
            "enabled_page_selectors": enabled_page_selectors_payload(),
        },
        "client_runtime": EXPORT_CLIENT_RUNTIME,
    }
    diagnostics = {
        "schema_version": 1,
        "title": config.dashboard_title,
        "states": diagnostics_by_state,
    }
    return payload, diagnostics


def build_export_payload(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> ExportPayload:
    """Build the client-side payload consumed by the export runtime."""
    payload, _ = build_export_artifacts(runs, config, summary_runs=summary_runs)
    return payload


def serialize_dashboard_state(
    context: ExportBuildContext,
    *,
    weight_mode: str,
    value_mode: str,
    diagnostics_by_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize one dashboard-level weighting/value state combination."""
    state = context.build_dashboard_state()
    state.weight_mode = weight_mode
    state.value_mode = value_mode
    set_percent_mode(value_mode == "Percent")
    pages = build_registered_export_pages(state, context.config)

    leaf_page_defs: list[PageDescriptorPayload] = []
    content_by_page: dict[str, PageContentPayload] = {}
    diagnostics_for_state: dict[str, Any] = {}
    page_by_id: dict[str, PageDescriptorPayload] = {}
    for page in pages:
        validate_export_page(page)
        page.refresh(force=True)
        if page.view is None:
            continue
        page_def = page_definition_for_page(page)
        selector_metadata_by_id = {
            selector_def.selector_id: resolve_selector_metadata(
                page_def,
                selector_def,
                page,
                context,
            )
            for selector_def in page_def.selectors
        }
        widget_metadata = build_widget_metadata(
            page_def,
            page,
            selector_metadata_by_id=selector_metadata_by_id,
        )
        descriptor = {
            "id": page_def.page_id,
            "title": page_def.title,
            "selectors": [
                selector_metadata_by_id[selector_def.selector_id]
                for selector_def in page_def.selectors
                if selector_def.widget_for(page) is not None
            ],
            "children": [],
            "default_child_id": None,
        }
        leaf_page_defs.append(descriptor)
        page_by_id[page_def.page_id] = descriptor
        content_by_page[page_def.page_id] = serialize_page_content(
            page,
            page_def=page_def,
            widget_metadata=widget_metadata,
            selector_metadata_by_id=selector_metadata_by_id,
            diagnostics_for_state=diagnostics_for_state,
        )
    grouped_page_defs: list[PageDescriptorPayload] = []
    for navigation_entry in resolve_export_navigation_entries(context.config):
        if navigation_entry.group_definition is None:
            page_def = page_by_id.get(navigation_entry.page_definitions[0].page_id)
            if page_def is not None:
                grouped_page_defs.append(page_def)
            continue
        children = [
            page_by_id[page_definition.page_id]
            for page_definition in navigation_entry.page_definitions
            if page_definition.page_id in page_by_id
        ]
        if not children:
            continue
        default_child_page_id = _resolve_group_default_child_page_id(
            navigation_entry.page_definitions,
            default_child_local_id=navigation_entry.group_definition.default_child_id,
        )
        grouped_page_defs.append(
            {
                "id": navigation_entry.entry_id,
                "title": navigation_entry.title,
                "selectors": [],
                "children": children,
                "default_child_id": default_child_page_id,
            }
        )
    if diagnostics_by_state is not None:
        diagnostics_by_state[state_key(weight_mode, value_mode)] = diagnostics_for_state
    return {"pages": grouped_page_defs, "content_by_page": content_by_page}


def _resolve_group_default_child_page_id(
    page_definitions: list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...],
    *,
    default_child_local_id: str | None,
) -> str:
    """Return the serialized default child page id for one grouped export page."""
    if not page_definitions:
        raise ValueError("Grouped export pages must include at least one child page.")

    if default_child_local_id:
        for page_definition in page_definitions:
            if page_definition.child_id == default_child_local_id:
                return page_definition.page_id

    return page_definitions[0].page_id


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
    enabled_part_defs = resolve_enabled_export_parts(page_def, page.config.export_html)
    enabled_part_ids = {part_def.part_id for part_def in enabled_part_defs}
    enabled_selector_ids = {
        selector_id for part_def in enabled_part_defs for selector_id in part_def.selector_ids
    }
    interactive_selectors = [
        selector_meta
        for selector_meta in selector_metadata_by_id.values()
        if selector_meta["export_enabled"]
    ]
    if interactive_selectors and not effective_export_parts(page_def):
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
            id(selector_def.widget_for(page))
            for selector_def in page_def.selectors
            if selector_def.selector_id not in enabled_selector_ids
            and selector_def.widget_for(page) is not None
        },
        hidden_view_ids={
            id(part_def.view_for(page))
            for part_def in effective_export_parts(page_def)
            if part_def.part_id not in enabled_part_ids and part_def.view_for(page) is not None
        },
    )
    if diagnostics_for_state is not None:
        diagnostics_for_state[page_def.page_id] = page_diagnostics
    return {"kind": "page", "content": content}


def build_widget_metadata(
    page_def: DashboardPageDefinition,
    page: Any,
    *,
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> dict[int, tuple[str | None, SelectorMetadataPayload | None]]:
    """Build selector metadata keyed by widget identity for serialization."""
    metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]] = {}
    for selector_def in page_def.selectors:
        selector_meta = selector_metadata_by_id[selector_def.selector_id]
        widget = selector_def.widget_for(page)
        if widget is not None:
            metadata[id(widget)] = (selector_def.selector_id, selector_meta)
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

    resolved_parts = resolve_page_parts(page, page_def=page_def)
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
        selector_def.selector_id: selector_def.widget_for(page)
        for selector_def in page_def.selectors
    }
    region_nodes: dict[int, dict[str, Any]] = {}
    for part_def, part_view in resolved_parts:
        active_selector_ids = [
            selector_id
            for selector_id in part_def.selector_ids
            if selector_metadata_by_id.get(selector_id, {}).get("export_enabled")
        ]
        default_values = [
            selector_metadata_by_id[selector_id]["default_value"]
            for selector_id in active_selector_ids
        ]
        default_key = variant_key(default_values)
        variants: dict[str, Any] = {}

        if active_selector_ids:
            selector_values = [
                selector_metadata_by_id[selector_id]["resolved_values"]
                for selector_id in active_selector_ids
            ]
            for combination in product(*selector_values):
                for selector_id, selected_value in zip(active_selector_ids, combination):
                    widget = selector_widgets.get(selector_id)
                    if widget is not None:
                        widget.value = selected_value
                if hasattr(page, "clear_filtered_view_cache"):
                    page.clear_filtered_view_cache()
                page.refresh(force=True)
                refreshed_part_view = part_def.view_for(page)
                if refreshed_part_view is None:
                    raise ValueError(
                        f"Dashboard page {page_def.page_id!r} export region {part_def.part_id!r} "
                        "resolved to no view during variant serialization."
                    )
                page_diagnostics[
                    f"region:{part_def.part_id}:{variant_key(combination)}"
                ] = _serialize_page_diagnostics(page)
                variants[variant_key(combination)] = serialize_viewable(
                    refreshed_part_view,
                    disable_widgets=False,
                    widget_metadata=widget_metadata,
                )

        for selector_id, selected_value in zip(active_selector_ids, default_values):
            widget = selector_widgets.get(selector_id)
            if widget is not None and selected_value is not None:
                widget.value = selected_value
        if hasattr(page, "clear_filtered_view_cache"):
            page.clear_filtered_view_cache()
        page.refresh(force=True)
        refreshed_part_view = part_def.view_for(page)
        if refreshed_part_view is None:
            raise ValueError(
                f"Dashboard page {page_def.page_id!r} export region {part_def.part_id!r} "
                "resolved to no view after restoring defaults."
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
        }

    return region_nodes


def resolve_page_parts(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
) -> list[tuple[Any, pn.viewable.Viewable]]:
    """Resolve and validate explicit export parts for one page instance."""
    if page.view is None:
        return []

    root_paths = _view_paths_by_id(page.view)
    enabled_part_defs = resolve_enabled_export_parts(page_def, page.config.export_html)
    resolved: list[tuple[Any, pn.viewable.Viewable]] = []
    for part_def in enabled_part_defs:
        part_view = part_def.view_for(page)
        if part_view is None:
            raise ValueError(
                f"Dashboard page {page_def.page_id!r} export region {part_def.part_id!r} "
                f"could not resolve view_attr {part_def.view_attr!r}."
            )
        part_path = root_paths.get(id(part_view))
        if part_path is None:
            raise ValueError(
                f"Dashboard page {page_def.page_id!r} export region {part_def.part_id!r} "
                "does not belong to the page view tree."
            )
        resolved.append((part_def, part_view))

    for index, (part_def, part_view) in enumerate(resolved):
        part_path = root_paths[id(part_view)]
        for other_def, other_view in resolved[index + 1 :]:
            other_path = root_paths[id(other_view)]
            if part_path == other_path:
                raise ValueError(
                    f"Dashboard page {page_def.page_id!r} export regions {part_def.part_id!r} "
                    f"and {other_def.part_id!r} resolve to the same subtree."
                )
            if _is_prefix(part_path, other_path) or _is_prefix(other_path, part_path):
                raise ValueError(
                    f"Dashboard page {page_def.page_id!r} export regions {part_def.part_id!r} "
                    f"and {other_def.part_id!r} must not overlap or nest."
                )

    return resolved


def resolve_enabled_export_parts(
    page_def: DashboardPageDefinition,
    export_html: Any,
) -> tuple[Any, ...]:
    """Return the enabled export parts for one page definition."""
    override = export_html.page_override(
        page_def.page_id,
        group_id=page_def.group_id,
        child_id=page_def.child_id,
    )
    enabled_parts = []
    for part_def in effective_export_parts(page_def):
        part_override = override.parts.get(part_def.part_id)
        if part_override is not None and part_override.enabled is False:
            continue
        enabled_parts.append(part_def)
    return tuple(enabled_parts)


def _view_paths_by_id(
    root: pn.viewable.Viewable,
    path: tuple[int, ...] = (),
    result: dict[int, tuple[int, ...]] | None = None,
) -> dict[int, tuple[int, ...]]:
    """Return stable DFS paths for supported viewables in one page tree."""
    result = result or {}
    result[id(root)] = path
    for index, child in enumerate(_child_viewables(root)):
        _view_paths_by_id(child, path + (index,), result)
    return result


def _child_viewables(view: pn.viewable.Viewable) -> list[pn.viewable.Viewable]:
    """Return supported child viewables for export-region path validation."""
    if isinstance(view, (pn.Column, pn.Row, pn.Card)):
        return [
            child
            for child in view.objects
            if isinstance(child, pn.viewable.Viewable)
        ]
    if isinstance(view, pn.Tabs):
        return [
            child
            for child in view.objects
            if isinstance(child, pn.viewable.Viewable)
        ]
    return []


def _is_prefix(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    """Return whether one view path is an ancestor-prefix of another."""
    return len(left) < len(right) and right[: len(left)] == left


def resolve_selector_metadata(
    page_def: DashboardPageDefinition,
    selector_def: PageSelectorDefinition,
    page: Any,
    context: ExportBuildContext,
) -> SelectorMetadataPayload:
    """Resolve one page selector into export metadata."""
    page_id = page_def.page_id
    selector_id = selector_def.selector_id
    request = context.config.export_html.selector_request(
        page_id,
        selector_id,
        group_id=page_def.group_id,
        child_id=page_def.child_id,
    )
    configured = selector_id in context.config.export_html.page_override(
        page_id,
        group_id=page_def.group_id,
        child_id=page_def.child_id,
    ).selector_requests
    widget = selector_def.widget_for(page)
    available = selector_def.available_for(page, context.config)
    export_enabled = bool(selector_def.exportable)

    if not available or widget is None:
        if configured:
            warning_key = (page_id, selector_id)
            if warning_key not in context.warned_unavailable_selectors:
                LOGGER.warning(
                    "Warning: "
                    f"{_selector_field_name(page_def, selector_id)} is configured, "
                    "but the selector is unavailable for this export. "
                    "Ignoring the configuration and exporting the page with its fallback layout."
                )
                context.warned_unavailable_selectors.add(warning_key)
        return {
            "id": selector_id,
            "label": selector_def.label,
            "available": False,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [],
            "default_value": None,
            "options": [],
            "export_enabled": False,
        }

    options = [str(option) for option in widget.options]
    default_value = str(widget.value)
    enabled_part_defs = resolve_enabled_export_parts(page_def, context.config.export_html)
    selector_used_by_enabled_part = any(
        selector_id in part_def.selector_ids for part_def in enabled_part_defs
    )
    if configured and not selector_used_by_enabled_part:
        warning_key = (page_id, selector_id, "unused")
        if warning_key not in context.warned_unavailable_selectors:
            LOGGER.warning(
                "Warning: "
                f"{_selector_field_name(page_def, selector_id)} is configured, "
                "but no enabled export part uses this selector. Ignoring the configuration."
            )
            context.warned_unavailable_selectors.add(warning_key)
        return {
            "id": selector_id,
            "label": selector_def.label,
            "available": True,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [default_value],
            "default_value": default_value,
            "options": options,
            "export_enabled": False,
        }
    resolved_values = resolve_selector_values(
        request=request,
        options=options,
        default_value=default_value,
        field_name=_selector_field_name(page_def, selector_id),
    )
    export_enabled = bool(selector_def.exportable) and len(resolved_values) > 1
    return {
        "id": selector_id,
        "label": selector_def.label,
        "available": True,
        "request_mode": request.mode,
        "requested_values": list(request.values),
        "resolved_values": resolved_values,
        "default_value": default_value,
        "options": options,
        "export_enabled": export_enabled,
    }


def resolve_selector_values(
    *,
    request: ExportSelectorRequest,
    options: list[str],
    default_value: str,
    field_name: str,
) -> list[str]:
    """Resolve configured selector requests against actual widget options."""
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
        if option is None:
            invalid.append(token)
            continue
        if option not in resolved:
            resolved.append(option)
    if invalid:
        raise ValueError(
            f"Unsupported {field_name} values: "
            + ", ".join(repr(token) for token in invalid)
        )
    if not resolved:
        raise ValueError(f"{field_name} resolved to no values.")
    return resolved


def validate_page_export_config(config: Config) -> None:
    """Validate export page and selector ids against the live registry."""
    unknown_pages = sorted(
        page_id
        for page_id in config.export_html.pages
        if _page_definition_for_export_override(page_id) is None
    )
    if unknown_pages:
        raise ValueError(
            "Unsupported visualizer.export_html.pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_pages)
        )

    unknown_excluded_pages = sorted(
        page_id
        for page_id in config.export_html.exclude_pages
        if page_definition_by_id(page_id) is None
    )
    if unknown_excluded_pages:
        raise ValueError(
            "Unsupported visualizer.export_html.exclude_pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_excluded_pages)
        )
    unknown_excluded_groups = sorted(
        group_id
        for group_id in config.export_html.exclude_groups
        if group_definition_by_id(group_id) is None
    )
    if unknown_excluded_groups:
        raise ValueError(
            "Unsupported visualizer.export_html.exclude_groups entries: "
            + ", ".join(repr(group_id) for group_id in unknown_excluded_groups)
        )

    for page_id, override in config.export_html.pages.items():
        page_def = _page_definition_for_export_override(page_id)
        if page_def is None:
            continue
        unknown_selectors = sorted(
            selector_id
            for selector_id in override.selector_requests
            if selector_definition_by_id(page_def.page_id, selector_id) is None
        )
        if unknown_selectors:
            raise ValueError(
                f"Unsupported visualizer.export_html.pages.{page_id} entries: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )
        unknown_parts = sorted(
            part_id
            for part_id in override.parts
            if export_part_definition_by_id(page_def.page_id, part_id) is None
        )
        if unknown_parts:
            raise ValueError(
                f"Unsupported visualizer.export_html.pages.{_page_config_key(page_def)}.parts entries: "
                + ", ".join(repr(part_id) for part_id in unknown_parts)
            )


def enabled_page_selectors_payload() -> list[PageSelectorReferencePayload]:
    """Return every exportable page selector in stable sorted order."""
    return sorted(
        [
            {"page_id": page.page_id, "selector_id": selector.selector_id}
            for page, selector in exportable_page_selectors()
        ],
        key=lambda item: (item["page_id"], item["selector_id"]),
    )


def _selector_field_name(
    page_def: DashboardPageDefinition,
    selector_id: str,
) -> str:
    return f"visualizer.export_html.pages.{_page_config_key(page_def)}.{selector_id}"


def _page_config_key(page_def: DashboardPageDefinition | None) -> str:
    if page_def is None:
        return "<unknown>"
    if page_def.group_id and page_def.child_id:
        return f"{page_def.group_id}.{page_def.child_id}"
    return page_def.page_id


def _page_definition_for_export_override(page_key: str) -> DashboardPageDefinition | None:
    page_def = page_definition_by_id(page_key)
    if page_def is not None:
        return page_def
    if "." not in page_key:
        return None
    group_id, child_id = page_key.split(".", 1)
    return page_definition_by_group_child(group_id, child_id)


def state_key(weight_mode: str, value_mode: str) -> str:
    """Return the stable key for one dashboard-level state combination."""
    return f"{weight_mode}||{value_mode}"


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
