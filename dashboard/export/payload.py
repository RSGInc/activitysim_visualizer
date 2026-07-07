"""Payload assembly for offline HTML export."""

from __future__ import annotations

from contextlib import contextmanager
from itertools import product
import json
from typing import Any

from activitysim_viz_logging import get_logger
import panel as pn

from dashboard.components import (
    build_run_legend_entries,
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
    raw_options = getattr(widget, "options", None)
    if raw_options is None:
        return []
    return [str(option) for option in raw_options]


def _selector_supports_option_enumeration(widget: pn.widgets.Widget) -> bool:
    return hasattr(widget, "options")


def _page_export_parts(page: Any, page_def: DashboardPageDefinition) -> tuple[Any, ...]:
    runtime_sections = tuple(getattr(page, "registered_sections", ()))
    if runtime_sections:
        return tuple(
            _RuntimeExportPart(
                part_id=section.section_id,
                selector_ids=section.selector_ids,
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
    for selector_def in _page_selector_defs(page, page_def):
        selector_id = _selector_id(selector_def)
        selector_meta = selector_metadata_by_id[selector_id]
        widget = _selector_widget(selector_def, page)
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
                with temporary_widget_values(
                    selector_widgets,
                    dict(zip(active_selector_ids, combination)),
                ):
                    refreshed_part_view = _refresh_page_part_view(
                        page,
                        part_def,
                        page_id=page_def.page_id,
                        context_label="during variant serialization",
                    )
                    page_diagnostics[
                        f"region:{part_def.part_id}:{variant_key(combination)}"
                    ] = _serialize_page_diagnostics(page)
                    variants[variant_key(combination)] = serialize_viewable(
                        refreshed_part_view,
                        disable_widgets=False,
                        widget_metadata=widget_metadata,
                    )

        with temporary_widget_values(
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
                widget.value = value
        yield
    finally:
        for selector_id, original_value in original_values.items():
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = original_value


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
