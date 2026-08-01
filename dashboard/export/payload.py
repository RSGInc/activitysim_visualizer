"""Payload assembly for offline HTML export."""

from __future__ import annotations

import json
from typing import Any

from runtime.logging import get_logger
import panel as pn

from dashboard.rendering import RenderContext, run_legend_entries
from dashboard import DashboardState
from dashboard.export.context import ExportBuildContext
from dashboard.export.protocols import validate_export_page
from dashboard.export.serializer import (
    json_default,
    page_definition_for_page,
    sanitize_export_payload_in_place,
)
from dashboard.export import page_serializer, selector_states, traversal
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
)
from dashboard.page_registry import (
    build_export_prepared_run_provider,
    build_registered_export_pages,
    group_definition_by_id,
    page_definition_by_id,
    resolve_export_navigation_entries,
)
from processor.models import RunData
from processor.summarize.cache_types import SummaryRun
from runtime.config import Config

LOGGER = get_logger("dashboard.export")

TOTAL_PAYLOAD_WARNING_BYTES = 100 * 1024 * 1024
TOTAL_PAYLOAD_STRONG_WARNING_BYTES = 250 * 1024 * 1024
PAGE_WARNING_BYTES = 10 * 1024 * 1024
STATIC_REGION_WARNING_BYTES = 5 * 1024 * 1024
SELECTOR_REGION_WARNING_BYTES = 1 * 1024 * 1024
def _build_validation_page(
    page_def: DashboardPageDefinition,
    config: Config,
) -> Any:
    page_cls = page_def.page_cls
    if page_cls is None:
        raise ValueError(f"Dashboard page {page_def.page_id!r} has no page class.")
    return page_cls(
        DashboardState(
            weighting_modes=config.weighting_modes,
            dashboard_segmentation_type=config.export_html.dashboard.segmentation_type,
            default_segmentation_visibility=(
                config.export_html.dashboard.segmentation_visibility
                or "full_and_segments"
            ),
        ),
        config,
    )


