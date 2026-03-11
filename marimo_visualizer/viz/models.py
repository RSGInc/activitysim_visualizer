"""Shared dataclasses for the marimo ActivitySim visualizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

DEFAULT_RUN_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
]

DEFAULT_FILE_STEMS = {
    "households": "final_households",
    "persons": "final_persons",
    "tours": "final_tours",
    "trips": "final_trips",
    "joint_tour_participants": "final_joint_tour_participants",
    "land_use": "final_land_use",
}


@dataclass(slots=True)
class RunSpec:
    """Configuration for a single ActivitySim run."""

    dir: str
    label: str
    skim_file: str | None = None
    hh_weight_col: str | None = None
    person_weight_col: str | None = None
    trip_weight_col: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "RunSpec":
        run_dir = str(data.get("dir", ""))
        label = str(data.get("label") or Path(run_dir).name)
        return cls(
            dir=run_dir,
            label=label,
            skim_file=data.get("skim_file") or None,
            hh_weight_col=data.get("hh_weight_col") or None,
            person_weight_col=data.get("person_weight_col") or None,
            trip_weight_col=data.get("trip_weight_col") or None,
        )


@dataclass(slots=True)
class Config:
    """All configuration for the visualizer, loaded from config.yaml."""

    name: str
    dashboard_title: str
    run_colors: list[str]
    files: dict[str, str]
    col_ptype: str
    col_hhsize: str
    col_auto_ownership: str
    col_num_workers: str
    col_num_adults: str
    col_sample_rate: str | None
    person_type_labels: dict[str, str] | None
    use_maz: bool
    maz_col: str
    taz_col: str
    geography_enabled: bool
    geography_landuse_col: str | None
    geography_mapping: dict[str, str] | None
    skim_file: str | None
    skim_matrix: str
    mode_order: list[str] | None
    mode_groups: dict[str, list[str]] | None
    runs: list[RunSpec] = field(default_factory=list)

    def run_color(self, idx: int) -> str:
        return self.run_colors[idx % len(self.run_colors)]

    def ordered_modes(self, modes_in_data: list[str]) -> list[str]:
        """Return modes in display order with unknown modes appended."""
        if not self.mode_order:
            return modes_in_data
        ordered = [mode for mode in self.mode_order if mode in modes_in_data]
        remaining = [mode for mode in modes_in_data if mode not in ordered]
        return ordered + remaining

    def apply_geo_mapping(self, expr: pl.Expr) -> pl.Expr:
        """Apply display labels to a geography column expression."""
        if not self.geography_mapping:
            return expr.cast(pl.Utf8)
        mapping = self.geography_mapping
        return expr.cast(pl.Utf8).map_elements(
            lambda value: mapping.get(str(value), str(value)) if value is not None else None,
            return_dtype=pl.Utf8,
        )

    def ptype_label(self, value: object) -> str:
        as_str = str(value)
        if self.person_type_labels and as_str in self.person_type_labels:
            return self.person_type_labels[as_str]
        return as_str


@dataclass(slots=True)
class RunData:
    """All loaded tables for one ActivitySim run."""

    label: str
    run_dir: str
    skim_file: str | None
    hh: pl.DataFrame
    per: pl.DataFrame
    tours: pl.DataFrame
    trips: pl.DataFrame
    joint_participants: pl.DataFrame
    land_use: pl.DataFrame
    skim_matrix: np.ndarray | None
    skim_zone_map: dict[int, int] | None = None
    hh_weight_col: str | None = None
    person_weight_col: str | None = None
    trip_weight_col: str | None = None


@dataclass(slots=True)
class PreparedRuns:
    """Bundle of weighted and unweighted run variants plus the active config."""

    config: Config
    weighted_runs: list[tuple[str, RunData]]
    unweighted_runs: list[tuple[str, RunData]]

    @property
    def run_labels(self) -> list[str]:
        return [label for label, _ in self.weighted_runs]
