"""Domain-oriented prepare operations over one explicit mutable run state."""

from __future__ import annotations

from runtime.config import Config

from processor.prepare.enrichment.canonicalize import (
    _canonicalize_identifiers_and_core_columns,
)
from processor.prepare.enrichment.day_vehicles import _prepare_day, _prepare_vehicles
from processor.prepare.enrichment.escort import _normalize_escort_fields
from processor.prepare.enrichment.finalize import _cast_prepared_tables
from processor.prepare.enrichment.households_persons import (
    _enrich_households_and_persons,
)
from processor.prepare.enrichment.non_motorized_distance import (
    _derive_non_motorized_distance,
)
from processor.prepare.enrichment.student_enrollment import (
    _derive_student_enrollment,
)
from processor.prepare.enrichment.time_periods import _derive_time_periods
from processor.prepare.enrichment.tours import _enrich_tours
from processor.prepare.enrichment.trips import _enrich_trips
from processor.prepare.enrichment.types import _PrepareState
from processor.prepare.enrichment.vot_bins import _normalize_vot_bins
from processor.prepare.enrichment.weights import _apply_weights
from processor.prepare.enrichment.zones import (
    _add_land_use_aggregated_geographies,
    _build_zone_context,
    _log_prepare_diagnostics,
)


def normalize_source_domain(state: _PrepareState, config: Config) -> _PrepareState:
    """Canonicalize source columns and establish weights and escort semantics."""
    state = _canonicalize_identifiers_and_core_columns(state, config)
    state = _normalize_escort_fields(state, config)
    return _apply_weights(state, config)


def enrich_people_and_places_domain(
    state: _PrepareState,
    config: Config,
) -> _PrepareState:
    """Enrich household/person tables and their shared geography context."""
    zones = _build_zone_context(state, config)
    state = _enrich_households_and_persons(state, config, zones)
    state = _derive_student_enrollment(state, config)
    state = _prepare_day(state)
    state.land_use = _add_land_use_aggregated_geographies(
        state.land_use,
        config=config,
        zone_context=zones,
    )
    state = _enrich_tours(state, config, zones)
    return _enrich_trips(state, config, zones)


def enrich_mobility_domain(state: _PrepareState, config: Config) -> _PrepareState:
    """Add vehicle, distance, time-period, and value-of-time outputs."""
    state = _prepare_vehicles(state)
    state = _derive_non_motorized_distance(state, config)
    state = _derive_time_periods(state, config)
    return _normalize_vot_bins(state, config)


def finalize_output_domain(state: _PrepareState) -> _PrepareState:
    """Validate diagnostics and cast the canonical prepared schemas."""
    _log_prepare_diagnostics(state)
    return _cast_prepared_tables(state)
