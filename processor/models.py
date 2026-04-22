"""Shared processor data models used across prepare, summarize, and dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import polars as pl


@dataclass
class RunData:
    """Holds all data for one ActivitySim run after processor preparation.

    Summary code should rely on prepared runtime columns rather than guessing raw
    ActivitySim schema. Today that contract includes canonical identifiers
    (for example ``household_id``, ``person_id``, ``tour_id``), prepared
    household aliases such as ``HHVEH``/``HHSIZE``, and prepared trip/tour
    fields such as ``tour_purpose``, ``trip_purpose``, ``tour_mode``,
    ``trip_mode``, ``tour_category``, ``depart_hour``, ``stops``,
    ``out_dir_dist``, ``SKIMDIST``, ``HGEO``, and ``WGEO`` when available.

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


@dataclass
class ProcessorWorkflowResult:
    """Prepared and summary workflow outputs for one processor invocation.

    This is the shared in-memory handoff between prepare/summarize today and
    dashboard later in the refactor. ``prepared_runs`` is the authoritative
    prepared-table contract. ``raw_runs``/``raw_runs_by_key`` remain temporary
    compatibility aliases for dashboard code that still uses the older name.
    """

    summary_runs: list[Any] = field(default_factory=list)
    prepared_runs: list[tuple[str, RunData]] = field(default_factory=list)
    prepared_runs_by_key: dict[str, tuple[str, RunData]] = field(default_factory=dict)
    run_keys: list[str] = field(default_factory=list)
    run_fingerprints_by_key: dict[str, dict[str, object]] = field(default_factory=dict)

    @property
    def raw_runs(self) -> list[tuple[str, RunData]]:
        """Temporary compatibility alias for dashboard code still using raw naming."""
        return self.prepared_runs

    @property
    def raw_runs_by_key(self) -> dict[str, tuple[str, RunData]]:
        """Temporary compatibility alias for dashboard code still using raw naming."""
        return self.prepared_runs_by_key
