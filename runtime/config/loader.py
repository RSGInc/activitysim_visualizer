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
)
from .constants import DEFAULT_RUN_COLORS, FILE_MAPPING_DEFAULTS
from .legacy import warn_ignored_legacy_key, warn_supported_legacy_key
from .models import (
    Config,
    ExportDashboardSettings,
    ExportHTMLSettings,
    ExportSelectorRequest,
    GeographyAggregationSettings,
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
    normalize_prepare_vot_bins,
    normalize_prepared_output_file_format,
    normalize_runs,
)
from .normalize_segmentation import normalize_segmentation
from .normalize_skimjoin import normalize_skimjoin_settings
from .signatures import digest_payload

ConfigT = TypeVar("ConfigT", bound=Config)


def load_config_from_yaml(path: str | Path, *, cls: type[ConfigT] = Config) -> ConfigT:
    config_path = Path(path).resolve()
    config_bytes = config_path.read_bytes()
    raw = yaml.safe_load(config_bytes.decode("utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config file must parse to a mapping.")

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

    skim_cfg = raw.get("skim", {})
    if not isinstance(skim_cfg, dict):
        raise ValueError("skim must be a mapping when provided.")
    skimjoin = normalize_skimjoin_settings(
        raw.get("skimjoin"),
        config_dir=config_path.parent,
    )
    prepare_vot_bins = normalize_prepare_vot_bins(
        prepare_cfg.get("vot_bins"),
        field_name="prepare.vot_bins",
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
        )
    warn_ignored_legacy_key(
        mapping=raw,
        key="dashboard_pages",
        legacy_field_name="dashboard_pages",
        replacement_field_name="visualizer.dashboard_pages",
    )
    warn_ignored_legacy_key(
        mapping=raw,
        key="run_colors",
        legacy_field_name="run_colors",
        replacement_field_name="visualizer.run_colors",
    )
    warn_ignored_legacy_key(
        mapping=outputs_cfg,
        key="summary_root",
        legacy_field_name="outputs.summary_root",
        replacement_field_name="processor.root",
    )
    warn_ignored_legacy_key(
        mapping=outputs_cfg,
        key="weighting_modes",
        legacy_field_name="outputs.weighting_modes",
        replacement_field_name="processor.summaries.weighting_modes",
    )
    warn_ignored_legacy_key(
        mapping=outputs_cfg,
        key="export_html",
        legacy_field_name="outputs.export_html",
        replacement_field_name="visualizer.export_html",
    )
    warn_supported_legacy_key(
        mapping=summaries_cfg,
        key="root",
        legacy_field_name="summaries.root",
        replacement_field_name="processor.root",
    )
    warn_supported_legacy_key(
        mapping=summaries_cfg,
        key="weighting_modes",
        legacy_field_name="summaries.weighting_modes",
        replacement_field_name="processor.summaries.weighting_modes",
    )

    dashboard_pages_cfg = visualizer_cfg.get("dashboard_pages")
    dashboard_pages = (
        None
        if dashboard_pages_cfg is None
        else normalize_dashboard_page_entries(
            dashboard_pages_cfg,
            field_name="visualizer.dashboard_pages",
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
    )
    warn_ignored_legacy_key(
        mapping=export_html_cfg,
        key="values",
        legacy_field_name="visualizer.export_html.values",
        replacement_field_name="visualizer.export_html.dashboard.values",
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
    run_colors = visualizer_cfg.get("run_colors", list(DEFAULT_RUN_COLORS))
    if not isinstance(run_colors, list):
        raise ValueError("visualizer.run_colors must be a list when provided.")
    missing_data_display = str(visualizer_cfg.get("missing_data_display", "card")).strip().lower()
    if missing_data_display not in {"card", "blank"}:
        raise ValueError("visualizer.missing_data_display must be either 'card' or 'blank'.")
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
            raw.get("group_joint_tour_purposes"),
            field_name="group_joint_tour_purposes",
        )
        if raw.get("group_joint_tour_purposes") is not None
        else True
    )
    group_atwork_tour_purposes = (
        normalize_optional_bool(
            raw.get("group_atwork_tour_purposes"),
            field_name="group_atwork_tour_purposes",
        )
        if raw.get("group_atwork_tour_purposes") is not None
        else True
    )
    group_school_tour_purposes = (
        normalize_optional_bool(
            raw.get("group_school_tour_purposes"),
            field_name="group_school_tour_purposes",
        )
        if raw.get("group_school_tour_purposes") is not None
        else True
    )
    student_types = normalize_student_types(
        raw.get("student_types"),
        field_name="student_types",
    )

    config = cls(
        config_path=str(config_path),
        config_digest=hashlib.sha256(config_bytes).hexdigest(),
        prepare_config_digest="",
        summary_config_digest="",
        presentation_config_digest="",
        name=raw.get("name", ""),
        dashboard_title=str(dashboard_title),
        dashboard_pages=dashboard_pages,
        enable_maz_geographies=enable_maz_geographies_raw,
        run_colors=run_colors,
        missing_data_display=missing_data_display,
        summary_root=str(summary_root),
        weighting_modes=weighting_modes,
        export_html=export_html,
        skimjoin=skimjoin,
        prepare_vot_bins=prepare_vot_bins,
        prepare_auto_sufficiency=prepare_auto_sufficiency,
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
        runs=runs,
    )
    config.prepare_config_digest = digest_payload(config.prepare_signature_payload())
    config.summary_config_digest = digest_payload(config.summary_signature_payload())
    config.presentation_config_digest = digest_payload(
        config.presentation_signature_payload()
    )
    return config
