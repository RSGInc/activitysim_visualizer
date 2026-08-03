"""Parsers for independent top-level configuration sections."""

from __future__ import annotations

from .common import normalize_column_aliases
from .models import PipelineSettings


PIPELINE_STEP_ORDER = ("prepare", "skimjoin", "segment", "summarize", "dashboard")
VALID_PIPELINE_STEPS = set(PIPELINE_STEP_ORDER)
VALID_DASHBOARD_MODES = {"none", "live", "export", "host"}


def mapping(raw_value, *, field_name: str) -> dict:
    """Return one optional mapping with a consistent validation error."""
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")
    return raw_value


def parse_pipeline(raw_value) -> PipelineSettings:
    """Parse the canonical ``pipeline`` section."""
    default_steps = ("summarize", "dashboard")
    if raw_value is None:
        return PipelineSettings(steps=default_steps)
    if not isinstance(raw_value, dict):
        raise ValueError("pipeline must be a mapping when provided.")

    steps_raw = raw_value.get("steps")
    if steps_raw is None:
        steps = list(default_steps)
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
            if step not in VALID_PIPELINE_STEPS:
                raise ValueError(
                    "pipeline.steps contains unsupported step "
                    f"{step!r}. Allowed steps: {', '.join(PIPELINE_STEP_ORDER)}."
                )
            if step in seen_steps:
                raise ValueError(f"pipeline.steps contains duplicate step {step!r}.")
            seen_steps.add(step)
            steps.append(step)

    dashboard_mode = str(raw_value.get("dashboard_mode", "live")).strip().lower()
    if dashboard_mode not in VALID_DASHBOARD_MODES:
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


_SCALAR_COLUMN_DEFAULTS = {
    "col_ptype": ("ptype", "ptype"),
    "col_hhsize": ("hhsize", "hhsize"),
    "col_auto_ownership": ("auto_ownership", "auto_ownership"),
    "col_num_workers": ("num_workers", "num_workers"),
    "col_num_adults": ("num_adults", "num_adults"),
}

