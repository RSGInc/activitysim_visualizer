"""Prepared-table availability metadata helpers."""

from __future__ import annotations

import polars as pl

from processor.models import RunData

PREPARED_TABLE_IDS: tuple[str, ...] = (
    "households",
    "persons",
    "tours",
    "trips",
    "joint_tour_participants",
    "land_use",
)
RUN_TABLE_ATTRS: tuple[tuple[str, str], ...] = (
    ("households", "hh"),
    ("persons", "per"),
    ("tours", "tours"),
    ("trips", "trips"),
    ("joint_tour_participants", "joint_participants"),
    ("land_use", "land_use"),
)


def attach_table_availability(
    rd: RunData,
    table_states: dict[str, str] | None = None,
    table_reasons: dict[str, str] | None = None,
) -> RunData:
    """Attach internal per-table availability metadata to a RunData instance."""
    setattr(rd, "_table_availability", dict(table_states or {}))
    setattr(rd, "_table_unavailable_reasons", dict(table_reasons or {}))
    return rd


def table_availability(rd: RunData) -> dict[str, str]:
    """Return internal per-table availability metadata for ``rd``."""
    states = getattr(rd, "_table_availability", None)
    if isinstance(states, dict):
        return dict(states)

    inferred: dict[str, str] = {}
    for table_id, attr_name in RUN_TABLE_ATTRS:
        table = getattr(rd, attr_name)
        inferred[table_id] = "empty" if table.width == 0 else "available"
    return inferred


def table_unavailable_reasons(rd: RunData) -> dict[str, str]:
    """Return internal per-table unavailable-reason metadata for ``rd``."""
    reasons = getattr(rd, "_table_unavailable_reasons", None)
    return dict(reasons) if isinstance(reasons, dict) else {}


def has_usable_loaded_tables(rd: RunData) -> bool:
    """Return whether any raw prepared input table was loaded for this run."""
    states = table_availability(rd)
    return any(states.get(table_id) != "unavailable" for table_id in PREPARED_TABLE_IDS)


def unavailable_tables(rd: RunData) -> dict[str, str]:
    """Return unavailable-table reasons for logging/diagnostics."""
    states = table_availability(rd)
    reasons = table_unavailable_reasons(rd)
    return {
        table_id: reasons.get(table_id, "table unavailable")
        for table_id, state in states.items()
        if state == "unavailable"
    }

