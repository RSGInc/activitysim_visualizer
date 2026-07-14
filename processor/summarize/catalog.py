"""Deterministic catalog assembled from explicitly imported owning modules."""

from __future__ import annotations

from types import ModuleType

from processor.summarize.contracts import SummaryDefinition, get_summary_definition
from processor.summarize.summaries import (
    daily_travel_activity,
    daily_travel_escort_counts,
    daily_travel_escort_distributions,
    demographics,
    joint_travel,
    legacy,
    long_term_distance,
    long_term_geography,
    long_term_person,
    long_term_vehicle,
    skimjoin,
    tour,
    tour_geography,
    tour_profiles,
    tour_vehicles,
    trip,
    trip_distributions,
    validation,
    validation_scaffolds,
)

SUMMARY_MODULES: tuple[ModuleType, ...] = (
    demographics,
    long_term_person,
    long_term_vehicle,
    long_term_geography,
    long_term_distance,
    daily_travel_activity,
    daily_travel_escort_counts,
    daily_travel_escort_distributions,
    joint_travel,
    tour,
    tour_vehicles,
    tour_profiles,
    tour_geography,
    trip,
    trip_distributions,
    skimjoin,
    validation,
    validation_scaffolds,
    legacy,
)


def build_summary_catalog(
    modules: tuple[ModuleType, ...] = SUMMARY_MODULES,
) -> tuple[SummaryDefinition, ...]:
    """Collect declarations once and reject duplicate ids immediately."""
    definitions: list[SummaryDefinition] = []
    seen_builders: set[int] = set()
    by_id: dict[str, SummaryDefinition] = {}
    for module in modules:
        for value in vars(module).values():
            definition = get_summary_definition(value) if callable(value) else None
            if (
                definition is None
                or definition.builder.__module__ != module.__name__
                or id(definition.builder) in seen_builders
            ):
                continue
            seen_builders.add(id(definition.builder))
            previous = by_id.get(definition.summary_id)
            if previous is not None:
                raise ValueError(
                    f"Duplicate summary id {definition.summary_id!r}: "
                    f"{previous.builder.__module__}.{previous.builder.__name__} and "
                    f"{definition.builder.__module__}.{definition.builder.__name__}."
                )
            by_id[definition.summary_id] = definition
            definitions.append(definition)
    return tuple(definitions)


SUMMARY_DEFINITIONS = build_summary_catalog()
SUMMARY_BY_ID = {
    definition.summary_id: definition for definition in SUMMARY_DEFINITIONS
}
SUMMARY_FILENAME_BY_ID = {
    definition.summary_id: f"{definition.filename}.csv"
    for definition in SUMMARY_DEFINITIONS
}
DEFAULT_SUMMARY_IDS = [
    definition.summary_id
    for definition in SUMMARY_DEFINITIONS
    if definition.build_by_default
]

__all__ = [
    "DEFAULT_SUMMARY_IDS",
    "SUMMARY_BY_ID",
    "SUMMARY_DEFINITIONS",
    "SUMMARY_FILENAME_BY_ID",
    "SUMMARY_MODULES",
    "build_summary_catalog",
]
