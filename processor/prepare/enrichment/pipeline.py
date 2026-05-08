"""Public orchestration entrypoint for prepare enrichment."""

from __future__ import annotations

from activitysim_viz_logging import get_logger

from processor.models import RunData
from processor.prepare.availability import table_availability, table_unavailable_reasons
from processor.prepare.enrichment.canonicalize import (
    _canonicalize_identifiers_and_core_columns,
)
from processor.prepare.enrichment.finalize import (
    _cast_prepared_tables,
    _finalize_prepared_run,
)
from processor.prepare.enrichment.households_persons import (
    _enrich_households_and_persons,
)
from processor.prepare.enrichment.student_enrollment import (
    _derive_student_enrollment,
)
from processor.prepare.enrichment.tours import _enrich_tours
from processor.prepare.enrichment.trips import _enrich_trips
from processor.prepare.enrichment.types import _PrepareState
from processor.prepare.enrichment.vot_bins import _normalize_vot_bins
from processor.prepare.enrichment.weights import _apply_weights
from processor.prepare.enrichment.zones import _build_zone_context
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _init_prepare_state(rd: RunData) -> _PrepareState:
    return _PrepareState(
        label=rd.label,
        run_dir=rd.run_dir,
        skim_file=rd.skim_file,
        hh=rd.hh,
        per=rd.per,
        tours=rd.tours,
        trips=rd.trips,
        joint_participants=rd.joint_participants,
        land_use=rd.land_use,
        skim=rd.skim_matrix,
        skim_map=rd.skim_zone_map,
        hh_weight_col=rd.hh_weight_col,
        person_weight_col=rd.person_weight_col,
        trip_weight_col=rd.trip_weight_col,
        table_states=table_availability(rd),
        table_reasons=table_unavailable_reasons(rd),
    )


def prepare_data(rd: RunData, config: Config) -> RunData:
    """Enrich ``RunData`` with derived columns needed by summaries and dashboard pages."""
    LOGGER.info("[prepare_data] Starting: %s", rd.label)

    state = _init_prepare_state(rd)
    state = _canonicalize_identifiers_and_core_columns(state, config)
    state = _apply_weights(state, config)
    zone_context = _build_zone_context(state, config)
    state = _enrich_households_and_persons(state, config, zone_context)
    state = _derive_student_enrollment(state, config)
    state = _enrich_tours(state, config, zone_context)
    state = _enrich_trips(state, config, zone_context)
    state = _normalize_vot_bins(state, config)
    state = _cast_prepared_tables(state)

    LOGGER.info("[prepare_data] Complete: %s", state.label)
    return _finalize_prepared_run(state)


__all__ = ["prepare_data"]
