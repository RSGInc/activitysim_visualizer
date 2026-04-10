"""Shared runtime data models used by both summarize and dashboard code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import polars as pl


@dataclass
class RunData:
    """Holds all data for one ActivitySim run, enriched by ``prepare_data()``."""

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