def build_export_artifacts(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> tuple[ExportPayload, dict[str, Any]]:
    """Build export payload plus sidecar diagnostics."""
    validate_page_export_config(config)
    export_weight_values = config.export_html.panel_weighting_values()
    export_value_values = config.export_html.panel_value_values()
    context = ExportBuildContext(
        config=config,
        summary_runs=summary_runs,
        prepared_run_provider=build_export_prepared_run_provider(runs, config),
    )
    chrome_state = context.build_dashboard_state()
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
        "runs_loaded": run_legend_entries(
            RenderContext.from_dashboard(config, chrome_state)
        ),
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
            "enabled_page_selectors": enabled_page_selectors_payload(page_order or []),
        },
        "client_runtime": EXPORT_CLIENT_RUNTIME,
    }
    size_analysis = analyze_export_payload_size(payload)
    diagnostics = {
        "schema_version": 1,
        "title": config.dashboard_title,
        "states": diagnostics_by_state,
        "size_analysis": size_analysis,
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


def analyze_export_payload_size(payload: ExportPayload) -> dict[str, Any]:
    """Return JSON-size diagnostics for one serialized export payload."""
    states = payload.get("states", {})
    states_analysis: dict[str, Any] = {}
    page_peaks: dict[str, dict[str, Any]] = {}
    region_peaks: dict[str, dict[str, Any]] = {}

    for export_state_key, state_payload in states.items():
        state_bytes = _estimate_json_bytes(state_payload)
        pages_analysis: dict[str, Any] = {}
        for page_id, page_payload in state_payload.items():
            page_bytes = _estimate_json_bytes(page_payload)
            regions = _collect_region_size_metrics(page_payload)
            pages_analysis[page_id] = {
                "payload_bytes": page_bytes,
                "regions": regions,
            }

            current_page_peak = page_peaks.get(page_id)
            if (
                current_page_peak is None
                or page_bytes > current_page_peak["payload_bytes"]
            ):
                page_peaks[page_id] = {
                    "state_key": export_state_key,
                    "payload_bytes": page_bytes,
                }

            page_region_peaks = region_peaks.setdefault(page_id, {})
            for region_id, region_metrics in regions.items():
                current_region_peak = page_region_peaks.get(region_id)
                if (
                    current_region_peak is None
                    or region_metrics["total_bytes"]
                    > current_region_peak["total_bytes"]
                ):
                    page_region_peaks[region_id] = {
                        "state_key": export_state_key,
                        **region_metrics,
                    }

        states_analysis[export_state_key] = {
            "payload_bytes": state_bytes,
            "pages": pages_analysis,
        }

    return {
        "warning_thresholds": {
            "total_payload_bytes": TOTAL_PAYLOAD_WARNING_BYTES,
            "strong_total_payload_bytes": TOTAL_PAYLOAD_STRONG_WARNING_BYTES,
            "page_payload_bytes": PAGE_WARNING_BYTES,
            "static_region_bytes": STATIC_REGION_WARNING_BYTES,
            "selector_region_bytes": SELECTOR_REGION_WARNING_BYTES,
        },
        "total_payload_bytes": _estimate_json_bytes(payload),
        "state_count": len(states_analysis),
        "states": states_analysis,
        "page_peaks": {
            page_id: page_peaks[page_id]
            for page_id in sorted(
                page_peaks,
                key=lambda item: (
                    page_peaks[item]["payload_bytes"],
                    item,
                ),
                reverse=True,
            )
        },
        "region_peaks": {
            page_id: {
                region_id: page_regions[region_id]
                for region_id in sorted(
                    page_regions,
                    key=lambda item: (
                        page_regions[item]["total_bytes"],
                        item,
                    ),
                    reverse=True,
                )
            }
            for page_id, page_regions in sorted(region_peaks.items())
        },
    }


def emit_export_size_warnings(size_analysis: dict[str, Any] | None) -> None:
    """Log targeted warnings when one export payload is estimated to be large."""
    if not size_analysis:
        return

    total_payload_bytes = int(size_analysis.get("total_payload_bytes", 0))
    state_count = int(size_analysis.get("state_count", 0))
    if total_payload_bytes >= TOTAL_PAYLOAD_STRONG_WARNING_BYTES:
        LOGGER.warning(
            "Warning: HTML export payload is estimated at %s across %d dashboard states before Plotly JS. "
            "The final file may be very large and slow to open because weighting/value states are serialized separately.",
            _format_bytes_as_mib(total_payload_bytes),
            state_count,
        )
    elif total_payload_bytes >= TOTAL_PAYLOAD_WARNING_BYTES:
        LOGGER.warning(
            "Warning: HTML export payload is estimated at %s across %d dashboard states before Plotly JS. "
            "The final file may be large because weighting/value states are serialized separately.",
            _format_bytes_as_mib(total_payload_bytes),
            state_count,
        )

    page_peaks = size_analysis.get("page_peaks", {})
    region_peaks = size_analysis.get("region_peaks", {})
    for page_id, page_peak in page_peaks.items():
        page_payload_bytes = int(page_peak.get("payload_bytes", 0))
        if page_payload_bytes < PAGE_WARNING_BYTES:
            continue
        LOGGER.warning(
            "Warning: HTML export page %s contributes about %s in state %s.",
            page_id,
            _format_bytes_as_mib(page_payload_bytes),
            page_peak.get("state_key", "<unknown>"),
        )

        page_regions = region_peaks.get(page_id, {})
        for region_id, region_peak in page_regions.items():
            region_total_bytes = int(region_peak.get("total_bytes", 0))
            variant_count = int(region_peak.get("variant_count", 0))
            selector_ids = [str(item) for item in region_peak.get("selector_ids", [])]
            page_def = page_definition_by_id(page_id)
            config_hint = _export_part_disable_hint(page_def, region_id)
            if variant_count == 0 and region_total_bytes >= STATIC_REGION_WARNING_BYTES:
                LOGGER.warning(
                    "Warning: HTML export page %s is large because region %s contributes about %s per state with no selector variants. "
                    "Consider disabling this export part with %s.",
                    page_id,
                    region_id,
                    _format_bytes_as_mib(region_total_bytes),
                    config_hint,
                )
                continue
            if _selector_region_warning_applies(region_peak):
                LOGGER.warning(
                    "Warning: HTML export page %s expands region %s to %d selector combinations (selectors: %s), contributing about %s per state. "
                    "Consider exporting default selector values or disabling this export part with %s.",
                    page_id,
                    region_id,
                    variant_count,
                    ", ".join(selector_ids) if selector_ids else "<none>",
                    _format_bytes_as_mib(region_total_bytes),
                    config_hint,
                )


def _estimate_json_bytes(value: Any) -> int:
    sanitized = sanitize_export_payload_in_place(value)
    return len(
        json.dumps(
            sanitized,
            default=json_default,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _collect_region_size_metrics(node: Any) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}

    if isinstance(node, dict):
        if node.get("kind") == "region":
            region_id = str(node.get("region_id", "<unknown>"))
            default_content = node.get("default_content")
            variants = node.get("variants", {})
            default_content_bytes = _estimate_json_bytes(default_content)
            variants_bytes = _estimate_json_bytes(variants)
            metrics[region_id] = {
                "selector_ids": [str(item) for item in node.get("selector_ids", [])],
                "variant_count": len(variants),
                "default_content_bytes": default_content_bytes,
                "variants_bytes": variants_bytes,
                "total_bytes": default_content_bytes + variants_bytes,
            }
        for value in node.values():
            metrics.update(_collect_region_size_metrics(value))
    elif isinstance(node, list):
        for item in node:
            metrics.update(_collect_region_size_metrics(item))

    return metrics


def _selector_region_warning_applies(region_peak: dict[str, Any]) -> bool:
    variant_count = int(region_peak.get("variant_count", 0))
    selector_ids = region_peak.get("selector_ids", [])
    total_bytes = int(region_peak.get("total_bytes", 0))
    return total_bytes >= SELECTOR_REGION_WARNING_BYTES and (
        variant_count >= 10 or (len(selector_ids) > 1 and variant_count > 1)
    )


def _format_bytes_as_mib(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MiB"


def _export_part_disable_hint(
    page_def: DashboardPageDefinition | None,
    part_id: str,
) -> str:
    page_key = _page_config_key(page_def)
    return f"dashboard.export.pages.{page_key}.parts.{part_id}.enabled: false"


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
        enabled_part_defs = traversal.enabled_export_parts(
            page,
            page_def,
            page.config.export_html,
        )
        if traversal.page_export_parts(page) and not enabled_part_defs:
            continue
        selector_defs = traversal.page_selectors(page)
        selector_metadata_by_id = {
            traversal.selector_id(selector_def): resolve_selector_metadata(
                page_def,
                selector_def,
                page,
                context,
            )
            for selector_def in selector_defs
        }
        selector_states.apply_selector_dependencies(page, selector_metadata_by_id)
        widget_metadata = page_serializer.build_widget_metadata(
            page,
            selector_metadata_by_id=selector_metadata_by_id,
        )
        descriptor = {
            "id": page_def.page_id,
            "title": page_def.title,
            "selectors": [
                selector_metadata_by_id[selector_id]
                for selector_id in selector_metadata_by_id
                if any(
                    selector_id in part_def.selector_ids for part_def in enabled_part_defs
                )
            ],
            "children": [],
            "default_page_id": None,
        }
        leaf_page_defs.append(descriptor)
        page_by_id[page_def.page_id] = descriptor
        content_by_page[page_def.page_id] = page_serializer.serialize_page_content(
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
        default_page_id = _resolve_group_default_child_page_id(
            navigation_entry.page_definitions,
            default_page_id=navigation_entry.group_definition.default_page_id,
        )
        grouped_page_defs.append(
            {
                "id": navigation_entry.entry_id,
                "title": navigation_entry.title,
                "selectors": [],
                "children": children,
                "default_page_id": default_page_id,
            }
        )
    if diagnostics_by_state is not None:
        diagnostics_by_state[state_key(weight_mode, value_mode)] = diagnostics_for_state
    return {"pages": grouped_page_defs, "content_by_page": content_by_page}


def _resolve_group_default_child_page_id(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
    *,
    default_page_id: str | None,
) -> str:
    """Return the serialized default page id for one grouped export page."""
    if not page_definitions:
        raise ValueError("Grouped export pages must include at least one child page.")

    if default_page_id:
        for page_definition in page_definitions:
            if page_definition.page_id == default_page_id:
                return page_definition.page_id

    return page_definitions[0].page_id


def resolve_selector_metadata(
    page_def: DashboardPageDefinition,
    selector_def: Any,
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
    )
    configured = (
        selector_id
        in context.config.export_html.page_override(
            page_id,
            group_id=page_def.group_id,
        ).selector_requests
    )
    widget = traversal.selector_widget(selector_def)
    available = traversal.selector_available(selector_def)
    export_enabled = traversal.selector_exportable(selector_def)

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
            "label": traversal.selector_label(selector_def),
            "available": False,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [],
            "default_value": None,
            "options": [],
            "export_enabled": False,
        }

    options = selector_states.selector_options(widget)
    default_value = str(widget.value)
    enabled_part_defs = traversal.enabled_export_parts(
        page, page_def, context.config.export_html
    )
    selector_used_by_enabled_part = any(
        selector_id in part_def.selector_ids for part_def in enabled_part_defs
    )
    supports_option_enumeration = selector_states.supports_option_enumeration(widget)
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
            "label": traversal.selector_label(selector_def),
            "available": True,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [default_value],
            "default_value": default_value,
            "options": options,
            "export_enabled": False,
        }
    if not supports_option_enumeration:
        if configured and request.mode != "default":
            warning_key = (page_id, selector_id, "non_enumerated")
            if warning_key not in context.warned_unavailable_selectors:
                LOGGER.warning(
                    "Warning: "
                    f"{_selector_field_name(page_def, selector_id)} is configured with "
                    f"mode {request.mode!r}, but widget type {type(widget).__name__} "
                    "does not expose discrete options for export enumeration. "
                    "Exporting only the current widget value."
                )
                context.warned_unavailable_selectors.add(warning_key)
        return {
            "id": selector_id,
            "label": traversal.selector_label(selector_def),
            "available": True,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [default_value],
            "default_value": default_value,
            "options": options,
            "export_enabled": False,
        }
    resolved_values = selector_states.resolve_selector_values(
        request=request,
        options=options,
        default_value=default_value,
        field_name=_selector_field_name(page_def, selector_id),
    )
    export_enabled = traversal.selector_exportable(selector_def) and len(resolved_values) > 1
    return {
        "id": selector_id,
        "label": traversal.selector_label(selector_def),
        "available": True,
        "request_mode": request.mode,
        "requested_values": list(request.values),
        "resolved_values": resolved_values,
        "default_value": default_value,
        "options": options,
        "export_enabled": export_enabled,
    }


def validate_page_export_config(config: Config) -> None:
    """Validate export page and selector ids against the live registry."""
    unknown_pages = sorted(
        page_id
        for page_id in config.export_html.pages
        if _page_definition_for_export_override(page_id) is None
        and group_definition_by_id(page_id) is None
    )
    if unknown_pages:
        raise ValueError(
            "Unsupported dashboard.export.pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_pages)
        )

    unknown_excluded_pages = sorted(
        page_id
        for page_id in config.export_html.exclude_pages
        if page_definition_by_id(page_id) is None
    )
    if unknown_excluded_pages:
        raise ValueError(
            "Unsupported dashboard.export.exclude_pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_excluded_pages)
        )
    unknown_excluded_groups = sorted(
        group_id
        for group_id in config.export_html.exclude_groups
        if group_definition_by_id(group_id) is None
    )
    if unknown_excluded_groups:
        raise ValueError(
            "Unsupported dashboard.export.exclude_groups entries: "
            + ", ".join(repr(group_id) for group_id in unknown_excluded_groups)
        )

    for page_id, override in config.export_html.pages.items():
        page_def = _page_definition_for_export_override(page_id)
        if page_def is None:
            # A group-level empty mapping is a valid no-op override and has no
            # leaf selectors or parts to validate.
            continue
        page = _build_validation_page(page_def, config)
        selector_defs = traversal.page_selectors(page)
        unknown_selectors = sorted(
            selector_id
            for selector_id in override.selector_requests
            if selector_defs
            and selector_id
            not in {traversal.selector_id(selector_def) for selector_def in selector_defs}
        )
        if unknown_selectors:
            raise ValueError(
                f"Unsupported dashboard.export.pages.{page_id} entries: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )
        export_parts = traversal.page_export_parts(page)
        unknown_parts = sorted(
            part_id
            for part_id in override.parts
            if export_parts and part_id not in {part.part_id for part in export_parts}
        )
        if unknown_parts:
            raise ValueError(
                f"Unsupported dashboard.export.pages.{_page_config_key(page_def)}.parts entries: "
                + ", ".join(repr(part_id) for part_id in unknown_parts)
            )


def enabled_page_selectors_payload(
    page_descriptors: list[PageDescriptorPayload],
) -> list[PageSelectorReferencePayload]:
    """Return export-enabled page selectors from serialized page descriptors."""
    selectors: list[PageSelectorReferencePayload] = []

    def _walk(descriptor: PageDescriptorPayload) -> None:
        for selector in descriptor["selectors"]:
            if selector["export_enabled"]:
                selectors.append(
                    {"page_id": descriptor["id"], "selector_id": selector["id"]}
                )
        for child in descriptor["children"]:
            _walk(child)

    for descriptor in page_descriptors:
        _walk(descriptor)
    return sorted(selectors, key=lambda item: (item["page_id"], item["selector_id"]))


def _selector_field_name(
    page_def: DashboardPageDefinition,
    selector_id: str,
) -> str:
    return f"dashboard.export.pages.{_page_config_key(page_def)}.{selector_id}"


def _page_config_key(page_def: DashboardPageDefinition | None) -> str:
    if page_def is None:
        return "<unknown>"
    if page_def.group_id:
        return f"{page_def.group_id}.{page_def.page_id}"
    return page_def.page_id


def _page_definition_for_export_override(
    page_key: str,
) -> DashboardPageDefinition | None:
    page_def = page_definition_by_id(page_key)
    if page_def is not None:
        return page_def
    if "." not in page_key:
        return None
    group_id, page_id = page_key.split(".", 1)
    page_def = page_definition_by_id(page_id)
    if page_def is None or page_def.group_id != group_id:
        return None
    return page_def


def state_key(weight_mode: str, value_mode: str) -> str:
    """Return the stable key for one dashboard-level state combination."""
    return f"{weight_mode}||{value_mode}"
