"""Shared processor data models used across prepare, summarize, and dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Literal, Optional

import numpy as np
import polars as pl

PreparedTableName = Literal[
    "hh",
    "per",
    "tours",
    "trips",
    "joint_participants",
    "land_use",
    "skim",
]
PREPARED_TABLE_NAMES: tuple[PreparedTableName, ...] = (
    "hh",
    "per",
    "tours",
    "trips",
    "joint_participants",
    "land_use",
    "skim",
)


@dataclass
class RunData:
    """Holds all data for one ActivitySim run after processor preparation.

    Summary code should rely on prepared runtime columns rather than guessing raw
    ActivitySim schema. Today that contract includes canonical identifiers
    (for example ``household_id``, ``person_id``, ``tour_id``), prepared
    household aliases such as ``HHVEH``/``HHSIZE``, and prepared trip/tour
    fields such as:

    - tours: ``tour_purpose``, ``tour_mode``, ``tour_category``, ``start_hour``,
      ``end_hour``, ``tourdur``, ``num_ob_stops``, ``num_ib_stops``,
      ``num_tot_stops``, ``SKIMDIST``, ``AUTOSUFF``, ``NUMBER_HH``,
      ``finalweight``
    - trips: ``tour_purpose``, ``trip_purpose``, ``tour_mode``, ``trip_mode``,
      ``depart_hour``, ``stops``, ``out_dir_dist``, ``od_dist``,
      ``num_participants``, ``finalweight``
    - shared prepared geography/runtime fields when available: ``HGEO``, ``WGEO``

    New summary builders should treat this dataclass as their source-of-truth
    interface rather than reaching back to raw, unprepared ActivitySim files.
    """

    label: str
    run_dir: str
    skim_file: Optional[str]
    hh: pl.DataFrame
    per: pl.DataFrame
    tours: pl.DataFrame
    trips: pl.DataFrame
    joint_participants: pl.DataFrame
    land_use: pl.DataFrame
    skim_matrix: Optional[np.ndarray]
    skim_zone_map: Optional[dict[int, int]] = None
    hh_weight_col: Optional[str] = None
    person_weight_col: Optional[str] = None
    trip_weight_col: Optional[str] = None
    skimjoin_manifest: dict[str, Any] = field(default_factory=dict)
    skimjoin_reports: dict[str, pl.DataFrame] = field(default_factory=dict)


def prune_prepared_run(
    prepared_run: RunData,
    required_tables: Collection[PreparedTableName],
) -> RunData:
    """Return a copy of ``prepared_run`` that keeps only the requested tables."""
    keep = set(required_tables)
    return RunData(
        label=prepared_run.label,
        run_dir=prepared_run.run_dir,
        skim_file=prepared_run.skim_file if "skim" in keep else None,
        hh=prepared_run.hh if "hh" in keep else pl.DataFrame(),
        per=prepared_run.per if "per" in keep else pl.DataFrame(),
        tours=prepared_run.tours if "tours" in keep else pl.DataFrame(),
        trips=prepared_run.trips if "trips" in keep else pl.DataFrame(),
        joint_participants=(
            prepared_run.joint_participants
            if "joint_participants" in keep
            else pl.DataFrame()
        ),
        land_use=prepared_run.land_use if "land_use" in keep else pl.DataFrame(),
        skim_matrix=prepared_run.skim_matrix if "skim" in keep else None,
        skim_zone_map=prepared_run.skim_zone_map if "skim" in keep else None,
        hh_weight_col=prepared_run.hh_weight_col,
        person_weight_col=prepared_run.person_weight_col,
        trip_weight_col=prepared_run.trip_weight_col,
        skimjoin_manifest=dict(prepared_run.skimjoin_manifest),
        skimjoin_reports=dict(prepared_run.skimjoin_reports),
    )


def prune_prepared_runs(
    prepared_runs: list[tuple[str, RunData]],
    required_tables: Collection[PreparedTableName],
) -> list[tuple[str, RunData]]:
    """Return prepared runs with only the requested tables retained."""
    return [
        (label, prune_prepared_run(prepared_run, required_tables))
        for label, prepared_run in prepared_runs
    ]


@dataclass
class ProcessorWorkflowResult:
    """Prepared and summary workflow outputs for one processor invocation.

    This is the shared in-memory handoff between prepare, summarize, and
    dashboard/export workflows. ``prepared_runs`` is the authoritative
    prepared-table contract carried across those steps.
    """

    summary_runs: list[Any] = field(default_factory=list)
    prepared_runs: list[tuple[str, RunData]] = field(default_factory=list)
    prepared_runs_by_key: dict[str, tuple[str, RunData]] = field(default_factory=dict)
    run_keys: list[str] = field(default_factory=list)
    run_fingerprints_by_key: dict[str, dict[str, object]] = field(default_factory=dict)
