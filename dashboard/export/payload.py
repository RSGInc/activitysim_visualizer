"""Payload assembly for offline HTML export."""

from __future__ import annotations

from itertools import product
from typing import Any

from activitysim_viz_logging import get_logger

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
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from dashboard.page_registry import (
    all_page_definitions,
    build_export_prepared_run_provider,
    build_registered_export_pages,
    exportable_page_selectors,
    group_definition_by_id,
    page_definition_by_id,
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
        widget_metadata = build_widget_metadata(
            page_def,
            page,
            context,
        )
        descriptor = {
            "id": page_def.page_id,
            "title": page_def.title,
            "selectors": [
                selector_meta
                for _, selector_meta in widget_metadata.values()
                if selector_meta is not None
            ],
            "children": [],
            "default_child_id": None,
        }
        leaf_page_defs.append(descriptor)
        page_by_id[page_def.page_id] = descriptor
        content_by_page[page_def.page_id] = serialize_page_content(
            page,
            page_def=page_def,
            config=context.config,
            widget_metadata=widget_metadata,
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
    config: Config,
    widget_metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]],
    diagnostics_for_state: dict[str, Any] | None = None,
) -> PageContentPayload:
    """Serialize one page, expanding selector variants when export-enabled."""
    page_diagnostics: dict[str, Any] = {"default": _serialize_page_diagnostics(page)}
    enabled_selectors = [
        selector_meta
        for _, selector_meta in widget_metadata.values()
        if selector_meta is not None and selector_meta["export_enabled"]
    ]
    if not enabled_selectors:
        if diagnostics_for_state is not None:
            diagnostics_for_state[page_def.page_id] = page_diagnostics
        return {
            "kind": "static_page",
            "content": serialize_viewable(
                page.view,
                disable_widgets=True,
                widget_metadata=widget_metadata,
            ),
        }

    selector_order = [selector_meta["id"] for selector_meta in enabled_selectors]
    selector_values = [
        selector_meta["resolved_values"] for selector_meta in enabled_selectors
    ]
    selector_widgets = {
        selector_def.selector_id: selector_def.widget_for(page)
        for selector_def in page_def.selectors
    }
    variants = {}
    default_values = [
        selector_meta["default_value"] for selector_meta in enabled_selectors
    ]
    for combination in product(*selector_values):
        for selector_id, selected_value in zip(selector_order, combination):
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = selected_value
        page.refresh(force=True)
        page_diagnostics[variant_key(combination)] = _serialize_page_diagnostics(page)
        variants[variant_key(combination)] = serialize_viewable(
            page.view,
            disable_widgets=False,
            widget_metadata=widget_metadata,
        )

    for selector_id, selected_value in zip(selector_order, default_values):
        widget = selector_widgets.get(selector_id)
        if widget is not None:
            widget.value = selected_value
    page.refresh(force=True)
    page_diagnostics["default"] = _serialize_page_diagnostics(page)
    if diagnostics_for_state is not None:
        diagnostics_for_state[page_def.page_id] = page_diagnostics
    return {
        "kind": "page_variants",
        "selector_ids": selector_order,
        "default_key": variant_key(default_values),
        "variants": variants,
    }


def build_widget_metadata(
    page_def: DashboardPageDefinition,
    page: Any,
    context: ExportBuildContext,
) -> dict[int, tuple[str | None, SelectorMetadataPayload | None]]:
    """Build selector metadata keyed by widget identity for serialization."""
    metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]] = {}
    for selector_def in page_def.selectors:
        selector_meta = resolve_selector_metadata(
            page_def,
            selector_def,
            page,
            context,
        )
        widget = selector_def.widget_for(page)
        if widget is not None:
            metadata[id(widget)] = (selector_def.selector_id, selector_meta)
    return metadata


def resolve_selector_metadata(
    page_def: DashboardPageDefinition,
    selector_def: PageSelectorDefinition,
    page: Any,
    context: ExportBuildContext,
) -> SelectorMetadataPayload:
    """Resolve one page selector into export metadata."""
    page_id = page_def.page_id
    selector_id = selector_def.selector_id
    request = context.config.export_html.selector_request(page_id, selector_id)
    if page_def.group_id and page_def.child_id:
        nested_request = context.config.export_html.selector_request(
            page_id,
            selector_id,
            group_id=page_def.group_id,
            child_id=page_def.child_id,
        )
        if nested_request != ExportSelectorRequest():
            request = nested_request
    configured = selector_id in context.config.export_html.pages.get(page_id, {})
    if page_def.group_id and page_def.child_id:
        configured = configured or (
            selector_id
            in context.config.export_html.grouped_pages.get(page_def.group_id, {}).get(
                page_def.child_id,
                {},
            )
        )
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
    resolved_values = resolve_selector_values(
        request=request,
        options=options,
        default_value=default_value,
        field_name=_selector_field_name(page_def, selector_id),
    )
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
        entry.page_id
        for entry in config.export_html.page_entries
        if page_definition_by_id(entry.page_id) is None
        and group_definition_by_id(entry.page_id) is None
    )
    if unknown_pages:
        raise ValueError(
            "Unsupported visualizer.export_html.pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_pages)
        )

    for page_id, selectors in config.export_html.pages.items():
        unknown_selectors = sorted(
            selector_id
            for selector_id in selectors
            if selector_definition_by_id(page_id, selector_id) is None
        )
        if unknown_selectors:
            raise ValueError(
                f"Unsupported visualizer.export_html.pages.{page_id} entries: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )
    for group_id, children in config.export_html.grouped_pages.items():
        if group_definition_by_id(group_id) is None:
            raise ValueError(
                "Unsupported visualizer.export_html.pages entries: " + repr(group_id)
            )
        for child_id, selectors in children.items():
            matching_page = next(
                (
                    page_definition
                    for page_definition in all_page_definitions()
                    if page_definition.group_id == group_id and page_definition.child_id == child_id
                ),
                None,
            )
            if matching_page is None:
                raise ValueError(
                    f"Unsupported visualizer.export_html.pages.{group_id}.children entries: {child_id!r}"
                )
            unknown_selectors = sorted(
                selector_id
                for selector_id in selectors
                if selector_definition_by_id(matching_page.page_id, selector_id) is None
            )
            if unknown_selectors:
                raise ValueError(
                    f"Unsupported visualizer.export_html.pages.{group_id}.children.{child_id} entries: "
                    + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
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
    if page_def.group_id and page_def.child_id:
        return (
            f"visualizer.export_html.pages.{page_def.group_id}.children."
            f"{page_def.child_id}.{selector_id}"
        )
    return f"visualizer.export_html.pages.{page_def.page_id}.{selector_id}"


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
