"""Payload assembly for offline HTML export."""

from __future__ import annotations

from contextlib import contextmanager
import json
from time import perf_counter
from typing import Any

from runtime.logging import get_logger
import panel as pn

from dashboard.components import (
    build_run_legend_entries,
    set_bar_hover_mode,
    set_density_hover_mode,
    set_percent_mode,
    set_run_colors,
    set_run_label_order,
)
from dashboard import DashboardState
from dashboard.export.context import ExportBuildContext
from dashboard.export.protocols import validate_export_page
from dashboard.export.serializer import (
    json_default,
    page_definition_for_page,
    sanitize_export_payload,
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
)
from dashboard.page_registry import (
    build_export_prepared_run_provider,
    build_registered_export_pages,
    effective_export_parts,
    group_definition_by_id,
    page_definition_by_id,
    resolve_export_navigation_entries,
)
from processor.models import RunData
from processor.summarize.cache import SummaryRun
from runtime.config import Config, ExportSelectorRequest

LOGGER = get_logger("dashboard.export")

TOTAL_PAYLOAD_WARNING_BYTES = 100 * 1024 * 1024
TOTAL_PAYLOAD_STRONG_WARNING_BYTES = 250 * 1024 * 1024
PAGE_WARNING_BYTES = 10 * 1024 * 1024
STATIC_REGION_WARNING_BYTES = 5 * 1024 * 1024
SELECTOR_REGION_WARNING_BYTES = 1 * 1024 * 1024
EXPORT_SECTION_VARIANT_WARNING_COUNT = 500
EXPORT_REGION_PROGRESS_INTERVAL_SECONDS = 30.0
EXPORT_REGION_PROGRESS_VARIANT_INTERVAL = 25
VMT_EXPORT_DROPDOWN_NOTE = (
    "Greyed-out dropdowns are unavailable in this HTML export. "
    "Use the live dashboard to access all dropdowns."
)


class _RuntimeExportPart:
    def __init__(
        self,
        *,
        part_id: str,
        selector_ids: tuple[str, ...],
        export_data_mode: str,
        view: pn.viewable.Viewable,
    ) -> None:
        self.part_id = part_id
        self.selector_ids = selector_ids
        self.export_data_mode = export_data_mode
        self._view = view

    def view_for(self, page: Any) -> pn.viewable.Viewable | None:
        return self._view


def _page_selector_defs(
    page: Any, page_def: DashboardPageDefinition
) -> tuple[Any, ...]:
    runtime_selectors = tuple(getattr(page, "registered_selectors", ()))
    if runtime_selectors:
        return runtime_selectors
    return tuple(page_def.selectors)


def _selector_id(selector_def: Any) -> str:
    return str(selector_def.selector_id)


def _selector_label(selector_def: Any) -> str:
    return str(selector_def.label)


def _selector_exportable(selector_def: Any) -> bool:
    return bool(getattr(selector_def, "exportable", True))


def _selector_widget(selector_def: Any, page: Any) -> pn.widgets.Widget | None:
    widget = getattr(selector_def, "widget", None)
    if isinstance(widget, pn.widgets.Widget):
        return widget
    if hasattr(selector_def, "widget_for"):
        return selector_def.widget_for(page)
    return None


def _selector_available(selector_def: Any, page: Any, config: Config) -> bool:
    widget = _selector_widget(selector_def, page)
    if widget is None:
        return False
    if hasattr(selector_def, "available_for"):
        return bool(selector_def.available_for(page, config))
    return True


def _selector_options(widget: pn.widgets.Widget) -> list[str]:
    if isinstance(widget, pn.widgets.Checkbox):
        return ["False", "True"]
    raw_options = getattr(widget, "options", None)
    if raw_options is None:
        return []
    return [str(option) for option in raw_options]


def _selector_supports_option_enumeration(widget: pn.widgets.Widget) -> bool:
    return isinstance(widget, pn.widgets.Checkbox) or hasattr(widget, "options")


def _page_export_parts(page: Any, page_def: DashboardPageDefinition) -> tuple[Any, ...]:
    runtime_sections = tuple(getattr(page, "registered_sections", ()))
    if runtime_sections:
        exportable_selector_ids = {
            _selector_id(selector_def)
            for selector_def in _page_selector_defs(page, page_def)
            if _selector_exportable(selector_def)
        }
        return tuple(
            _RuntimeExportPart(
                part_id=section.section_id,
                selector_ids=tuple(
                    selector_id
                    for selector_id in section.selector_ids
                    if selector_id in exportable_selector_ids
                ),
                export_data_mode=section.export_data_mode,
                view=section.container,
            )
            for section in runtime_sections
            if section.export
        )
    return effective_export_parts(page_def)


