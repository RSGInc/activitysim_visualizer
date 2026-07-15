"""Top-level YAML loading and config assembly."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypeVar

import yaml

from .common import (
    normalize_optional_bool,
    normalize_string_list,
)
from .constants import DEFAULT_RUN_COLORS, FILE_MAPPING_DEFAULTS
from .models import (
    Config,
    GeographyAggregationSettings,
)
from .normalize_categories import (
    category_spec_from_mapping,
    category_spec_from_sequence,
    normalize_categories,
    normalize_escort_category_spec,
)
from .normalize_export import (
    normalize_dashboard_page_entries,
)
from .normalize_geography import normalize_geography_aggregations
from .normalize_prepare import (
    normalize_fallback_file_mapping,
    normalize_file_mapping,
    normalize_runs,
)
from .normalize_segmentation import normalize_segmentation
from .normalize_skimjoin import normalize_skimjoin_settings
from .schema import validate_canonical_config
from .sections import mapping, parse_columns, parse_pipeline, parse_zones
from .sections_dashboard import parse_dashboard_export
from .sections_prepare import parse_prepare
from .signatures import digest_payload
from runtime.weighting import (
    load_weighting_mode_extensions,
    normalize_weighting_modes,
    weighting_mode_definitions,
)

ConfigT = TypeVar("ConfigT", bound=Config)

def load_config_from_yaml(path: str | Path, *, cls: type[ConfigT] = Config) -> ConfigT:
    config_path = Path(path).resolve()
    config_bytes = config_path.read_bytes()
    raw = yaml.safe_load(config_bytes.decode("utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config file must parse to a mapping.")
    validate_canonical_config(raw)
    extensions_cfg = mapping(raw.get("extensions"), field_name="extensions")
    extension_modules = normalize_string_list(
        extensions_cfg.get("modules"),
        field_name="extensions.modules",
    )
    extension_settings = dict(
        mapping(
            extensions_cfg.get("settings"),
            field_name="extensions.settings",
        )
    )
    load_weighting_mode_extensions(extension_modules)
    pipeline = parse_pipeline(raw.get("pipeline"))
    dashboard_cfg = mapping(raw.get("dashboard"), field_name="dashboard")
    dashboard_live_cfg = mapping(dashboard_cfg.get("live"), field_name="dashboard.live")
    summarize_cfg = mapping(raw.get("summarize"), field_name="summarize")
    display_cfg = mapping(raw.get("display"), field_name="display")
    segment_cfg = mapping(raw.get("segment"), field_name="segment")

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

    column_fields = parse_columns(raw.get("columns"))
    zone_fields = parse_zones(raw.get("zones"))
    geo = mapping(summarize_cfg.get("geography"), field_name="summarize.geography")

    prepare = parse_prepare(raw.get("prepare"), config_dir=config_path.parent)

    geo_enabled = bool(geo.get("enabled", False))
    geo_mapping = None
    if geo_enabled and "mapping" in geo:
        geo_mapping = {str(k): str(v) for k, v in geo["mapping"].items()}
    geography_aggregations = (
        normalize_geography_aggregations(
            geo,
            field_name="summarize.geography",
            config_dir=config_path.parent,
        )
        if geo_enabled
        else GeographyAggregationSettings(enabled=False)
    )

    segmentation = normalize_segmentation(
        {**segment_cfg, "enabled": pipeline.has_step("segment")},
        field_name="segment",
        config_dir=config_path.parent,
    )

    skim_cfg = prepare.distance_skim
    skimjoin = normalize_skimjoin_settings(
        raw.get("skimjoin"),
        config_dir=config_path.parent,
        default_enabled=pipeline.has_step("skimjoin"),
    )
    modes_cfg = raw.get("modes", {})
    if not isinstance(modes_cfg, dict):
        raise ValueError("modes must be a mapping when provided.")
    dashboard_pages_cfg = dashboard_live_cfg.get("pages")
    dashboard_pages = (
        None
        if dashboard_pages_cfg is None
        else normalize_dashboard_page_entries(
            dashboard_pages_cfg,
            field_name="dashboard.live.pages",
        )
    )

    summary_root_raw = raw.get("root", "artifacts/summary_cache")
    summary_root = Path(summary_root_raw)
    if not summary_root.is_absolute():
        summary_root = (config_path.parent / summary_root).resolve()

    weighting_modes = normalize_weighting_modes(
        summarize_cfg.get("weighting_modes"),
        field_name="summarize.weighting_modes",
    )
    selected_weighting_definitions = weighting_mode_definitions(
        weighting_modes,
        field_name="summarize.weighting_modes",
    )

    summary_failure_policy = str(
        summarize_cfg.get("failure_policy", "record")
    ).strip().lower()
    if summary_failure_policy not in {"record", "error"}:
        raise ValueError(
            "summarize.failure_policy must be either 'record' or 'error'."
        )

    export_html = parse_dashboard_export(
        dashboard_cfg.get("export"),
        pipeline=pipeline,
        segmentation=segmentation,
        summary_root=summary_root,
        weighting_modes=weighting_modes,
        weighting_labels={
            definition.mode_id: definition.label
            for definition in selected_weighting_definitions
        },
    )

    dashboard_title = dashboard_cfg.get("title", "ActivitySim Visualizer")
    log_level = str(raw.get("log_level", "INFO")).strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(
            "log_level must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )
    run_colors = display_cfg.get("run_colors", list(DEFAULT_RUN_COLORS))
    if not isinstance(run_colors, list):
        raise ValueError("display.run_colors must be a list when provided.")
    missing_data_display = str(
        display_cfg.get("missing_data_display", "card")
    ).strip().lower()
    if missing_data_display not in {"card", "blank"}:
        raise ValueError("display.missing_data_display must be either 'card' or 'blank'.")
    bar_hover_mode = str(display_cfg.get("bar_hover_mode", "closest")).strip().lower()
    if bar_hover_mode not in {"closest", "all"}:
        raise ValueError("display.bar_hover_mode must be either 'closest' or 'all'.")
    density_hover_mode = str(
        display_cfg.get("density_hover_mode", "closest")
    ).strip().lower()
    if density_hover_mode not in {"closest", "all"}:
        raise ValueError(
            "display.density_hover_mode must be either 'closest' or 'all'."
        )
    enable_maz_geographies_raw = dashboard_cfg.get("enable_maz_geographies", False)
    if not isinstance(enable_maz_geographies_raw, bool):
        raise ValueError(
            "dashboard.enable_maz_geographies must be true or false when provided."
        )

    summary_categories = normalize_categories(
        summarize_cfg.get("category_normalization"),
        field_name="summarize.category_normalization",
    )
    dashboard_labels = normalize_categories(
        display_cfg.get("labels"),
        field_name="display.labels",
    )
    if "geography" not in summary_categories and geo_mapping:
        geography_spec = category_spec_from_mapping(geo_mapping)
        if geography_spec is not None:
            summary_categories["geography"] = geography_spec
    if "geography" not in dashboard_labels and geo_mapping:
        geography_spec = category_spec_from_mapping(geo_mapping)
        if geography_spec is not None:
            dashboard_labels["geography"] = geography_spec
    if "mode" not in dashboard_labels:
        mode_spec = category_spec_from_sequence(modes_cfg.get("order"))
        if mode_spec is not None:
            dashboard_labels["mode"] = mode_spec
    summary_categories["escort"] = normalize_escort_category_spec(
        summary_categories.get("escort")
    )
    dashboard_labels["escort"] = normalize_escort_category_spec(
        dashboard_labels.get("escort")
    )

    group_joint_tour_purposes = (
        normalize_optional_bool(
            summarize_cfg.get("group_joint_tour_purposes"),
            field_name="summarize.group_joint_tour_purposes",
        )
        if "group_joint_tour_purposes" in summarize_cfg
        else True
    )
    group_atwork_tour_purposes = (
        normalize_optional_bool(
            summarize_cfg.get("group_atwork_tour_purposes"),
            field_name="summarize.group_atwork_tour_purposes",
        )
        if "group_atwork_tour_purposes" in summarize_cfg
        else True
    )
    group_school_tour_purposes = (
        normalize_optional_bool(
            summarize_cfg.get("group_school_tour_purposes"),
            field_name="summarize.group_school_tour_purposes",
        )
        if "group_school_tour_purposes" in summarize_cfg
        else True
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
        weighting_mode_definitions=selected_weighting_definitions,
        extension_modules=tuple(extension_modules),
        extension_settings=extension_settings,
        summary_failure_policy=summary_failure_policy,
        export_html=export_html,
        skimjoin=skimjoin,
        **prepare.config_fields,
        files=files,
        fallback_files=fallback_files,
        **column_fields,
        summary_categories=summary_categories,
        dashboard_labels=dashboard_labels,
        group_joint_tour_purposes=group_joint_tour_purposes,
        group_atwork_tour_purposes=group_atwork_tour_purposes,
        group_school_tour_purposes=group_school_tour_purposes,
        **zone_fields,
        geography_enabled=geo_enabled,
        geography_landuse_col=geo.get("landuse_col") if geo_enabled else None,
        geography_mapping=geo_mapping,
        geography_aggregations=geography_aggregations,
        segmentation=segmentation,
        skim_file=skim_cfg.get("file"),
        skim_matrix=skim_cfg.get("matrix", "SOV_DIST__MD"),
        mode_groups=modes_cfg.get("groups"),
        pnr_tour_modes=(
            normalize_string_list(
                summarize_cfg.get("pnr_tour_modes"),
                field_name="summarize.pnr_tour_modes",
            )
            if "pnr_tour_modes" in summarize_cfg
            else ["PNR_TRANSIT"]
        ),
        runs=runs,
    )
    if not config.pnr_tour_modes:
        raise ValueError("summarize.pnr_tour_modes must resolve to at least one mode.")
    config.prepare_config_digest = digest_payload(config.prepare_signature_payload())
    config.summary_config_digest = digest_payload(config.summary_signature_payload())
    config.presentation_config_digest = digest_payload(
        config.presentation_signature_payload()
    )
    return config
