"""Shared runtime data models used by both summarize and dashboard code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import polars as pl


@dataclass
class RunData:
    """Holds all data for one ActivitySim run, enriched by ``prepare_data()``.

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