_ALIAS_COLUMN_DEFAULTS = {
    "col_household_id": ("household_id", ["household_id"]),
    "col_person_id": ("person_id", ["person_id"]),
    "col_tour_id": ("tour_id", ["tour_id"]),
    "col_trip_id": ("trip_id", ["trip_id"]),
    "col_tour_purpose": (
        "tour_purpose",
        ["tour_purpose", "primary_purpose", "tour_type", "purpose"],
    ),
    "col_trip_purpose": ("trip_purpose", ["trip_purpose", "purpose"]),
    "col_tour_mode": ("tour_mode", ["tour_mode"]),
    "col_trip_mode": ("trip_mode", ["trip_mode"]),
    "col_tour_category": ("tour_category", ["tour_category"]),
    "col_tour_start": ("tour_start", ["start", "start_hour"]),
    "col_tour_end": ("tour_end", ["end", "end_hour"]),
    "col_tour_duration": ("tour_duration", ["duration", "tourdur"]),
    "col_trip_depart": ("trip_depart", ["depart", "depart_hour"]),
    "col_total_employment": (
        "total_employment",
        [
            "EMP_TOTAL",
            "EMP_Total",
            "EMPLOY_TOT",
            "TOTEMP",
            "total_employment",
            "employment",
        ],
    ),
    "col_income_segment": (
        "income_segment",
        ["income_segment", "income_broad", "income"],
    ),
    "col_home_zone_id": ("home_zone_id", ["home_zone_id"]),
    "col_workplace_zone_id": ("workplace_zone_id", ["workplace_zone_id"]),
    "col_school_zone_id": ("school_zone_id", ["school_zone_id"]),
    "col_has_license": ("has_license", ["has_license"]),
    "col_mandatory_tour_frequency": (
        "mandatory_tour_frequency",
        ["mandatory_tour_frequency"],
    ),
    "col_is_student": ("is_student", ["is_student", "student"]),
    "col_is_university": ("is_university", ["is_university", "major_uni"]),
    "col_school_segment": ("school_segment", ["school_segment"]),
    "col_schg": ("schg", ["SCHG"]),
    "col_pstudent": ("pstudent", ["pstudent"]),
    "col_tour_origin": ("tour_origin", ["origin"]),
    "col_tour_destination": ("tour_destination", ["destination"]),
    "col_trip_origin": ("trip_origin", ["origin"]),
    "col_trip_destination": ("trip_destination", ["destination"]),
    "col_stop_frequency": ("stop_frequency", ["stop_frequency"]),
    "col_trip_outbound": ("trip_outbound", ["outbound"]),
    "col_trip_num": ("trip_num", ["trip_num"]),
    "col_pnr_zone_id": ("pnr_zone_id", ["pnr_zone_id"]),
    "col_pnr_lot_capacity": ("pnr_lot_capacity", ["PNR_SPACES"]),
    "col_is_worker": ("is_worker", ["is_worker"]),
    "col_adult": ("adult", ["adult", "is_adult"]),
    "col_day_id": ("day_id", ["day_id"]),
    "col_day_weight": ("day_weight", ["day_weight"]),
    "col_vehicle_id": ("vehicle_id", ["vehicle_id"]),
    "col_vehicle_num": ("vehicle_num", ["vehicle_num"]),
    "col_vehicle_type": ("vehicle_type", ["vehicle_type"]),
    "col_school_esc_outbound": (
        "school_esc_outbound",
        ["school_esc_outbound"],
    ),
    "col_school_esc_inbound": ("school_esc_inbound", ["school_esc_inbound"]),
    "col_num_escortees": ("num_escortees", ["num_escortees", "num_escorted"]),
    "col_out_escorted_tour_ids": (
        "out_escorted_tour_ids",
        ["out_escorted_tour_ids"],
    ),
    "col_inb_escorted_tour_ids": (
        "inb_escorted_tour_ids",
        ["inb_escorted_tour_ids"],
    ),
    "col_out_escorting_type": ("out_escorting_type", ["out_escorting_type"]),
    "col_inb_escorting_type": ("inb_escorting_type", ["inb_escorting_type"]),
    "col_out_chauffeur_tour_id": (
        "out_chauffeur_tour_id",
        ["out_chauffeur_tour_id"],
    ),
    "col_inb_chauffeur_tour_id": (
        "inb_chauffeur_tour_id",
        ["inb_chauffeur_tour_id"],
    ),
}

CANONICAL_COLUMN_KEYS = {
    yaml_field for yaml_field, _ in _SCALAR_COLUMN_DEFAULTS.values()
} | {
    yaml_field for yaml_field, _ in _ALIAS_COLUMN_DEFAULTS.values()
} | {"sample_rate"}


def parse_columns(raw_value) -> dict:
    """Parse ``columns`` into the corresponding ``Config`` constructor fields."""
    columns = mapping(raw_value, field_name="columns")
    fields = {
        config_field: columns.get(yaml_field, default)
        for config_field, (yaml_field, default) in _SCALAR_COLUMN_DEFAULTS.items()
    }
    fields["col_sample_rate"] = columns.get("sample_rate") or None
    fields.update(
        {
            config_field: normalize_column_aliases(
                columns.get(yaml_field),
                field_name=f"columns.{yaml_field}",
                default=default,
            )
            for config_field, (yaml_field, default) in _ALIAS_COLUMN_DEFAULTS.items()
        }
    )
    return fields


def parse_zones(raw_value) -> dict:
    """Parse ``zones`` into the corresponding ``Config`` constructor fields."""
    zones = mapping(raw_value, field_name="zones")
    return {
        "use_maz": bool(zones.get("use_maz", True)),
        "maz_col": normalize_column_aliases(
            zones.get("maz_col"),
            field_name="zones.maz_col",
            default=["MAZ", "zone_id"],
        ),
        "taz_col": normalize_column_aliases(
            zones.get("taz_col"),
            field_name="zones.taz_col",
            default=["TAZ", "taz"],
        ),
    }
