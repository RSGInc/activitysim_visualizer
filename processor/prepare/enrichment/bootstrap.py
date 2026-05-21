"""Prepare pipeline state initialization helpers."""

from __future__ import annotations

from processor.models import RunData
from processor.prepare.availability import table_availability, table_unavailable_reasons
from processor.prepare.enrichment.types import _PrepareState


def _init_prepare_state(rd: RunData) -> _PrepareState:
    """Create mutable prepare state from the raw run container."""
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
        prepare_diagnostics=dict(rd.prepare_diagnostics),
    )
