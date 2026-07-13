"""Validation for the canonical application config surface."""

from __future__ import annotations

from collections.abc import Mapping

from .sections import CANONICAL_COLUMN_KEYS


CANONICAL_TOP_LEVEL_KEYS = {
    "columns",
    "dashboard",
    "display",
    "fallback_files",
    "files",
    "log_level",
    "modes",
    "name",
    "pipeline",
    "prepare",
    "root",
    "runs",
    "segment",
    "skimjoin",
    "summarize",
    "zones",
}

REMOVED_TOP_LEVEL_KEYS = {
    "categories": "Use summarize.category_normalization and display.labels.",
    "dashboard_labels": "Use display.labels.",
    "dashboard_pages": "Use dashboard.live.pages.",
    "dashboard_title": "Use dashboard.title.",
    "geography": "Use summarize.geography.",
    "group_atwork_tour_purposes": "Use summarize.group_atwork_tour_purposes.",
    "group_joint_tour_purposes": "Use summarize.group_joint_tour_purposes.",
    "group_school_tour_purposes": "Use summarize.group_school_tour_purposes.",
    "outputs": "Use root, summarize, and dashboard.export.",
    "person_types": "Use display.labels.person_type.",
    "processor": "Use root, prepare, and summarize.",
    "run_colors": "Use display.run_colors.",
    "segmentation": "Use segment.",
    "skim": "Use prepare.distance_skim.",
    "student_types": "Use prepare.student_types.",
    "summaries": "Use root and summarize.",
    "summary_categories": "Use summarize.category_normalization.",
    "transit_subsidies": "Use display.labels.transit_subsidy.",
    "visualizer": "Use dashboard and display.",
}


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping when provided.")
    return value


def _reject_keys(
    mapping: Mapping[str, object],
    *,
    field_name: str,
    replacements: Mapping[str, str],
) -> None:
    removed = [key for key in replacements if key in mapping]
    if not removed:
        return
    details = "; ".join(
        f"{field_name}.{key}: {replacements[key]}" for key in removed
    )
    raise ValueError(f"Removed config keys are not supported: {details}")


def _reject_unknown_keys(
    section: Mapping[str, object],
    *,
    field_name: str,
    allowed: set[str],
) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(
            f"Unknown {field_name} config keys: "
            + ", ".join(repr(key) for key in unknown)
        )


def validate_canonical_config(raw: Mapping[str, object]) -> None:
    """Reject removed and unknown keys before normalization can ignore them."""
    removed = [key for key in REMOVED_TOP_LEVEL_KEYS if key in raw]
    if removed:
        details = "; ".join(
            f"{key}: {REMOVED_TOP_LEVEL_KEYS[key]}" for key in removed
        )
        raise ValueError(f"Removed config keys are not supported: {details}")

    unknown = sorted(set(raw) - CANONICAL_TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(
            "Unknown top-level config keys: "
            + ", ".join(repr(key) for key in unknown)
        )

    dashboard = _mapping(raw.get("dashboard"), field_name="dashboard")
    _reject_unknown_keys(
        dashboard,
        field_name="dashboard",
        allowed={"title", "live", "export", "enable_maz_geographies", "pages"},
    )
    _reject_keys(
        dashboard,
        field_name="dashboard",
        replacements={"pages": "Use dashboard.live.pages."},
    )
    export = _mapping(dashboard.get("export"), field_name="dashboard.export")
    live = _mapping(dashboard.get("live"), field_name="dashboard.live")
    _reject_unknown_keys(
        live,
        field_name="dashboard.live",
        allowed={"pages"},
    )
    _reject_unknown_keys(
        export,
        field_name="dashboard.export",
        allowed={
            "output_path",
            "dashboard",
            "pages",
            "exclude_pages",
            "exclude_groups",
            "enabled",
            "weighting",
            "values",
        },
    )
    _reject_keys(
        export,
        field_name="dashboard.export",
        replacements={
            "enabled": "Use pipeline.dashboard_mode.",
            "weighting": "Use dashboard.export.dashboard.weighting.",
            "values": "Use dashboard.export.dashboard.values.",
        },
    )

    summarize = _mapping(raw.get("summarize"), field_name="summarize")
    _reject_unknown_keys(
        summarize,
        field_name="summarize",
        allowed={
            "weighting_modes",
            "geography",
            "category_normalization",
            "group_joint_tour_purposes",
            "group_atwork_tour_purposes",
            "group_school_tour_purposes",
            "pnr_tour_modes",
            "summary_categories",
        },
    )
    _reject_keys(
        summarize,
        field_name="summarize",
        replacements={
            "summary_categories": "Use summarize.category_normalization."
        },
    )

    segment = _mapping(raw.get("segment"), field_name="segment")
    _reject_unknown_keys(
        segment,
        field_name="segment",
        allowed={"dashboard", "definitions", "enabled"},
    )
    _reject_keys(
        segment,
        field_name="segment",
        replacements={"enabled": "Use pipeline.steps."},
    )

    skimjoin = _mapping(raw.get("skimjoin"), field_name="skimjoin")
    _reject_unknown_keys(
        skimjoin,
        field_name="skimjoin",
        allowed={
            "defaults",
            "create_hypothetical_skim_tables",
            "generate_hypothetical_sidecars",
            "config_path",
            "distance_skim",
            "enabled",
        },
    )
    _reject_keys(
        skimjoin,
        field_name="skimjoin",
        replacements={
            "config_path": "Use skimjoin.defaults.config_path.",
            "distance_skim": "Use prepare.distance_skim.",
            "enabled": "Use pipeline.steps.",
        },
    )

    modes = _mapping(raw.get("modes"), field_name="modes")
    _reject_unknown_keys(
        modes,
        field_name="modes",
        allowed={"order", "groups", "pnr_tour_modes"},
    )
    _reject_keys(
        modes,
        field_name="modes",
        replacements={"pnr_tour_modes": "Use summarize.pnr_tour_modes."},
    )

    pipeline = _mapping(raw.get("pipeline"), field_name="pipeline")
    _reject_unknown_keys(
        pipeline,
        field_name="pipeline",
        allowed={"steps", "dashboard_mode", "overwrite"},
    )

    display = _mapping(raw.get("display"), field_name="display")
    _reject_unknown_keys(
        display,
        field_name="display",
        allowed={
            "labels",
            "run_colors",
            "missing_data_display",
            "bar_hover_mode",
            "density_hover_mode",
        },
    )

    prepare = _mapping(raw.get("prepare"), field_name="prepare")
    _reject_unknown_keys(
        prepare,
        field_name="prepare",
        allowed={
            "output",
            "validation",
            "distance_skim",
            "vot_bins",
            "time_periods",
            "non_motorized_distance_skim",
            "auto_sufficiency_basis",
            "student_types",
        },
    )

    columns = _mapping(raw.get("columns"), field_name="columns")
    _reject_unknown_keys(
        columns,
        field_name="columns",
        allowed=CANONICAL_COLUMN_KEYS,
    )

    zones = _mapping(raw.get("zones"), field_name="zones")
    _reject_unknown_keys(
        zones,
        field_name="zones",
        allowed={"use_maz", "maz_col", "taz_col"},
    )
