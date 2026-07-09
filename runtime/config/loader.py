"""Top-level YAML loading and config assembly."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypeVar

import yaml

from .common import (
    normalize_column_aliases,
    normalize_label_mapping,
    normalize_optional_bool,
    normalize_optional_path_string,
    normalize_string_list,
)
from .constants import DEFAULT_RUN_COLORS, FILE_MAPPING_DEFAULTS
from .legacy import (
    emit_grouped_legacy_summary,
    warn_ignored_legacy_key,
    warn_supported_legacy_key,
)
from .models import (
    Config,
    ExportDashboardSettings,
    ExportHTMLSettings,
    ExportSelectorRequest,
    GeographyAggregationSettings,
    PipelineSettings,
    PrepareAutoSufficiencySettings,
)
from .normalize_categories import (
    category_spec_from_mapping,
    category_spec_from_sequence,
    normalize_categories,
    normalize_escort_category_spec,
    normalize_student_types,
)
from .normalize_export import (
    normalize_dashboard_page_entries,
    normalize_excluded_ids,
    normalize_export_html_selection,
    normalize_export_page_entries,
)
from .normalize_geography import normalize_geography_aggregations
from .normalize_prepare import (
    normalize_fallback_file_mapping,
    normalize_file_mapping,
    normalize_prepare_relationship_checks,
    normalize_prepare_time_periods,
    normalize_prepare_vot_bins,
    normalize_prepared_output_file_format,
    normalize_runs,
)
from .normalize_segmentation import normalize_segmentation
from .normalize_skimjoin import normalize_skimjoin_settings
from .signatures import digest_payload

ConfigT = TypeVar("ConfigT", bound=Config)

_PIPELINE_STEP_ORDER = ("prepare", "skimjoin", "segment", "summarize", "dashboard")
_VALID_PIPELINE_STEPS = set(_PIPELINE_STEP_ORDER)
_VALID_DASHBOARD_MODES = {"none", "live", "export", "host"}


def _mapping(raw_value, *, field_name: str) -> dict:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")
    return raw_value


def _synthesized_pipeline_steps(
    *,
    legacy_skimjoin_enabled: bool,
    legacy_segmentation_enabled: bool,
) -> tuple[str, ...]:
    steps = ["summarize", "dashboard"]
    if legacy_skimjoin_enabled:
        steps = ["prepare", "skimjoin", *steps]
    if legacy_segmentation_enabled:
        steps.insert(steps.index("dashboard"), "segment")
    return tuple(steps)


def _normalize_pipeline_settings(
    raw_value,
    *,
    legacy_skimjoin_enabled: bool,
    legacy_segmentation_enabled: bool,
) -> PipelineSettings:
    synthesized_steps = _synthesized_pipeline_steps(
        legacy_skimjoin_enabled=legacy_skimjoin_enabled,
        legacy_segmentation_enabled=legacy_segmentation_enabled,
    )
    if raw_value is None:
        return PipelineSettings(steps=synthesized_steps)
    if not isinstance(raw_value, dict):
        raise ValueError("pipeline must be a mapping when provided.")

    steps_raw = raw_value.get("steps")
    if steps_raw is None:
        steps = list(synthesized_steps)
    else:
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("pipeline.steps must be a non-empty list when provided.")
        steps = []
        seen_steps: set[str] = set()
        for idx, raw_step in enumerate(steps_raw):
            if not isinstance(raw_step, str):
                raise ValueError("pipeline.steps entries must be strings.")
            step = raw_step.strip()
            if step != step.lower():
                raise ValueError(
                    f"pipeline.steps[{idx}] must already be normalized lowercase."
                )
            if step not in _VALID_PIPELINE_STEPS:
                raise ValueError(
                    "pipeline.steps contains unsupported step "
                    f"{step!r}. Allowed steps: {', '.join(_PIPELINE_STEP_ORDER)}."
                )
            if step in seen_steps:
                raise ValueError(f"pipeline.steps contains duplicate step {step!r}.")
            seen_steps.add(step)
            steps.append(step)

    dashboard_mode = str(raw_value.get("dashboard_mode", "live")).strip().lower()
    if dashboard_mode not in _VALID_DASHBOARD_MODES:
        raise ValueError(
            "pipeline.dashboard_mode must be one of none, live, export, or host."
        )

    overwrite = raw_value.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ValueError("pipeline.overwrite must be true or false when provided.")

    if "skimjoin" in steps and "prepare" not in steps:
        raise ValueError("pipeline.steps cannot include 'skimjoin' without 'prepare'.")
    if "segment" in steps and "summarize" not in steps:
        raise ValueError("pipeline.steps cannot include 'segment' without 'summarize'.")
    if "dashboard" in steps and steps[-1] != "dashboard":
        raise ValueError("pipeline.steps must place 'dashboard' last when present.")

    return PipelineSettings(
        steps=tuple(steps),
        dashboard_mode=dashboard_mode,
        overwrite=overwrite,
    )


def _compatibility_normalize_raw_config(
    raw: dict,
) -> tuple[dict, PipelineSettings, list[tuple[str, str, str]]]:
    legacy_warnings: list[tuple[str, str, str]] = []
    prepare_cfg = dict(_mapping(raw.get("prepare"), field_name="prepare"))
    processor_cfg = dict(_mapping(raw.get("processor"), field_name="processor"))
    processor_summaries_cfg = dict(
        _mapping(processor_cfg.get("summaries"), field_name="processor.summaries")
    )
    visualizer_cfg = dict(_mapping(raw.get("visualizer"), field_name="visualizer"))
    dashboard_cfg = _mapping(raw.get("dashboard"), field_name="dashboard")
    dashboard_live_cfg = _mapping(dashboard_cfg.get("live"), field_name="dashboard.live")
    summarize_cfg = _mapping(raw.get("summarize"), field_name="summarize")
    display_cfg = _mapping(raw.get("display"), field_name="display")
    segment_cfg = _mapping(raw.get("segment"), field_name="segment")
    legacy_segmentation_cfg = _mapping(raw.get("segmentation"), field_name="segmentation")
    legacy_skimjoin_cfg = _mapping(raw.get("skimjoin"), field_name="skimjoin")
    modes_cfg = _mapping(raw.get("modes"), field_name="modes")

    pipeline = _normalize_pipeline_settings(
        raw.get("pipeline"),
        legacy_skimjoin_enabled=bool(legacy_skimjoin_cfg.get("enabled", False)),
        legacy_segmentation_enabled=bool(legacy_segmentation_cfg.get("enabled", False)),
    )

    normalized = dict(raw)

    legacy_distance_skim = raw.get("skim")
    if legacy_distance_skim is not None and not isinstance(legacy_distance_skim, dict):
        raise ValueError("skim must be a mapping when provided.")

    if "root" in raw:
        warn_ignored_legacy_key(
            mapping=processor_cfg,
            key="root",
            legacy_field_name="processor.root",
            replacement_field_name="root",
            collector=legacy_warnings,
        )
        warn_ignored_legacy_key(
            mapping=_mapping(raw.get("summaries"), field_name="summaries"),
            key="root",
            legacy_field_name="summaries.root",
            replacement_field_name="root",
            collector=legacy_warnings,
        )
        processor_cfg["root"] = raw["root"]
    elif "root" in _mapping(raw.get("summaries"), field_name="summaries"):
        warn_supported_legacy_key(
            mapping=_mapping(raw.get("summaries"), field_name="summaries"),
            key="root",
            legacy_field_name="summaries.root",
            replacement_field_name="processor.root",
            collector=legacy_warnings,
        )

    if "weighting_modes" in summarize_cfg:
        warn_ignored_legacy_key(
            mapping=processor_summaries_cfg,
            key="weighting_modes",
            legacy_field_name="processor.summaries.weighting_modes",
            replacement_field_name="summarize.weighting_modes",
            collector=legacy_warnings,
        )
        warn_ignored_legacy_key(
            mapping=_mapping(raw.get("summaries"), field_name="summaries"),
            key="weighting_modes",
            legacy_field_name="summaries.weighting_modes",
            replacement_field_name="summarize.weighting_modes",
            collector=legacy_warnings,
        )
        processor_summaries_cfg["weighting_modes"] = summarize_cfg["weighting_modes"]
    elif "weighting_modes" in _mapping(raw.get("summaries"), field_name="summaries"):
        warn_supported_legacy_key(
            mapping=_mapping(raw.get("summaries"), field_name="summaries"),
            key="weighting_modes",
            legacy_field_name="summaries.weighting_modes",
            replacement_field_name="processor.summaries.weighting_modes",
            collector=legacy_warnings,
        )

    if processor_summaries_cfg:
        processor_cfg["summaries"] = processor_summaries_cfg
    if processor_cfg:
        normalized["processor"] = processor_cfg

    if "log_level" in raw:
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="log_level",
            legacy_field_name="visualizer.log_level",
            replacement_field_name="log_level",
            collector=legacy_warnings,
        )
        visualizer_cfg["log_level"] = raw["log_level"]

    if "title" in dashboard_cfg:
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="dashboard_title",
            legacy_field_name="visualizer.dashboard_title",
            replacement_field_name="dashboard.title",
            collector=legacy_warnings,
        )
        warn_ignored_legacy_key(
            mapping=raw,
            key="dashboard_title",
            legacy_field_name="dashboard_title",
            replacement_field_name="dashboard.title",
            collector=legacy_warnings,
        )
        visualizer_cfg["dashboard_title"] = dashboard_cfg["title"]

    if "pages" in dashboard_live_cfg:
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="dashboard_pages",
            legacy_field_name="visualizer.dashboard_pages",
            replacement_field_name="dashboard.live.pages",
            collector=legacy_warnings,
        )
        warn_ignored_legacy_key(
            mapping=dashboard_cfg,
            key="pages",
            legacy_field_name="dashboard.pages",
            replacement_field_name="dashboard.live.pages",
            collector=legacy_warnings,
        )
        visualizer_cfg["dashboard_pages"] = dashboard_live_cfg["pages"]
    elif "pages" in dashboard_cfg:
        warn_supported_legacy_key(
            mapping=dashboard_cfg,
            key="pages",
            legacy_field_name="dashboard.pages",
            replacement_field_name="dashboard.live.pages",
            collector=legacy_warnings,
        )
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="dashboard_pages",
            legacy_field_name="visualizer.dashboard_pages",
            replacement_field_name="dashboard.live.pages",
            collector=legacy_warnings,
        )
        visualizer_cfg["dashboard_pages"] = dashboard_cfg["pages"]

    if "export" in dashboard_cfg:
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="export_html",
            legacy_field_name="visualizer.export_html",
            replacement_field_name="dashboard.export",
            collector=legacy_warnings,
        )
        export_cfg = dict(_mapping(dashboard_cfg.get("export"), field_name="dashboard.export"))
        warn_supported_legacy_key(
            mapping=export_cfg,
            key="enabled",
            legacy_field_name="dashboard.export.enabled",
            replacement_field_name="pipeline.dashboard_mode",
            collector=legacy_warnings,
        )
        visualizer_cfg["export_html"] = export_cfg
    elif (
        raw.get("pipeline")
        and pipeline.has_step("dashboard")
        and pipeline.dashboard_mode == "export"
        and "export_html" not in visualizer_cfg
    ):
        visualizer_cfg["export_html"] = {}

    if "enable_maz_geographies" in dashboard_cfg:
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="enable_maz_geographies",
            legacy_field_name="visualizer.enable_maz_geographies",
            replacement_field_name="dashboard.enable_maz_geographies",
            collector=legacy_warnings,
        )
        visualizer_cfg["enable_maz_geographies"] = dashboard_cfg["enable_maz_geographies"]

    if "run_colors" in display_cfg:
        warn_ignored_legacy_key(
            mapping=raw,
            key="run_colors",
            legacy_field_name="run_colors",
            replacement_field_name="display.run_colors",
            collector=legacy_warnings,
        )
        warn_ignored_legacy_key(
            mapping=visualizer_cfg,
            key="run_colors",
            legacy_field_name="visualizer.run_colors",
            replacement_field_name="display.run_colors",
            collector=legacy_warnings,
        )
        visualizer_cfg["run_colors"] = display_cfg["run_colors"]

    if "density_hover_mode" in display_cfg:
        visualizer_cfg["density_hover_mode"] = display_cfg["density_hover_mode"]

    if "bar_hover_mode" in display_cfg:
        visualizer_cfg["bar_hover_mode"] = display_cfg["bar_hover_mode"]

    if visualizer_cfg:
        normalized["visualizer"] = visualizer_cfg

    if "labels" in display_cfg:
        warn_ignored_legacy_key(
            mapping=raw,
            key="dashboard_labels",
            legacy_field_name="dashboard_labels",
            replacement_field_name="display.labels",
            collector=legacy_warnings,
        )
        normalized["dashboard_labels"] = display_cfg["labels"]

    if "geography" in summarize_cfg:
        warn_ignored_legacy_key(
            mapping=raw,
            key="geography",
            legacy_field_name="geography",
            replacement_field_name="summarize.geography",
            collector=legacy_warnings,
        )
        normalized["geography"] = summarize_cfg["geography"]

    for key in (
        "group_joint_tour_purposes",
        "group_atwork_tour_purposes",
        "group_school_tour_purposes",
    ):
        if key in summarize_cfg:
            warn_ignored_legacy_key(
                mapping=raw,
                key=key,
                legacy_field_name=key,
                replacement_field_name=f"summarize.{key}",
                collector=legacy_warnings,
            )
            normalized[key] = summarize_cfg[key]
        else:
            warn_supported_legacy_key(
                mapping=raw,
                key=key,
                legacy_field_name=key,
                replacement_field_name=f"summarize.{key}",
                collector=legacy_warnings,
            )

    if "pnr_tour_modes" in summarize_cfg:
        warn_ignored_legacy_key(
            mapping=modes_cfg,
            key="pnr_tour_modes",
            legacy_field_name="modes.pnr_tour_modes",
            replacement_field_name="summarize.pnr_tour_modes",
            collector=legacy_warnings,
        )
    elif "pnr_tour_modes" in modes_cfg:
        warn_supported_legacy_key(
            mapping=modes_cfg,
            key="pnr_tour_modes",
            legacy_field_name="modes.pnr_tour_modes",
            replacement_field_name="summarize.pnr_tour_modes",
            collector=legacy_warnings,
        )

    if segment_cfg:
        warn_ignored_legacy_key(
            mapping=raw,
            key="segmentation",
            legacy_field_name="segmentation",
            replacement_field_name="segment",
            collector=legacy_warnings,
        )
        synthesized_segment = dict(segment_cfg)
        warn_supported_legacy_key(
            mapping=synthesized_segment,
            key="enabled",
            legacy_field_name="segment.enabled",
            replacement_field_name="pipeline.steps",
            collector=legacy_warnings,
        )
        if "enabled" not in synthesized_segment:
            synthesized_segment["enabled"] = pipeline.has_step("segment") or bool(
                synthesized_segment.get("definitions")
            )
        normalized["segmentation"] = synthesized_segment

    if legacy_skimjoin_cfg:
        normalized_skimjoin = dict(legacy_skimjoin_cfg)
        if "distance_skim" in normalized_skimjoin:
            if "distance_skim" in prepare_cfg:
                warn_ignored_legacy_key(
                    mapping=normalized_skimjoin,
                    key="distance_skim",
                    legacy_field_name="skimjoin.distance_skim",
                    replacement_field_name="prepare.distance_skim",
                    collector=legacy_warnings,
                )
            else:
                warn_supported_legacy_key(
                    mapping=normalized_skimjoin,
                    key="distance_skim",
                    legacy_field_name="skimjoin.distance_skim",
                    replacement_field_name="prepare.distance_skim",
                    collector=legacy_warnings,
                )
                prepare_cfg["distance_skim"] = normalized_skimjoin["distance_skim"]
            warn_ignored_legacy_key(
                mapping=raw,
                key="skim",
                legacy_field_name="skim",
                replacement_field_name="prepare.distance_skim",
                collector=legacy_warnings,
            )
        if "defaults" in normalized_skimjoin:
            warn_ignored_legacy_key(
                mapping=normalized_skimjoin,
                key="config_path",
                legacy_field_name="skimjoin.config_path",
                replacement_field_name="skimjoin.defaults.config_path",
                collector=legacy_warnings,
            )
        if raw.get("pipeline") is not None:
            warn_supported_legacy_key(
                mapping=normalized_skimjoin,
                key="enabled",
                legacy_field_name="skimjoin.enabled",
                replacement_field_name="pipeline.steps",
                collector=legacy_warnings,
            )
            normalized_skimjoin["enabled"] = pipeline.has_step("skimjoin")
        elif "enabled" not in normalized_skimjoin and "defaults" in normalized_skimjoin:
            normalized_skimjoin["enabled"] = True
        normalized["skimjoin"] = normalized_skimjoin
    elif raw.get("pipeline") is not None and pipeline.has_step("skimjoin"):
        normalized["skimjoin"] = {"enabled": True}

    if legacy_distance_skim is not None and "distance_skim" not in prepare_cfg:
        warn_supported_legacy_key(
            mapping=raw,
            key="skim",
            legacy_field_name="skim",
            replacement_field_name="prepare.distance_skim",
            collector=legacy_warnings,
        )
        prepare_cfg["distance_skim"] = legacy_distance_skim

    if prepare_cfg:
        normalized["prepare"] = prepare_cfg

    return normalized, pipeline, legacy_warnings


def load_config_from_yaml(path: str | Path, *, cls: type[ConfigT] = Config) -> ConfigT:
    config_path = Path(path).resolve()
    config_bytes = config_path.read_bytes()
    raw = yaml.safe_load(config_bytes.decode("utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config file must parse to a mapping.")
    raw, pipeline, legacy_warnings = _compatibility_normalize_raw_config(raw)

    processor_cfg = raw.get("processor") or {}
    if not isinstance(processor_cfg, dict):
        raise ValueError("processor must be a mapping when provided.")

    summaries_cfg = raw.get("summaries") or {}
    if not isinstance(summaries_cfg, dict):
        raise ValueError("summaries must be a mapping when provided.")
    processor_summaries_cfg = processor_cfg.get("summaries") or {}
    if not isinstance(processor_summaries_cfg, dict):
        raise ValueError("processor.summaries must be a mapping when provided.")

    visualizer_cfg = raw.get("visualizer") or {}
    if not isinstance(visualizer_cfg, dict):
        raise ValueError("visualizer must be a mapping when provided.")
    dashboard_cfg = _mapping(raw.get("dashboard"), field_name="dashboard")
    dashboard_live_cfg = _mapping(dashboard_cfg.get("live"), field_name="dashboard.live")
    summarize_cfg = _mapping(raw.get("summarize"), field_name="summarize")

    files = normalize_file_mapping(
        raw.get("files"),
        field_name="files",
        defaults=FILE_MAPPING_DEFAULTS,
    )
    fallback_files = normalize_fallback_file_mapping(
        raw.get("fallback_files"),
        field_name="fallback_files",
        config_dir=config_path.parent,
    )
    runs = normalize_runs(
        raw.get("runs"),
        field_name="runs",
        config_dir=config_path.parent,
    )

    cols = raw.get("columns", {})
    if not isinstance(cols, dict):
        raise ValueError("columns must be a mapping when provided.")
    zones = raw.get("zones", {})
    if not isinstance(zones, dict):
        raise ValueError("zones must be a mapping when provided.")
    geo = raw.get("geography", {})
    if not isinstance(geo, dict):
        raise ValueError("geography must be a mapping when provided.")

    prepare_cfg = raw.get("prepare", {})
    if prepare_cfg is None:
        prepare_cfg = {}
    if not isinstance(prepare_cfg, dict):
        raise ValueError("prepare must be a mapping when provided.")
    prepare_output_cfg = prepare_cfg.get("output", {})
    if prepare_output_cfg is None:
        prepare_output_cfg = {}
    if not isinstance(prepare_output_cfg, dict):
        raise ValueError("prepare.output must be a mapping when provided.")
    prepare_validation_cfg = prepare_cfg.get("validation", {})
    if prepare_validation_cfg is None:
        prepare_validation_cfg = {}
    if not isinstance(prepare_validation_cfg, dict):
        raise ValueError("prepare.validation must be a mapping when provided.")

    geo_enabled = bool(geo.get("enabled", False))
    geo_mapping = None
    if geo_enabled and "mapping" in geo:
        geo_mapping = {str(k): str(v) for k, v in geo["mapping"].items()}
    geography_aggregations = (
        normalize_geography_aggregations(
            geo,
            field_name="geography",
            config_dir=config_path.parent,
        )
        if geo_enabled
        else GeographyAggregationSettings(enabled=False)
    )

    segmentation = normalize_segmentation(
        raw.get("segmentation"),
        field_name="segmentation",
        config_dir=config_path.parent,
    )

    skim_cfg = prepare_cfg.get("distance_skim", {})
    if skim_cfg is None:
        skim_cfg = {}
    if not isinstance(skim_cfg, dict):
        raise ValueError("prepare.distance_skim must be a mapping when provided.")
    skimjoin = normalize_skimjoin_settings(
        raw.get("skimjoin"),
        config_dir=config_path.parent,
    )
    prepare_vot_bins = normalize_prepare_vot_bins(
        prepare_cfg.get("vot_bins"),
        field_name="prepare.vot_bins",
    )
    prepare_time_periods = normalize_prepare_time_periods(
        prepare_cfg.get("time_periods"),
        field_name="prepare.time_periods",
        config_dir=config_path.parent,
    )
    auto_sufficiency_basis_raw = prepare_cfg.get("auto_sufficiency_basis")
    if auto_sufficiency_basis_raw is None:
        prepare_auto_sufficiency = PrepareAutoSufficiencySettings()
    elif not isinstance(auto_sufficiency_basis_raw, str):
        raise ValueError(
            "prepare.auto_sufficiency_basis must be one of "
            "'licensed_drivers', 'workers', or 'adults'."
        )
    else:
        auto_sufficiency_basis = auto_sufficiency_basis_raw.strip().lower()
        if auto_sufficiency_basis not in {
            "licensed_drivers",
            "workers",
            "adults",
        }:
            raise ValueError(
                "prepare.auto_sufficiency_basis must be one of "
                "'licensed_drivers', 'workers', or 'adults'."
            )
        prepare_auto_sufficiency = PrepareAutoSufficiencySettings(
            basis=auto_sufficiency_basis
        )
    prepare_output_file_format = normalize_prepared_output_file_format(
        prepare_output_cfg.get("file_format"),
        field_name="prepare.output.file_format",
    )
    prepare_relationship_checks = normalize_prepare_relationship_checks(
        prepare_validation_cfg.get("relationship_checks"),
        field_name="prepare.validation.relationship_checks",
    )

    modes_cfg = raw.get("modes", {})
    if not isinstance(modes_cfg, dict):
        raise ValueError("modes must be a mapping when provided.")
    outputs_cfg = raw.get("outputs", {})
    if outputs_cfg is None:
        outputs_cfg = {}
    if not isinstance(outputs_cfg, dict):
        raise ValueError("outputs must be a mapping when provided.")

    if "dashboard_title" in raw and "dashboard_title" in visualizer_cfg:
        warn_ignored_legacy_key(
            mapping=raw,
            key="dashboard_title",
            legacy_field_name="dashboard_title",
            replacement_field_name="visualizer.dashboard_title",
            collector=legacy_warnings,
        )
    warn_ignored_legacy_key(
        mapping=raw,
        key="dashboard_pages",
        legacy_field_name="dashboard_pages",
        replacement_field_name="visualizer.dashboard_pages",
        collector=legacy_warnings,
    )
    warn_ignored_legacy_key(
        mapping=raw,
        key="run_colors",
        legacy_field_name="run_colors",
        replacement_field_name="visualizer.run_colors",
        collector=legacy_warnings,
    )
    warn_ignored_legacy_key(
        mapping=outputs_cfg,
        key="summary_root",
        legacy_field_name="outputs.summary_root",
        replacement_field_name="processor.root",
        collector=legacy_warnings,
    )
    warn_ignored_legacy_key(
        mapping=outputs_cfg,
        key="weighting_modes",
        legacy_field_name="outputs.weighting_modes",
        replacement_field_name="processor.summaries.weighting_modes",
        collector=legacy_warnings,
    )
    warn_ignored_legacy_key(
        mapping=outputs_cfg,
        key="export_html",
        legacy_field_name="outputs.export_html",
        replacement_field_name="visualizer.export_html",
        collector=legacy_warnings,
    )
    warn_supported_legacy_key(
        mapping=summaries_cfg,
        key="root",
        legacy_field_name="summaries.root",
        replacement_field_name="processor.root",
        collector=legacy_warnings,
    )
    warn_supported_legacy_key(
        mapping=summaries_cfg,
        key="weighting_modes",
        legacy_field_name="summaries.weighting_modes",
        replacement_field_name="processor.summaries.weighting_modes",
        collector=legacy_warnings,
    )

    dashboard_pages_cfg = visualizer_cfg.get("dashboard_pages")
    dashboard_pages_field_name = "visualizer.dashboard_pages"
    if "pages" in dashboard_live_cfg:
        dashboard_pages_field_name = "dashboard.live.pages"
    elif "pages" in dashboard_cfg:
        dashboard_pages_field_name = "dashboard.pages"
    dashboard_pages = (
        None
        if dashboard_pages_cfg is None
        else normalize_dashboard_page_entries(
            dashboard_pages_cfg,
            field_name=dashboard_pages_field_name,
        )
    )

    summary_root_raw = processor_cfg.get("root", summaries_cfg.get("root", "artifacts/summary_cache"))
    summary_root = Path(summary_root_raw)
    if not summary_root.is_absolute():
        summary_root = (config_path.parent / summary_root).resolve()

    weighting_modes_cfg = processor_summaries_cfg.get(
        "weighting_modes",
        summaries_cfg.get("weighting_modes", ["weighted", "unweighted"]),
    )
    raw_weighting_modes = [str(mode).strip().lower() for mode in weighting_modes_cfg]
    supported_weighting_modes = {"weighted", "unweighted"}
    invalid_weighting_modes = [
        mode for mode in raw_weighting_modes if mode and mode not in supported_weighting_modes
    ]
    if invalid_weighting_modes:
        raise ValueError(
            "Unsupported processor.summaries.weighting_modes values: "
            + ", ".join(repr(mode) for mode in invalid_weighting_modes)
        )
    weighting_modes: list[str] = []
    for mode in raw_weighting_modes:
        if mode and mode not in weighting_modes:
            weighting_modes.append(mode)
    if not weighting_modes:
        weighting_modes = ["weighted", "unweighted"]

    raw_export_html_cfg = visualizer_cfg.get("export_html")
    export_html_present = raw_export_html_cfg is not None
    export_html_cfg = raw_export_html_cfg or {}
    if not isinstance(export_html_cfg, dict):
        raise ValueError("visualizer.export_html must be a mapping when provided.")
    warn_ignored_legacy_key(
        mapping=export_html_cfg,
        key="weighting",
        legacy_field_name="visualizer.export_html.weighting",
        replacement_field_name="visualizer.export_html.dashboard.weighting",
        collector=legacy_warnings,
    )
    warn_ignored_legacy_key(
        mapping=export_html_cfg,
        key="values",
        legacy_field_name="visualizer.export_html.values",
        replacement_field_name="visualizer.export_html.dashboard.values",
        collector=legacy_warnings,
    )
    export_enabled_raw = export_html_cfg.get("enabled")
    if export_enabled_raw is None:
        export_enabled = export_html_present
    elif isinstance(export_enabled_raw, bool):
        export_enabled = export_enabled_raw
    else:
        raise ValueError("visualizer.export_html.enabled must be true or false.")

    dashboard_cfg = export_html_cfg.get("dashboard")
    if dashboard_cfg is None:
        dashboard_cfg = {}
    elif not isinstance(dashboard_cfg, dict):
        raise ValueError("visualizer.export_html.dashboard must be a mapping.")

    pages_cfg = export_html_cfg.get("pages")
    pages_configured = pages_cfg is not None
    if pages_cfg is None:
        pages_cfg = {}
    normalized_pages = normalize_export_page_entries(
        pages_cfg,
        field_name="visualizer.export_html.pages",
    )

    export_html = ExportHTMLSettings(
        enabled=export_enabled,
        output_path=normalize_optional_path_string(
            export_html_cfg.get("output_path"),
            field_name="visualizer.export_html.output_path",
            config_dir=summary_root,
        ),
        dashboard=ExportDashboardSettings(
            weighting=normalize_export_html_selection(
                dashboard_cfg.get("weighting"),
                field_name="visualizer.export_html.dashboard.weighting",
                default=weighting_modes,
                allowed=weighting_modes,
            ),
            values=normalize_export_html_selection(
                dashboard_cfg.get("values"),
                field_name="visualizer.export_html.dashboard.values",
                default=["percent", "count"],
                allowed=["percent", "count"],
            ),
            segmentation_type=(
                None
                if not segmentation.enabled
                else (
                    str(dashboard_cfg.get("segmentation_type")).strip().lower()
                    if dashboard_cfg.get("segmentation_type") is not None
                    else segmentation.dashboard.segmentation_type
                )
            ),
            segmentation_visibility=(
                None
                if not segmentation.enabled
                else str(
                    dashboard_cfg.get(
                        "segmentation_visibility",
                        segmentation.dashboard.visibility,
                    )
                )
                .strip()
                .lower()
            ),
        ),
        pages=normalized_pages,
        exclude_pages=normalize_excluded_ids(
            export_html_cfg.get("exclude_pages"),
            field_name="visualizer.export_html.exclude_pages",
        ),
        exclude_groups=normalize_excluded_ids(
            export_html_cfg.get("exclude_groups"),
            field_name="visualizer.export_html.exclude_groups",
        ),
        pages_configured=pages_configured,
        default_selector_request=ExportSelectorRequest(mode="all"),
    )

    if export_html.dashboard.segmentation_type is not None and (
        export_html.dashboard.segmentation_type not in segmentation.definition_names()
    ):
        raise ValueError(
            "visualizer.export_html.dashboard.segmentation_type must name one configured segmentation definition."
        )
    if export_html.dashboard.segmentation_visibility is not None and (
        export_html.dashboard.segmentation_visibility
        not in {"full_only", "segments_only", "full_and_segments"}
    ):
        raise ValueError(
            "visualizer.export_html.dashboard.segmentation_visibility must be one of full_only, segments_only, or full_and_segments."
        )

    dashboard_title = visualizer_cfg.get("dashboard_title")
    if dashboard_title is None:
        dashboard_title = raw.get("dashboard_title", "ActivitySim Visualizer")
    log_level = str(visualizer_cfg.get("log_level", "INFO")).strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(
            "visualizer.log_level must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )
    run_colors = visualizer_cfg.get("run_colors", list(DEFAULT_RUN_COLORS))
    if not isinstance(run_colors, list):
        raise ValueError("visualizer.run_colors must be a list when provided.")
    missing_data_display = str(visualizer_cfg.get("missing_data_display", "card")).strip().lower()
    if missing_data_display not in {"card", "blank"}:
        raise ValueError("visualizer.missing_data_display must be either 'card' or 'blank'.")
    bar_hover_mode = str(visualizer_cfg.get("bar_hover_mode", "closest")).strip().lower()
    if bar_hover_mode not in {"closest", "all"}:
        raise ValueError("display.bar_hover_mode must be either 'closest' or 'all'.")
    density_hover_mode = str(
        visualizer_cfg.get("density_hover_mode", "closest")
    ).strip().lower()
    if density_hover_mode not in {"closest", "all"}:
        raise ValueError(
            "display.density_hover_mode must be either 'closest' or 'all'."
        )
    enable_maz_geographies_raw = visualizer_cfg.get("enable_maz_geographies", False)
    if not isinstance(enable_maz_geographies_raw, bool):
        raise ValueError(
            "visualizer.enable_maz_geographies must be true or false when provided."
        )

    person_type_labels = normalize_label_mapping(
        raw.get("person_types"),
        field_name="person_types",
    )
    transit_subsidy_labels = normalize_label_mapping(
        raw.get("transit_subsidies"),
        field_name="transit_subsidies",
    )
    summary_categories = normalize_categories(
        raw.get("summary_categories"),
        field_name="summary_categories",
    )
    dashboard_labels = normalize_categories(
        raw.get("dashboard_labels"),
        field_name="dashboard_labels",
    )
    legacy_categories = normalize_categories(
        raw.get("categories"),
        field_name="categories",
    )
    for category_id, spec in legacy_categories.items():
        summary_categories.setdefault(category_id, spec)
        dashboard_labels.setdefault(category_id, spec)
    if "person_type" not in dashboard_labels:
        legacy_person_type_spec = category_spec_from_mapping(person_type_labels)
        if legacy_person_type_spec is not None:
            dashboard_labels["person_type"] = legacy_person_type_spec
    if "transit_subsidy" not in dashboard_labels:
        legacy_transit_subsidy_spec = category_spec_from_mapping(transit_subsidy_labels)
        if legacy_transit_subsidy_spec is not None:
            dashboard_labels["transit_subsidy"] = legacy_transit_subsidy_spec
    if "geography" not in summary_categories and geo_mapping:
        legacy_geography_spec = category_spec_from_mapping(geo_mapping)
        if legacy_geography_spec is not None:
            summary_categories["geography"] = legacy_geography_spec
    if "geography" not in dashboard_labels and geo_mapping:
        legacy_geography_spec = category_spec_from_mapping(geo_mapping)
        if legacy_geography_spec is not None:
            dashboard_labels["geography"] = legacy_geography_spec
    if "mode" not in dashboard_labels:
        legacy_mode_spec = category_spec_from_sequence(modes_cfg.get("order"))
        if legacy_mode_spec is not None:
            dashboard_labels["mode"] = legacy_mode_spec
    summary_categories["escort"] = normalize_escort_category_spec(
        summary_categories.get("escort")
    )
    dashboard_labels["escort"] = normalize_escort_category_spec(
        dashboard_labels.get("escort")
    )

    group_joint_tour_purposes = (
        normalize_optional_bool(
            summarize_cfg.get(
                "group_joint_tour_purposes",
                raw.get("group_joint_tour_purposes"),
            ),
            field_name=(
                "summarize.group_joint_tour_purposes"
                if "group_joint_tour_purposes" in summarize_cfg
                else "group_joint_tour_purposes"
            ),
        )
        if (
            "group_joint_tour_purposes" in summarize_cfg
            or raw.get("group_joint_tour_purposes") is not None
        )
        else True
    )
    group_atwork_tour_purposes = (
        normalize_optional_bool(
            summarize_cfg.get(
                "group_atwork_tour_purposes",
                raw.get("group_atwork_tour_purposes"),
            ),
            field_name=(
                "summarize.group_atwork_tour_purposes"
                if "group_atwork_tour_purposes" in summarize_cfg
                else "group_atwork_tour_purposes"
            ),
        )
        if (
            "group_atwork_tour_purposes" in summarize_cfg
            or raw.get("group_atwork_tour_purposes") is not None
        )
        else True
    )
    group_school_tour_purposes = (
        normalize_optional_bool(
            summarize_cfg.get(
                "group_school_tour_purposes",
                raw.get("group_school_tour_purposes"),
            ),
            field_name=(
                "summarize.group_school_tour_purposes"
                if "group_school_tour_purposes" in summarize_cfg
                else "group_school_tour_purposes"
            ),
        )
        if (
            "group_school_tour_purposes" in summarize_cfg
            or raw.get("group_school_tour_purposes") is not None
        )
        else True
    )
    student_types = normalize_student_types(
        raw.get("student_types"),
        field_name="student_types",
    )

    pnr_tour_modes_field_name = (
        "summarize.pnr_tour_modes"
        if "pnr_tour_modes" in summarize_cfg
        else "modes.pnr_tour_modes"
    )

    config = cls(
        config_path=str(config_path),
        config_digest=hashlib.sha256(config_bytes).hexdigest(),
        prepare_config_digest="",
        summary_config_digest="",
        presentation_config_digest="",
        name=raw.get("name", ""),
        dashboard_title=str(dashboard_title),
        log_level=log_level,
        pipeline=pipeline,
        dashboard_pages=dashboard_pages,
        enable_maz_geographies=enable_maz_geographies_raw,
        run_colors=run_colors,
        missing_data_display=missing_data_display,
        bar_hover_mode=bar_hover_mode,
        density_hover_mode=density_hover_mode,
        summary_root=str(summary_root),
        weighting_modes=weighting_modes,
        export_html=export_html,
        skimjoin=skimjoin,
        prepare_vot_bins=prepare_vot_bins,
        prepare_auto_sufficiency=prepare_auto_sufficiency,
        prepare_time_periods=prepare_time_periods,
        prepare_output_file_format=prepare_output_file_format,
        prepare_relationship_checks=prepare_relationship_checks,
        files=files,
        fallback_files=fallback_files,
        col_ptype=cols.get("ptype", "ptype"),
        col_hhsize=cols.get("hhsize", "hhsize"),
        col_auto_ownership=cols.get("auto_ownership", "auto_ownership"),
        col_num_workers=cols.get("num_workers", "num_workers"),
        col_num_adults=cols.get("num_adults", "num_adults"),
        col_sample_rate=cols.get("sample_rate") or None,
        col_household_id=normalize_column_aliases(
            cols.get("household_id"),
            field_name="columns.household_id",
            default=["household_id"],
        ),
        col_person_id=normalize_column_aliases(
            cols.get("person_id"),
            field_name="columns.person_id",
            default=["person_id"],
        ),
        col_tour_id=normalize_column_aliases(
            cols.get("tour_id"),
            field_name="columns.tour_id",
            default=["tour_id"],
        ),
        col_trip_id=normalize_column_aliases(
            cols.get("trip_id"),
            field_name="columns.trip_id",
            default=["trip_id"],
        ),
        col_tour_purpose=normalize_column_aliases(
            cols.get("tour_purpose"),
            field_name="columns.tour_purpose",
            default=["tour_purpose", "primary_purpose", "tour_type", "purpose"],
        ),
        col_trip_purpose=normalize_column_aliases(
            cols.get("trip_purpose"),
            field_name="columns.trip_purpose",
            default=["trip_purpose", "purpose"],
        ),
        col_tour_mode=normalize_column_aliases(
            cols.get("tour_mode"),
            field_name="columns.tour_mode",
            default=["tour_mode"],
        ),
        col_trip_mode=normalize_column_aliases(
            cols.get("trip_mode"),
            field_name="columns.trip_mode",
            default=["trip_mode"],
        ),
        col_tour_category=normalize_column_aliases(
            cols.get("tour_category"),
            field_name="columns.tour_category",
            default=["tour_category"],
        ),
        col_tour_start=normalize_column_aliases(
            cols.get("tour_start"),
            field_name="columns.tour_start",
            default=["start", "start_hour"],
        ),
        col_tour_end=normalize_column_aliases(
            cols.get("tour_end"),
            field_name="columns.tour_end",
            default=["end", "end_hour"],
        ),
        col_tour_duration=normalize_column_aliases(
            cols.get("tour_duration"),
            field_name="columns.tour_duration",
            default=["duration", "tourdur"],
        ),
        col_trip_depart=normalize_column_aliases(
            cols.get("trip_depart"),
            field_name="columns.trip_depart",
            default=["depart", "depart_hour"],
        ),
        col_total_employment=normalize_column_aliases(
            cols.get("total_employment"),
            field_name="columns.total_employment",
            default=[
                "EMP_TOTAL",
                "EMP_Total",
                "EMPLOY_TOT",
                "TOTEMP",
                "total_employment",
                "employment",
            ],
        ),
        col_income_segment=normalize_column_aliases(
            cols.get("income_segment"),
            field_name="columns.income_segment",
            default=["income_segment", "income_broad", "income"],
        ),
        col_home_zone_id=normalize_column_aliases(
            cols.get("home_zone_id"),
            field_name="columns.home_zone_id",
            default=["home_zone_id"],
        ),
        col_workplace_zone_id=normalize_column_aliases(
            cols.get("workplace_zone_id"),
            field_name="columns.workplace_zone_id",
            default=["workplace_zone_id"],
        ),
        col_school_zone_id=normalize_column_aliases(
            cols.get("school_zone_id"),
            field_name="columns.school_zone_id",
            default=["school_zone_id"],
        ),
        col_has_license=normalize_column_aliases(
            cols.get("has_license"),
            field_name="columns.has_license",
            default=["has_license"],
        ),
        col_mandatory_tour_frequency=normalize_column_aliases(
            cols.get("mandatory_tour_frequency"),
            field_name="columns.mandatory_tour_frequency",
            default=["mandatory_tour_frequency"],
        ),
        col_is_student=normalize_column_aliases(
            cols.get("is_student"),
            field_name="columns.is_student",
            default=["is_student", "student"],
        ),
        col_is_university=normalize_column_aliases(
            cols.get("is_university"),
            field_name="columns.is_university",
            default=["is_university", "major_uni"],
        ),
        col_school_segment=normalize_column_aliases(
            cols.get("school_segment"),
            field_name="columns.school_segment",
            default=["school_segment"],
        ),
        col_schg=normalize_column_aliases(
            cols.get("schg"),
            field_name="columns.schg",
            default=["SCHG"],
        ),
        col_pstudent=normalize_column_aliases(
            cols.get("pstudent"),
            field_name="columns.pstudent",
            default=["pstudent"],
        ),
        col_tour_origin=normalize_column_aliases(
            cols.get("tour_origin"),
            field_name="columns.tour_origin",
            default=["origin"],
        ),
        col_tour_destination=normalize_column_aliases(
            cols.get("tour_destination"),
            field_name="columns.tour_destination",
            default=["destination"],
        ),
        col_trip_origin=normalize_column_aliases(
            cols.get("trip_origin"),
            field_name="columns.trip_origin",
            default=["origin"],
        ),
        col_trip_destination=normalize_column_aliases(
            cols.get("trip_destination"),
            field_name="columns.trip_destination",
            default=["destination"],
        ),
        col_stop_frequency=normalize_column_aliases(
            cols.get("stop_frequency"),
            field_name="columns.stop_frequency",
            default=["stop_frequency"],
        ),
        col_trip_outbound=normalize_column_aliases(
            cols.get("trip_outbound"),
            field_name="columns.trip_outbound",
            default=["outbound"],
        ),
        col_trip_num=normalize_column_aliases(
            cols.get("trip_num"),
            field_name="columns.trip_num",
            default=["trip_num"],
        ),
        col_pnr_zone_id=normalize_column_aliases(
            cols.get("pnr_zone_id"),
            field_name="columns.pnr_zone_id",
            default=["pnr_zone_id"],
        ),
        col_pnr_lot_capacity=normalize_column_aliases(
            cols.get("pnr_lot_capacity"),
            field_name="columns.pnr_lot_capacity",
            default=["PNR_SPACES"],
        ),
        col_is_worker=normalize_column_aliases(
            cols.get("is_worker"),
            field_name="columns.is_worker",
            default=["is_worker"],
        ),
        col_adult=normalize_column_aliases(
            cols.get("adult"),
            field_name="columns.adult",
            default=["adult", "is_adult"],
        ),
        col_day_id=normalize_column_aliases(
            cols.get("day_id"),
            field_name="columns.day_id",
            default=["day_id"],
        ),
        col_day_weight=normalize_column_aliases(
            cols.get("day_weight"),
            field_name="columns.day_weight",
            default=["day_weight"],
        ),
        col_vehicle_id=normalize_column_aliases(
            cols.get("vehicle_id"),
            field_name="columns.vehicle_id",
            default=["vehicle_id"],
        ),
        col_vehicle_num=normalize_column_aliases(
            cols.get("vehicle_num"),
            field_name="columns.vehicle_num",
            default=["vehicle_num"],
        ),
        col_vehicle_type=normalize_column_aliases(
            cols.get("vehicle_type"),
            field_name="columns.vehicle_type",
            default=["vehicle_type"],
        ),
        col_school_esc_outbound=normalize_column_aliases(
            cols.get("school_esc_outbound"),
            field_name="columns.school_esc_outbound",
            default=["school_esc_outbound"],
        ),
        col_school_esc_inbound=normalize_column_aliases(
            cols.get("school_esc_inbound"),
            field_name="columns.school_esc_inbound",
            default=["school_esc_inbound"],
        ),
        col_num_escortees=normalize_column_aliases(
            cols.get("num_escortees"),
            field_name="columns.num_escortees",
            default=["num_escortees", "num_escorted"],
        ),
        col_out_escorted_tour_ids=normalize_column_aliases(
            cols.get("out_escorted_tour_ids"),
            field_name="columns.out_escorted_tour_ids",
            default=["out_escorted_tour_ids"],
        ),
        col_inb_escorted_tour_ids=normalize_column_aliases(
            cols.get("inb_escorted_tour_ids"),
            field_name="columns.inb_escorted_tour_ids",
            default=["inb_escorted_tour_ids"],
        ),
        col_out_escorting_type=normalize_column_aliases(
            cols.get("out_escorting_type"),
            field_name="columns.out_escorting_type",
            default=["out_escorting_type"],
        ),
        col_inb_escorting_type=normalize_column_aliases(
            cols.get("inb_escorting_type"),
            field_name="columns.inb_escorting_type",
            default=["inb_escorting_type"],
        ),
        col_out_chauffeur_tour_id=normalize_column_aliases(
            cols.get("out_chauffeur_tour_id"),
            field_name="columns.out_chauffeur_tour_id",
            default=["out_chauffeur_tour_id"],
        ),
        col_inb_chauffeur_tour_id=normalize_column_aliases(
            cols.get("inb_chauffeur_tour_id"),
            field_name="columns.inb_chauffeur_tour_id",
            default=["inb_chauffeur_tour_id"],
        ),
        summary_categories=summary_categories,
        dashboard_labels=dashboard_labels,
        person_type_labels=person_type_labels,
        transit_subsidy_labels=transit_subsidy_labels,
        group_joint_tour_purposes=group_joint_tour_purposes,
        group_atwork_tour_purposes=group_atwork_tour_purposes,
        group_school_tour_purposes=group_school_tour_purposes,
        student_types=student_types,
        use_maz=bool(zones.get("use_maz", True)),
        maz_col=normalize_column_aliases(
            zones.get("maz_col"),
            field_name="zones.maz_col",
            default=["MAZ", "zone_id"],
        ),
        taz_col=normalize_column_aliases(
            zones.get("taz_col"),
            field_name="zones.taz_col",
            default=["TAZ", "taz"],
        ),
        geography_enabled=geo_enabled,
        geography_landuse_col=geo.get("landuse_col") if geo_enabled else None,
        geography_mapping=geo_mapping,
        geography_aggregations=geography_aggregations,
        segmentation=segmentation,
        skim_file=skim_cfg.get("file"),
        skim_matrix=skim_cfg.get("matrix", "SOV_DIST__MD"),
        mode_order=modes_cfg.get("order"),
            mode_groups=modes_cfg.get("groups"),
            pnr_tour_modes=(
                normalize_string_list(
                    summarize_cfg.get("pnr_tour_modes", modes_cfg.get("pnr_tour_modes")),
                    field_name=pnr_tour_modes_field_name,
                )
                if (
                    "pnr_tour_modes" in summarize_cfg
                    or "pnr_tour_modes" in modes_cfg
                )
                else ["PNR_TRANSIT"]
            ),
            runs=runs,
        )
    if not config.pnr_tour_modes:
        raise ValueError(f"{pnr_tour_modes_field_name} must resolve to at least one mode.")
    config.prepare_config_digest = digest_payload(config.prepare_signature_payload())
    config.summary_config_digest = digest_payload(config.summary_signature_payload())
    config.presentation_config_digest = digest_payload(
        config.presentation_signature_payload()
    )
    emit_grouped_legacy_summary(legacy_warnings)
    return config
