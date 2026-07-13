"""Parser for the canonical ``prepare`` section."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import PrepareAutoSufficiencySettings
from .normalize_categories import normalize_student_types
from .normalize_prepare import (
    normalize_prepare_non_motorized_distance_skim,
    normalize_prepare_relationship_checks,
    normalize_prepare_time_periods,
    normalize_prepare_vot_bins,
    normalize_prepared_output_file_format,
)
from .sections import mapping


@dataclass(frozen=True)
class ParsedPrepareSection:
    """Config constructor fields resolved from ``prepare``."""

    config_fields: dict
    distance_skim: dict


def parse_prepare(raw_value, *, config_dir: Path) -> ParsedPrepareSection:
    prepare = mapping(raw_value, field_name="prepare")
    output = mapping(prepare.get("output"), field_name="prepare.output")
    validation = mapping(
        prepare.get("validation"), field_name="prepare.validation"
    )
    distance_skim = mapping(
        prepare.get("distance_skim"), field_name="prepare.distance_skim"
    )

    basis_raw = prepare.get("auto_sufficiency_basis")
    if basis_raw is None:
        auto_sufficiency = PrepareAutoSufficiencySettings()
    elif not isinstance(basis_raw, str) or basis_raw.strip().lower() not in {
        "licensed_drivers",
        "workers",
        "adults",
    }:
        raise ValueError(
            "prepare.auto_sufficiency_basis must be one of "
            "'licensed_drivers', 'workers', or 'adults'."
        )
    else:
        auto_sufficiency = PrepareAutoSufficiencySettings(
            basis=basis_raw.strip().lower()
        )

    return ParsedPrepareSection(
        config_fields={
            "prepare_vot_bins": normalize_prepare_vot_bins(
                prepare.get("vot_bins"), field_name="prepare.vot_bins"
            ),
            "prepare_auto_sufficiency": auto_sufficiency,
            "prepare_time_periods": normalize_prepare_time_periods(
                prepare.get("time_periods"),
                field_name="prepare.time_periods",
                config_dir=config_dir,
            ),
            "prepare_non_motorized_distance_skim": (
                normalize_prepare_non_motorized_distance_skim(
                    prepare.get("non_motorized_distance_skim"),
                    field_name="prepare.non_motorized_distance_skim",
                    config_dir=config_dir,
                )
            ),
            "prepare_output_file_format": normalize_prepared_output_file_format(
                output.get("file_format"), field_name="prepare.output.file_format"
            ),
            "prepare_relationship_checks": normalize_prepare_relationship_checks(
                validation.get("relationship_checks"),
                field_name="prepare.validation.relationship_checks",
            ),
            "student_types": normalize_student_types(
                prepare.get("student_types"), field_name="prepare.student_types"
            ),
        },
        distance_skim=distance_skim,
    )