def _part_uses_prepared_data(part_def: Any) -> bool:
    return str(getattr(part_def, "export_data_mode", "none")) != "none"


def _include_part_in_export(part_def: Any) -> bool:
    return not _part_uses_prepared_data(part_def)


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
    set_run_colors(config.run_colors)
    set_bar_hover_mode(config.bar_hover_mode)
    set_density_hover_mode(config.density_hover_mode)
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
    sanitized = sanitize_export_payload(value)
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
    return f"visualizer.export_html.pages.{page_key}.parts.{part_id}.enabled: false"


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
        enabled_part_defs = resolve_enabled_export_parts(
            page,
            page_def,
            page.config.export_html,
        )
        if _page_export_parts(page, page_def) and not enabled_part_defs:
            continue
        selector_defs = _page_selector_defs(page, page_def)
        selector_metadata_by_id = {
            _selector_id(selector_def): resolve_selector_metadata(
                page_def,
                selector_def,
                page,
                context,
            )
            for selector_def in selector_defs
        }
        apply_selector_dependencies(page, selector_metadata_by_id)
        widget_metadata = build_widget_metadata(
            page_def,
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
    enabled_part_defs = resolve_enabled_export_parts(
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
    if interactive_selectors and not _page_export_parts(page, page_def):
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
            for selector_def in _page_selector_defs(page, page_def)
            for widget in [_selector_widget(selector_def, page)]
            if _selector_id(selector_def) not in enabled_selector_ids
            and widget is not None
        },
        hidden_view_ids={
            id(part_def.view_for(page))
            for part_def in _page_export_parts(page, page_def)
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
    page_def: DashboardPageDefinition,
    page: Any,
    *,
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> dict[int, tuple[str | None, SelectorMetadataPayload | None]]:
    """Build selector metadata keyed by widget identity for serialization."""
    metadata: dict[int, tuple[str | None, SelectorMetadataPayload | None]] = {}
    for selector_def in _page_selector_defs(page, page_def):
        selector_id = _selector_id(selector_def)
        selector_meta = selector_metadata_by_id[selector_id]
        widget = _selector_widget(selector_def, page)
        if widget is not None:
            metadata[id(widget)] = (selector_id, selector_meta)
    return metadata


def apply_selector_dependencies(
    page: Any,
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> None:
    """Attach page-owned dependent-selector domains to export metadata."""
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
        allowed_options: list[str] = []
        for parent_value in parent_values:
            for option in options_by_parent_value[parent_value]:
                if option not in allowed_options:
                    allowed_options.append(option)
        if not allowed_options:
            continue

        original_resolved = {
            str(value) for value in selector_meta["resolved_values"]
        }
        if selector_meta["request_mode"] == "all":
            resolved_values = allowed_options
        else:
            resolved_values = [
                option for option in allowed_options if option in original_resolved
            ]
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
        _selector_id(selector_def): _selector_widget(selector_def, page)
        for selector_def in _page_selector_defs(page, page_def)
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
            state_specs, variant_aliases = resolve_export_section_states(
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
                with _suppress_page_selector_refresh(page), temporary_widget_values(
                    selector_widgets,
                    state_spec,
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
            LOGGER.info("Export region %s: static region, serializing default content.", region_label)

        with _suppress_page_selector_refresh(page), temporary_widget_values(
            selector_widgets,
            dict(zip(active_selector_ids, default_values)),
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


def resolve_export_section_states(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
    part_def: Any,
    active_selector_ids: list[str],
    selector_widgets: dict[str, pn.widgets.Widget | None],
    selector_metadata_by_id: dict[str, SelectorMetadataPayload],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Return canonical export states and collapsed raw-state aliases."""
    if not active_selector_ids:
        return [], {}

    states_by_key: dict[str, dict[str, str]] = {}
    aliases: dict[str, str] = {}

    def visit(
        index: int,
        canonical_values: dict[str, str],
        raw_values: dict[str, str],
    ) -> None:
        with _suppress_page_selector_refresh(page), temporary_widget_values(
            selector_widgets,
            canonical_values,
        ):
            _sync_page_controls(page)
            if index >= len(active_selector_ids):
                effective_values = _effective_selector_values(
                    active_selector_ids,
                    selector_widgets,
                )
                state_key = variant_key(
                    [effective_values[selector_id] for selector_id in active_selector_ids]
                )
                raw_key = variant_key(
                    [
                        raw_values.get(selector_id, effective_values[selector_id])
                        for selector_id in active_selector_ids
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
            ignored_selectors = _export_ignored_selectors(
                page,
                part_def.part_id,
                canonical_values,
            )
            candidate_values = _selector_values_for_current_state(
                page_def=page_def,
                selector_id=selector_id,
                widget=widget,
                selector_meta=selector_metadata_by_id[selector_id],
            )
            if not candidate_values:
                return
            selector_is_collapsed = bool(getattr(widget, "disabled", False)) or (
                selector_id in ignored_selectors
            )
            if selector_is_collapsed:
                effective_value = str(widget.value)
                for raw_value in candidate_values:
                    canonical_value = _export_canonical_selector_value(
                        page,
                        part_def.part_id,
                        selector_id,
                        raw_value,
                        canonical_values,
                    )
                    visit(
                        index + 1,
                        {
                            **canonical_values,
                            selector_id: (
                                effective_value
                                if canonical_value == raw_value
                                else canonical_value
                            ),
                        },
                        {**raw_values, selector_id: raw_value},
                    )
            else:
                for raw_value in candidate_values:
                    canonical_value = _export_canonical_selector_value(
                        page,
                        part_def.part_id,
                        selector_id,
                        raw_value,
                        canonical_values,
                    )
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
            f"Dashboard page {page_def.page_id!r} export region {part_def.part_id!r} "
            "resolved to no valid selector states."
        )
    return list(states_by_key.values()), aliases


def _sync_page_controls(page: Any) -> None:
    sync_controls = getattr(page, "sync_controls", None)
    if callable(sync_controls):
        sync_controls()


@contextmanager
def _suppress_page_selector_refresh(page: Any):
    if not hasattr(page, "_is_refreshing"):
        yield
        return
    previous_is_refreshing = bool(getattr(page, "_is_refreshing"))
    previous_queued_selector_ids = set(getattr(page, "_queued_selector_ids", set()))
    page._is_refreshing = True
    try:
        yield
    finally:
        page._is_refreshing = previous_is_refreshing
        if hasattr(page, "_queued_selector_ids"):
            page._queued_selector_ids = previous_queued_selector_ids


def _effective_selector_values(
    active_selector_ids: list[str],
    selector_widgets: dict[str, pn.widgets.Widget | None],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for selector_id in active_selector_ids:
        widget = selector_widgets.get(selector_id)
        if widget is not None:
            values[selector_id] = str(widget.value)
    return values


def _export_ignored_selectors(
    page: Any,
    section_id: str,
    selected_values: dict[str, str],
) -> set[str]:
    ignored_selectors = getattr(page, "export_ignored_selectors", None)
    if not callable(ignored_selectors):
        return set()
    return set(ignored_selectors(section_id, dict(selected_values)) or set())


def _export_canonical_selector_value(
    page: Any,
    section_id: str,
    selector_id: str,
    value: str,
    selected_values: dict[str, str],
) -> str:
    canonical_selector_value = getattr(page, "export_canonical_selector_value", None)
    if not callable(canonical_selector_value):
        return value
    return str(
        canonical_selector_value(
            section_id,
            selector_id,
            str(value),
            dict(selected_values),
        )
    )


def _selector_values_for_current_state(
    *,
    page_def: DashboardPageDefinition,
    selector_id: str,
    widget: pn.widgets.Widget,
    selector_meta: SelectorMetadataPayload,
) -> list[str]:
    options = _selector_options(widget)
    default_value = str(widget.value)
    request_mode = selector_meta["request_mode"]
    if request_mode == "default":
        return [default_value]
    if request_mode == "all":
        return options or [default_value]

    option_lookup = {option.strip().lower(): option for option in options}
    resolved: list[str] = []
    for token in selector_meta["requested_values"]:
        option = option_lookup.get(str(token).strip().lower())
        if option is not None and option not in resolved:
            resolved.append(option)
    if not resolved:
        return []
    return resolved


def resolve_page_parts(
    page: Any,
    *,
    page_def: DashboardPageDefinition,
) -> list[tuple[Any, pn.viewable.Viewable]]:
    """Resolve and validate explicit export parts for one page instance."""
    if page.view is None:
        return []

    root_paths = _view_paths_by_id(page.view)
    enabled_part_defs = resolve_enabled_export_parts(
        page, page_def, page.config.export_html
    )
    resolved: list[tuple[Any, pn.viewable.Viewable]] = []
    for part_def in enabled_part_defs:
        part_view = part_def.view_for(page)
        if part_view is None:
            raise ValueError(
                f"Dashboard page {page_def.page_id!r} export region {part_def.part_id!r} "
                "could not resolve its registered view."
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


@contextmanager
def temporary_widget_values(
    selector_widgets: dict[str, pn.widgets.Widget | None],
    values_by_selector_id: dict[str, Any],
):
    """Temporarily set selector widget values and always restore the originals.

    Export region serialization needs to mutate live widget instances so each
    selector combination can be rendered offline. This helper keeps that
    mutation boundary explicit and guarantees restoration on both success and
    failure paths.
    """
    original_values = {
        selector_id: widget.value
        for selector_id, widget in selector_widgets.items()
        if widget is not None
    }
    try:
        for selector_id, value in values_by_selector_id.items():
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = _coerce_widget_value(widget, value)
        yield
    finally:
        for selector_id, original_value in original_values.items():
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = original_value


def _coerce_widget_value(widget: pn.widgets.Widget, value: Any) -> Any:
    if isinstance(widget, pn.widgets.Checkbox) and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return value


def _refresh_page_part_view(
    page: Any,
    part_def: Any,
    *,
    page_id: str,
    context_label: str,
) -> pn.viewable.Viewable:
    """Refresh one page and resolve the current export-part subtree."""
    if hasattr(page, "clear_filtered_view_cache"):
        page.clear_filtered_view_cache()
    page.refresh(force=True)
    refreshed_part_view = part_def.view_for(page)
    if refreshed_part_view is None:
        raise ValueError(
            f"Dashboard page {page_id!r} export region {part_def.part_id!r} "
            f"resolved to no view {context_label}."
        )
    return refreshed_part_view


def resolve_enabled_export_parts(
    page: Any,
    page_def: DashboardPageDefinition,
    export_html: Any,
) -> tuple[Any, ...]:
    """Return the enabled export parts for one page definition."""
    override = export_html.page_override(
        page_def.page_id,
        group_id=page_def.group_id,
    )
    enabled_parts = []
    for part_def in _page_export_parts(page, page_def):
        if not _include_part_in_export(part_def):
            continue
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
            child for child in view.objects if isinstance(child, pn.viewable.Viewable)
        ]
    if isinstance(view, pn.Tabs):
        return [
            child for child in view.objects if isinstance(child, pn.viewable.Viewable)
        ]
    return []


def _is_prefix(left: tuple[int, ...], right: tuple[int, ...]) -> bool:
    """Return whether one view path is an ancestor-prefix of another."""
    return len(left) < len(right) and right[: len(left)] == left


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
    widget = _selector_widget(selector_def, page)
    available = _selector_available(selector_def, page, context.config)
    export_enabled = _selector_exportable(selector_def)

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
            "label": _selector_label(selector_def),
            "available": False,
            "request_mode": request.mode,
            "requested_values": list(request.values),
            "resolved_values": [],
            "default_value": None,
            "options": [],
            "export_enabled": False,
        }

    options = _selector_options(widget)
    default_value = str(widget.value)
    enabled_part_defs = resolve_enabled_export_parts(
        page, page_def, context.config.export_html
    )
    selector_used_by_enabled_part = any(
        selector_id in part_def.selector_ids for part_def in enabled_part_defs
    )
    supports_option_enumeration = _selector_supports_option_enumeration(widget)
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
            "label": _selector_label(selector_def),
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
            "label": _selector_label(selector_def),
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
    export_enabled = _selector_exportable(selector_def) and len(resolved_values) > 1
    return {
        "id": selector_id,
        "label": _selector_label(selector_def),
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
            continue
        if option not in resolved:
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
        page = _build_validation_page(page_def, config)
        selector_defs = _page_selector_defs(page, page_def)
        unknown_selectors = sorted(
            selector_id
            for selector_id in override.selector_requests
            if selector_defs
            and selector_id
            not in {_selector_id(selector_def) for selector_def in selector_defs}
        )
        if unknown_selectors:
            raise ValueError(
                f"Unsupported visualizer.export_html.pages.{page_id} entries: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )
        export_parts = _page_export_parts(page, page_def)
        unknown_parts = sorted(
            part_id
            for part_id in override.parts
            if export_parts and part_id not in {part.part_id for part in export_parts}
        )
        if unknown_parts:
            raise ValueError(
                f"Unsupported visualizer.export_html.pages.{_page_config_key(page_def)}.parts entries: "
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
    return f"visualizer.export_html.pages.{_page_config_key(page_def)}.{selector_id}"


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
