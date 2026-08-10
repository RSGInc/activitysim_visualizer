"""Digest and signature-payload helpers for config contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import Config, PreparedColumnSegmentationSource
from .normalize_categories import category_specs_payload


def digest_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _geography_payload(config: Config) -> dict[str, Any]:
    geography_payload: dict[str, Any] = {"enabled": config.geography_enabled}
    if config.geography_enabled:
        geography_spec = config.summary_category_spec("geography")
        geography_payload["landuse_col"] = config.geography_landuse_col
        geography_payload["mapping"] = (
            dict(geography_spec.mapping_items)
            if geography_spec is not None and geography_spec.mapping_items
            else (
                {
                    key: config.geography_mapping[key]
                    for key in sorted(config.geography_mapping)
                }
                if config.geography_mapping
                else None
            )
        )
    geography_payload["aggregations"] = [
        {
            "name": aggregation.name,
            "source_zone_system": aggregation.source_zone_system,
            "file": aggregation.file,
            "zone_id_col": aggregation.zone_id_col,
            "geography_col": aggregation.geography_col,
            "lookup_rows": [
                {"zone_id": zone_id, "geography_id": geography_id}
                for zone_id, geography_id in aggregation.lookup_rows
            ],
        }
        for aggregation in config.geography_aggregations.aggregations
    ]
    return geography_payload


def _student_types_payload(config: Config) -> list[dict[str, Any]]:
    return [
        {
            "label": entry.label,
            "land_use_columns": list(entry.land_use_columns),
            "person": (
                {
                    "is_university": entry.person.is_university,
                    "school_segment": list(entry.person.school_segment),
                    "SCHG": list(entry.person.SCHG),
                    "pstudent": list(entry.person.pstudent),
                }
                if entry.person is not None
                else None
            ),
        }
        for entry in config.student_types
    ]


def prepare_signature_payload(config: Config) -> dict[str, Any]:
    return {
        "files": {key: config.files[key] for key in sorted(config.files)},
        "columns": {
            "ptype": config.col_ptype,
            "hhsize": config.col_hhsize,
            "auto_ownership": config.col_auto_ownership,
            "num_workers": config.col_num_workers,
            "num_adults": config.col_num_adults,
            "sample_rate": config.col_sample_rate,
            "household_id": list(config.col_household_id),
            "person_id": list(config.col_person_id),
            "tour_id": list(config.col_tour_id),
            "trip_id": list(config.col_trip_id),
            "tour_purpose": list(config.col_tour_purpose),
            "trip_purpose": list(config.col_trip_purpose),
            "tour_mode": list(config.col_tour_mode),
            "trip_mode": list(config.col_trip_mode),
            "tour_category": list(config.col_tour_category),
            "tour_start": list(config.col_tour_start),
            "tour_end": list(config.col_tour_end),
            "tour_duration": list(config.col_tour_duration),
            "trip_depart": list(config.col_trip_depart),
            "total_employment": list(config.col_total_employment),
            "income_segment": list(config.col_income_segment),
            "pnr_zone_id": list(config.col_pnr_zone_id),
            "pnr_lot_capacity": list(config.col_pnr_lot_capacity),
            "is_worker": list(config.col_is_worker),
            "adult": list(config.col_adult),
            "school_esc_outbound": list(config.col_school_esc_outbound),
            "school_esc_inbound": list(config.col_school_esc_inbound),
            "num_escortees": list(config.col_num_escortees),
            "out_escorted_tour_ids": list(config.col_out_escorted_tour_ids),
            "inb_escorted_tour_ids": list(config.col_inb_escorted_tour_ids),
            "out_escorting_type": list(config.col_out_escorting_type),
            "inb_escorting_type": list(config.col_inb_escorting_type),
            "out_chauffeur_tour_id": list(config.col_out_chauffeur_tour_id),
            "inb_chauffeur_tour_id": list(config.col_inb_chauffeur_tour_id),
        },
        "tour_purpose_grouping": {
            "group_joint_tour_purposes": config.group_joint_tour_purposes,
            "group_atwork_tour_purposes": config.group_atwork_tour_purposes,
            "group_school_tour_purposes": config.group_school_tour_purposes,
        },
        "student_types": _student_types_payload(config),
        "zones": {
            "use_maz": config.use_maz,
            "maz_col": list(config.maz_col),
            "taz_col": list(config.taz_col),
        },
        "geography": _geography_payload(config),
        "skim": {"matrix": config.skim_matrix},
        "skimjoin": {
            "enabled": config.skimjoin_step_enabled(),
            "config_digest": config.skimjoin.config_digest,
            "create_hypothetical_skim_tables": (
                config.skimjoin.create_hypothetical_skim_tables
            ),
            "failure_policy": config.skimjoin.failure_policy,
        },
        "prepare": {
            "auto_sufficiency": {
                "basis": config.prepare_auto_sufficiency.basis,
            },
            "output": {"file_format": config.prepare_output_file_format},
            "time_periods": {
                "enabled": config.prepare_time_periods.enabled,
                "network_los_file": config.prepare_time_periods.network_los_file,
                "network_los_digest": config.prepare_time_periods.network_los_digest,
                "trip_period_number_column": (
                    config.prepare_time_periods.trip_period_number_column
                ),
                "tour_start_period_number_column": (
                    config.prepare_time_periods.tour_start_period_number_column
                ),
                "tour_end_period_number_column": (
                    config.prepare_time_periods.tour_end_period_number_column
                ),
            },
            "non_motorized_distance_skim": {
                "enabled": config.prepare_non_motorized_distance_skim.enabled,
                "file": config.prepare_non_motorized_distance_skim.file,
                "file_digest": config.prepare_non_motorized_distance_skim.file_digest,
                "matrix": config.prepare_non_motorized_distance_skim.matrix,
                "source_type": (
                    config.prepare_non_motorized_distance_skim.source_type
                ),
                "value_column": (
                    config.prepare_non_motorized_distance_skim.value_column
                ),
            },
            "vot_bins": {
                "enabled": config.prepare_vot_bins.enabled,
                "source_column": config.prepare_vot_bins.source_column,
                "output_column": config.prepare_vot_bins.output_column,
                "fallback_value": config.prepare_vot_bins.fallback_value,
                "mappings": {
                    run_name: {
                        key: value for key, value in sorted(run_mapping.items())
                    }
                    for run_name, run_mapping in sorted(
                        config.prepare_vot_bins.mappings.items()
                    )
                },
            },
        },
    }


def base_prepare_signature_payload(config: Config) -> dict[str, Any]:
    """Return preparation identity before optional skim enrichment."""
    payload = prepare_signature_payload(config)
    payload.pop("skimjoin", None)
    return payload


def summary_signature_payload(config: Config) -> dict[str, Any]:
    return {
        "weighting_modes": [
            definition.signature_payload()
            for definition in config.weighting_mode_definitions
        ],
        "extension_settings": config.extension_settings,
        "failure_policy": config.summary_failure_policy,
        "files": {key: config.files[key] for key in sorted(config.files)},
        "columns": prepare_signature_payload(config)["columns"],
        "summary_categories": category_specs_payload(config.summary_categories),
        # These labels are still materialized by demographic/person summaries.
        # Keep them in the summary identity until phase 4 moves labeling fully
        # into the dashboard presentation boundary.
        "display_label_dependencies": {
            category_id: (
                dict(config.dashboard_label_spec(category_id).mapping_items)
                if config.dashboard_label_spec(category_id) is not None
                else None
            )
            for category_id in ("person_type", "transit_subsidy")
        },
        "tour_purpose_grouping": {
            "group_joint_tour_purposes": config.group_joint_tour_purposes,
            "group_atwork_tour_purposes": config.group_atwork_tour_purposes,
            "group_school_tour_purposes": config.group_school_tour_purposes,
        },
        "student_types": _student_types_payload(config),
        "zones": {
            "use_maz": config.use_maz,
            "maz_col": list(config.maz_col),
            "taz_col": list(config.taz_col),
        },
        "geography": _geography_payload(config),
        "skim": {"matrix": config.skim_matrix},
        "modes": {
            "groups": (
                [
                    (group_name, list(mode_names))
                    for group_name, mode_names in config.mode_groups.items()
                ]
                if config.mode_groups
                else None
            ),
            "pnr_tour_modes": list(config.pnr_tour_modes),
        },
        "skimjoin": {
            "enabled": config.skimjoin_step_enabled(),
            "config_digest": config.skimjoin.config_digest,
            "create_hypothetical_skim_tables": (
                config.skimjoin.create_hypothetical_skim_tables
            ),
            "failure_policy": config.skimjoin.failure_policy,
        },
        "prepare": {
            "vot_bins": prepare_signature_payload(config)["prepare"]["vot_bins"],
        },
    }


def segmentation_unit_signature_payload(
    config: Config,
    *,
    segmentation_type: str,
    segment_id: str,
) -> dict[str, Any]:
    """Return the cache identity for one full or segmented analysis unit."""
    if segmentation_type == "full" and segment_id == "full":
        return {"segmentation_type": "full", "segment_id": "full"}

    definition = config.segmentation.definition_by_name(segmentation_type)
    if definition is None or definition.source is None:
        return {"segmentation_type": segmentation_type, "segment_id": segment_id}
    segment = next(
        (candidate for candidate in definition.segments if candidate.id == segment_id),
        None,
    )
    if segment is None:
        return {"segmentation_type": segmentation_type, "segment_id": segment_id}

    source = definition.source
    if isinstance(source, PreparedColumnSegmentationSource):
        source_payload: dict[str, Any] = {
            "type": "prepared_column",
            "column": source.column,
            "source_table": source.source_table,
        }
    else:
        segment_values = set(segment.values)
        source_payload = {
            "type": "csv_lookup",
            "file": source.file,
            "join_source_table": source.join_source_table,
            "join_source_key_column": source.join_source_key_column,
            "csv_key_column": source.csv_key_column,
            "segment_value_column": source.segment_value_column,
            "lookup_rows": [
                {"key": key, "value": value}
                for key, value in source.lookup_rows
                if value in segment_values
            ],
        }
    return {
        "segmentation_type": segmentation_type,
        "segment_id": segment.id,
        "segment_label": segment.label,
        "segment_values": list(segment.values),
        "source": source_payload,
    }


def presentation_signature_payload(config: Config) -> dict[str, Any]:
    return {
        "dashboard_title": config.dashboard_title,
        "dashboard_logo": config.dashboard_logo,
        "log_level": config.log_level,
        "dashboard_pages": (
            [
                {
                    "page_id": entry.page_id,
                    "mode": entry.mode,
                    "page_ids": list(entry.page_ids),
                }
                for entry in config.dashboard_pages
            ]
            if config.dashboard_pages is not None
            else None
        ),
        "include_notes": config.include_notes,
        "enable_maz_geographies": config.enable_maz_geographies,
        "run_colors": list(config.run_colors),
        "missing_data_display": config.missing_data_display,
        "bar_hover_mode": config.bar_hover_mode,
        "density_hover_mode": config.density_hover_mode,
        "weighting_modes": [
            {"mode_id": definition.mode_id, "label": definition.label}
            for definition in config.weighting_mode_definitions
        ],
        "segmentation": {
            "enabled": config.segmentation.enabled,
            "dashboard": {
                "segmentation_type": config.segmentation.dashboard.segmentation_type,
                "visibility": config.segmentation.dashboard.visibility,
            },
        },
        "dashboard_labels": category_specs_payload(config.dashboard_labels),
        "export_html": {
            "enabled": config.export_html.enabled,
            "output_path": config.export_html.output_path,
            "dashboard": {
                "weighting": list(config.export_html.dashboard.weighting),
                "values": list(config.export_html.dashboard.values),
                "segmentation_type": config.export_html.dashboard.segmentation_type,
                "segmentation_visibility": config.export_html.dashboard.segmentation_visibility,
            },
            "pages_configured": config.export_html.pages_configured,
            "exclude_pages": list(config.export_html.exclude_pages),
            "exclude_groups": list(config.export_html.exclude_groups),
            "pages": [
                {
                    "page_id": page_id,
                    "enabled": override.enabled,
                    "selectors": {
                        selector_id: {
                            "mode": request.mode,
                            "values": list(request.values),
                        }
                        for selector_id, request in override.selector_requests.items()
                    },
                    "parts": {
                        part_id: {"enabled": part.enabled}
                        for part_id, part in override.parts.items()
                    },
                }
                for page_id, override in config.export_html.pages.items()
            ],
        },
    }
