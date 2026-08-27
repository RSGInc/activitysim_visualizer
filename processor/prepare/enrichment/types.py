"""Internal state containers for the prepare enrichment pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from processor.models import RunData
from processor.prepare.availability import (
    attach_table_availability,
    table_availability,
    table_unavailable_reasons,
)


@dataclass
class _PrepareState:
    label: str
    run_dir: str
    skim_file: str | None
    hh: pl.DataFrame
    per: pl.DataFrame
    day: pl.DataFrame
    tours: pl.DataFrame
    trips: pl.DataFrame
    vehicles: pl.DataFrame
    joint_participants: pl.DataFrame
    land_use: pl.DataFrame
    skim: np.ndarray | None
    skim_map: dict[int, int] | None
    hh_weight_col: str | None
    person_weight_col: str | None
    trip_weight_col: str | None
    day_weight_col: str | None
    table_states: dict[str, str]
    table_reasons: dict[str, str]
    prepare_diagnostics: dict[str, object]

    @classmethod
    def from_run(cls, run: RunData) -> "_PrepareState":
        """Open the pipeline's single mutable boundary around a raw run."""
        return cls(
            label=run.label,
            run_dir=run.run_dir,
            skim_file=run.skim_file,
            hh=run.hh,
            per=run.per,
            day=run.day,
            tours=run.tours,
            trips=run.trips,
            vehicles=run.vehicles,
            joint_participants=run.joint_participants,
            land_use=run.land_use,
            skim=run.skim_matrix,
            skim_map=run.skim_zone_map,
            hh_weight_col=run.hh_weight_col,
            person_weight_col=run.person_weight_col,
            trip_weight_col=run.trip_weight_col,
            day_weight_col=run.day_weight_col,
            table_states=table_availability(run),
            table_reasons=table_unavailable_reasons(run),
            prepare_diagnostics=dict(run.prepare_diagnostics),
        )

    def to_run(self) -> RunData:
        """Close the mutation boundary and return the prepared artifact."""
        return attach_table_availability(
            RunData(
                label=self.label,
                run_dir=self.run_dir,
                skim_file=self.skim_file,
                hh=self.hh,
                per=self.per,
                day=self.day,
                tours=self.tours,
                trips=self.trips,
                vehicles=self.vehicles,
                joint_participants=self.joint_participants,
                land_use=self.land_use,
                skim_matrix=self.skim,
                skim_zone_map=self.skim_map,
                hh_weight_col=self.hh_weight_col,
                person_weight_col=self.person_weight_col,
                trip_weight_col=self.trip_weight_col,
                day_weight_col=self.day_weight_col,
                prepare_diagnostics=dict(self.prepare_diagnostics),
            ),
            table_states=self.table_states,
            table_reasons=self.table_reasons,
        )


@dataclass(frozen=True)
class _ZoneContext:
    maz_taz: pl.DataFrame | None
    zone_geo: pl.DataFrame | None
    aggregation_lookups: dict[str, pl.DataFrame]
