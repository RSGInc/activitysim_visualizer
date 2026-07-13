"""Parsers for canonical dashboard configuration."""

from __future__ import annotations

from pathlib import Path

from .common import normalize_optional_path_string
from .models import (
    ExportDashboardSettings,
    ExportHTMLSettings,
    ExportSelectorRequest,
    PipelineSettings,
    SegmentationSettings,
)
from .normalize_export import (
    normalize_excluded_ids,
    normalize_export_html_selection,
    normalize_export_page_entries,
)
from .sections import mapping


def parse_dashboard_export(
    raw_value,
    *,
    pipeline: PipelineSettings,
    segmentation: SegmentationSettings,
    summary_root: Path,
    weighting_modes: list[str],
) -> ExportHTMLSettings:
    """Parse ``dashboard.export`` after pipeline and segmentation resolution."""
    export = mapping(raw_value, field_name="dashboard.export")
    dashboard = mapping(
        export.get("dashboard"), field_name="dashboard.export.dashboard"
    )
    pages_raw = export.get("pages")

    settings = ExportHTMLSettings(
        enabled=(
            pipeline.has_step("dashboard") and pipeline.dashboard_mode == "export"
        ),
        output_path=normalize_optional_path_string(
            export.get("output_path"),
            field_name="dashboard.export.output_path",
            config_dir=summary_root,
        ),
        dashboard=ExportDashboardSettings(
            weighting=normalize_export_html_selection(
                dashboard.get("weighting"),
                field_name="dashboard.export.dashboard.weighting",
                default=weighting_modes,
                allowed=weighting_modes,
            ),
            values=normalize_export_html_selection(
                dashboard.get("values"),
                field_name="dashboard.export.dashboard.values",
                default=["percent", "count"],
                allowed=["percent", "count"],
            ),
            segmentation_type=(
                None
                if not segmentation.enabled
                else (
                    str(dashboard.get("segmentation_type")).strip().lower()
                    if dashboard.get("segmentation_type") is not None
                    else segmentation.dashboard.segmentation_type
                )
            ),
            segmentation_visibility=(
                None
                if not segmentation.enabled
                else str(
                    dashboard.get(
                        "segmentation_visibility", segmentation.dashboard.visibility
                    )
                )
                .strip()
                .lower()
            ),
        ),
        pages=normalize_export_page_entries(
            {} if pages_raw is None else pages_raw,
            field_name="dashboard.export.pages",
        ),
        exclude_pages=normalize_excluded_ids(
            export.get("exclude_pages"),
            field_name="dashboard.export.exclude_pages",
        ),
        exclude_groups=normalize_excluded_ids(
            export.get("exclude_groups"),
            field_name="dashboard.export.exclude_groups",
        ),
        pages_configured=pages_raw is not None,
        default_selector_request=ExportSelectorRequest(mode="all"),
    )

    if settings.dashboard.segmentation_type is not None and (
        settings.dashboard.segmentation_type not in segmentation.definition_names()
    ):
        raise ValueError(
            "dashboard.export.dashboard.segmentation_type must name one configured segment definition."
        )
    if settings.dashboard.segmentation_visibility is not None and (
        settings.dashboard.segmentation_visibility
        not in {"full_only", "segments_only", "full_and_segments"}
    ):
        raise ValueError(
            "dashboard.export.dashboard.segmentation_visibility must be one of "
            "full_only, segments_only, or full_and_segments."
        )
    return settings
