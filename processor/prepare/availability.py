"""Prepared-table availability metadata helpers."""

from __future__ import annotations

from processor.models import RunData, TableAvailabilityMetadata

TABLE_STATE_AVAILABLE = "available"
TABLE_STATE_EMPTY = "empty"
TABLE_STATE_UNAVAILABLE = "unavailable"
TABLE_STATE_FAILED = "failed"
TABLE_STATES: tuple[str, ...] = (
    TABLE_STATE_AVAILABLE,
    TABLE_STATE_EMPTY,
    TABLE_STATE_UNAVAILABLE,
    TABLE_STATE_FAILED,
)

PREPARED_TABLE_IDS: tuple[str, ...] = (
    "households",
    "persons",
    "day",
    "tours",
    "trips",
    "vehicles",
    "joint_tour_participants",
    "land_use",
)
CORE_PREPARED_TABLE_IDS: tuple[str, ...] = (
    "households",
    "persons",
    "tours",
    "trips",
)
RUN_TABLE_ATTRS: tuple[tuple[str, str], ...] = (
    ("households", "hh"),
    ("persons", "per"),
    ("day", "day"),
    ("tours", "tours"),
    ("trips", "trips"),
    ("vehicles", "vehicles"),
    ("joint_tour_participants", "joint_participants"),
    ("land_use", "land_use"),
)

_TABLE_AVAILABILITY_ATTR = "_table_availability"
_TABLE_DIAGNOSTICS_ATTR = "_table_diagnostics"


def _coerce_mapping(values: dict[str, object] | None) -> dict[str, str]:
    return {str(key): str(value) for key, value in dict(values or {}).items()}


def _infer_table_states(rd: RunData) -> dict[str, str]:
    inferred: dict[str, str] = {}
    for table_id, attr_name in RUN_TABLE_ATTRS:
        table = getattr(rd, attr_name)
        inferred[table_id] = (
            TABLE_STATE_EMPTY if table.width == 0 else TABLE_STATE_AVAILABLE
        )
    return inferred


def _attached_metadata(rd: RunData) -> TableAvailabilityMetadata | None:
    explicit = getattr(rd, "table_availability_metadata", None)
    if isinstance(explicit, TableAvailabilityMetadata) and (
        explicit.states or explicit.diagnostics
    ):
        return TableAvailabilityMetadata(
            states=_coerce_mapping(explicit.states),
            diagnostics=_coerce_mapping(explicit.diagnostics),
        )

    states = getattr(rd, _TABLE_AVAILABILITY_ATTR, None)
    diagnostics = getattr(rd, _TABLE_DIAGNOSTICS_ATTR, None)
    if not isinstance(states, dict) and not isinstance(diagnostics, dict):
        return None
    return TableAvailabilityMetadata(
        states=_coerce_mapping(states if isinstance(states, dict) else None),
        diagnostics=_coerce_mapping(
            diagnostics if isinstance(diagnostics, dict) else None
        ),
    )


def _metadata_for_run(rd: RunData) -> TableAvailabilityMetadata:
    metadata = _attached_metadata(rd)
    if metadata is not None:
        return metadata
    return TableAvailabilityMetadata(states=_infer_table_states(rd), diagnostics={})


def _diagnostics_for_state(rd: RunData, state: str) -> dict[str, str]:
    metadata = _metadata_for_run(rd)
    return {
        table_id: reason
        for table_id, reason in metadata.diagnostics.items()
        if metadata.states.get(table_id) == state
    }


def attach_table_availability(
    rd: RunData,
    table_states: dict[str, str] | None = None,
    table_reasons: dict[str, str] | None = None,
) -> RunData:
    """Attach internal per-table availability metadata to a RunData instance."""
    metadata = TableAvailabilityMetadata(
        states=_coerce_mapping(table_states),
        diagnostics=_coerce_mapping(table_reasons),
    )
    rd.table_availability_metadata = metadata
    setattr(rd, _TABLE_AVAILABILITY_ATTR, metadata.states)
    setattr(rd, _TABLE_DIAGNOSTICS_ATTR, metadata.diagnostics)
    return rd


def table_availability(rd: RunData) -> dict[str, str]:
    """Return internal per-table availability metadata for ``rd``."""
    return dict(_metadata_for_run(rd).states)


def table_unavailable_reasons(rd: RunData) -> dict[str, str]:
    """Return internal per-table unavailable-reason metadata for ``rd``."""
    return _diagnostics_for_state(rd, TABLE_STATE_UNAVAILABLE)


def table_failure_reasons(rd: RunData) -> dict[str, str]:
    """Return internal per-table failure diagnostics for ``rd``."""
    return _diagnostics_for_state(rd, TABLE_STATE_FAILED)


def table_diagnostics(rd: RunData) -> dict[str, str]:
    """Return internal per-table diagnostics for unavailable or failed tables."""
    return dict(_metadata_for_run(rd).diagnostics)


def has_usable_loaded_tables(rd: RunData) -> bool:
    """Return whether any raw prepared input table was loaded for this run."""
    states = table_availability(rd)
    return any(
        states.get(table_id) not in {TABLE_STATE_UNAVAILABLE, TABLE_STATE_FAILED}
        for table_id in CORE_PREPARED_TABLE_IDS
    )


def unavailable_tables(rd: RunData) -> dict[str, str]:
    """Return unavailable-table reasons for logging/diagnostics."""
    states = table_availability(rd)
    reasons = table_unavailable_reasons(rd)
    return {
        table_id: reasons.get(table_id, "table unavailable")
        for table_id, state in states.items()
        if state == TABLE_STATE_UNAVAILABLE
    }


def failed_tables(rd: RunData) -> dict[str, str]:
    """Return failed-table reasons for logging/diagnostics."""
    states = table_availability(rd)
    reasons = table_failure_reasons(rd)
    return {
        table_id: reasons.get(table_id, "table failed")
        for table_id, state in states.items()
        if state == TABLE_STATE_FAILED
    }


__all__ = [
    "CORE_PREPARED_TABLE_IDS",
    "PREPARED_TABLE_IDS",
    "RUN_TABLE_ATTRS",
    "TABLE_STATE_AVAILABLE",
    "TABLE_STATE_EMPTY",
    "TABLE_STATE_FAILED",
    "TABLE_STATE_UNAVAILABLE",
    "TABLE_STATES",
    "TableAvailabilityMetadata",
    "attach_table_availability",
    "failed_tables",
    "has_usable_loaded_tables",
    "table_availability",
    "table_diagnostics",
    "table_failure_reasons",
    "table_unavailable_reasons",
    "unavailable_tables",
]
