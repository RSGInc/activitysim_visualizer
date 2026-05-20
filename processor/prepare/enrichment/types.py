"""Internal state containers for the prepare enrichment pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass
class _PrepareState:
    label: str
    run_dir: str
    skim_file: str | None
    hh: pl.DataFrame
    per: pl.DataFrame
    tours: pl.DataFrame
    trips: pl.DataFrame
    joint_participants: pl.DataFrame
    land_use: pl.DataFrame
    skim: np.ndarray | None
    skim_map: dict[int, int] | None
    hh_weight_col: str | None
    person_weight_col: str | None
    trip_weight_col: str | None
    table_states: dict[str, str]
    table_reasons: dict[str, str]


@dataclass(frozen=True)
class _ZoneContext:
    maz_taz: pl.DataFrame | None
    zone_geo: pl.DataFrame | None
    aggregation_lookups: dict[str, pl.DataFrame]
