"""Named stage groups for prepare enrichment orchestration."""

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
from processor.prepare.enrichment.student_enrollment import (
    _derive_student_enrollment,
)
from processor.prepare.enrichment.tours import _enrich_tours
from processor.prepare.enrichment.trips import _enrich_trips
from processor.prepare.enrichment.types import _PrepareState
from processor.prepare.enrichment.time_periods import _derive_time_periods
from processor.prepare.enrichment.vot_bins import _normalize_vot_bins
from processor.prepare.enrichment.weights import _apply_weights
from processor.prepare.enrichment.zones import (
    _add_land_use_aggregated_geographies,
    _build_zone_context,
    _log_prepare_diagnostics,
)


def _run_prepare_core_stages(state: _PrepareState, config: Config) -> _PrepareState:
    """Run identifier cleanup and shared weighting steps."""
    state = _canonicalize_identifiers_and_core_columns(state, config)
    state = _normalize_escort_fields(state, config)
    return _apply_weights(state, config)


def _run_prepare_person_and_tour_stages(
    state: _PrepareState, config: Config
) -> _PrepareState:
    """Run household, person, and tour enrichment stages sharing zone context."""
    zone_context = _build_zone_context(state, config)
    state = _enrich_households_and_persons(state, config, zone_context)
    state = _derive_student_enrollment(state, config)
    state = _prepare_day(state)
    state.land_use = _add_land_use_aggregated_geographies(
        state.land_use,
        config=config,
        zone_context=zone_context,
    )
    state = _enrich_tours(state, config, zone_context)
    state = _enrich_trips(state, config, zone_context)
    state = _prepare_vehicles(state)
    return state


def _run_prepare_output_stages(state: _PrepareState, config: Config) -> _PrepareState:
    """Normalize output-only columns and cast final prepared table schemas."""
    state = _derive_time_periods(state, config)
    state = _normalize_vot_bins(state, config)
    _log_prepare_diagnostics(state)
    return _cast_prepared_tables(state)
