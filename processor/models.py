"""Shared processor data models used across prepare, summarize, and dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Literal, Optional

import numpy as np
import polars as pl

PreparedTableName = Literal[
    "hh",
    "per",
    "day",
    "tours",
    "trips",
    "vehicles",
    "joint_participants",
    "land_use",
    "skim",
]
PREPARED_TABLE_NAMES: tuple[PreparedTableName, ...] = (
    "hh",
    "per",
    "day",
    "tours",
    "trips",
    "vehicles",
    "joint_participants",
    "land_use",
    "skim",
)


@dataclass(frozen=True)
class TableAvailabilityMetadata:
    """Explicit per-run prepared-table availability metadata."""

    states: dict[str, str] = field(default_factory=dict)
    diagnostics: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SkimjoinArtifacts:
    """Typed container for skimjoin manifest/report sidecar data."""

    manifest: dict[str, Any] = field(default_factory=dict)
    reports: dict[str, pl.DataFrame] = field(default_factory=dict)


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
      ``num_tot_stops``, ``tour_distance``, ``SKIMDIST``, ``AUTOSUFF``, ``NUMBER_HH``,
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
    day_weight_col: Optional[str] = "day_weight"
    day: pl.DataFrame = field(default_factory=pl.DataFrame)
    vehicles: pl.DataFrame = field(default_factory=pl.DataFrame)
    trip_hypothetical_skims: pl.DataFrame = field(default_factory=pl.DataFrame)
    tour_hypothetical_skims: pl.DataFrame = field(default_factory=pl.DataFrame)
    table_availability_metadata: TableAvailabilityMetadata = field(
        default_factory=TableAvailabilityMetadata
    )
    prepare_diagnostics: dict[str, Any] = field(default_factory=dict)
    skimjoin_artifacts: SkimjoinArtifacts = field(default_factory=SkimjoinArtifacts)
    skimjoin_manifest: dict[str, Any] = field(default_factory=dict)
    skimjoin_reports: dict[str, pl.DataFrame] = field(default_factory=dict)

    def __post_init__(self) -> None:
        metadata = self.table_availability_metadata
        self.table_availability_metadata = TableAvailabilityMetadata(
            states=dict(metadata.states),
            diagnostics=dict(metadata.diagnostics),
        )
        self.prepare_diagnostics = dict(self.prepare_diagnostics)

        if self.skimjoin_manifest or self.skimjoin_reports:
            self.skimjoin_manifest = dict(self.skimjoin_manifest)
            self.skimjoin_reports = dict(self.skimjoin_reports)
            self.skimjoin_artifacts = SkimjoinArtifacts(
                manifest=dict(self.skimjoin_manifest),
                reports=dict(self.skimjoin_reports),
            )
        else:
            self.skimjoin_artifacts = SkimjoinArtifacts(
                manifest=dict(self.skimjoin_artifacts.manifest),
                reports=dict(self.skimjoin_artifacts.reports),
            )
            self.skimjoin_manifest = dict(self.skimjoin_artifacts.manifest)
            self.skimjoin_reports = dict(self.skimjoin_artifacts.reports)


def map_run_data_tables(
    run: RunData,
    transform: Callable[[str, pl.DataFrame], pl.DataFrame],
    *,
    clear_weight_columns: bool = False,
) -> RunData:
    """Copy a run while applying one transform to every DataFrame table."""

    def mapped(table_name: str, frame: pl.DataFrame) -> pl.DataFrame:
        result = transform(table_name, frame)
        if not isinstance(result, pl.DataFrame):
            raise TypeError(
                f"RunData table transform for {table_name!r} returned "
                f"{type(result).__name__}; expected polars.DataFrame."
            )
        return result

    return RunData(
        label=run.label,
        run_dir=run.run_dir,
        skim_file=run.skim_file,
        hh=mapped("hh", run.hh),
        per=mapped("per", run.per),
        day=mapped("day", run.day),
        tours=mapped("tours", run.tours),
        trips=mapped("trips", run.trips),
        vehicles=mapped("vehicles", run.vehicles),
        trip_hypothetical_skims=mapped(
            "trip_hypothetical_skims", run.trip_hypothetical_skims
        ),
        tour_hypothetical_skims=mapped(
            "tour_hypothetical_skims", run.tour_hypothetical_skims
        ),
        joint_participants=mapped("joint_participants", run.joint_participants),
        land_use=mapped("land_use", run.land_use),
        skim_matrix=run.skim_matrix,
        skim_zone_map=run.skim_zone_map,
        hh_weight_col=None if clear_weight_columns else run.hh_weight_col,
        person_weight_col=None if clear_weight_columns else run.person_weight_col,
        trip_weight_col=None if clear_weight_columns else run.trip_weight_col,
        day_weight_col=None if clear_weight_columns else run.day_weight_col,
        table_availability_metadata=TableAvailabilityMetadata(
            states=dict(run.table_availability_metadata.states),
            diagnostics=dict(run.table_availability_metadata.diagnostics),
        ),
        prepare_diagnostics=dict(run.prepare_diagnostics),
        skimjoin_artifacts=SkimjoinArtifacts(
            manifest=dict(run.skimjoin_artifacts.manifest),
            reports=dict(run.skimjoin_artifacts.reports),
        ),
        skimjoin_manifest=dict(run.skimjoin_manifest),
        skimjoin_reports=dict(run.skimjoin_reports),
    )


def prune_prepared_run(
    prepared_run: RunData,
    required_tables: Collection[PreparedTableName],
) -> RunData:
    """Return a copy of ``prepared_run`` that keeps only the requested tables."""
    keep = set(required_tables)
    trip_sidecar = prepared_run.trip_hypothetical_skims
    if "trips" not in keep:
        trip_sidecar = pl.DataFrame()
    tour_sidecar = prepared_run.tour_hypothetical_skims
    if "tours" not in keep:
        tour_sidecar = pl.DataFrame()
    return RunData(
        label=prepared_run.label,
        run_dir=prepared_run.run_dir,
        skim_file=prepared_run.skim_file if "skim" in keep else None,
        hh=prepared_run.hh if "hh" in keep else pl.DataFrame(),
        per=prepared_run.per if "per" in keep else pl.DataFrame(),
        day=prepared_run.day if "day" in keep else pl.DataFrame(),
        tours=prepared_run.tours if "tours" in keep else pl.DataFrame(),
        trips=prepared_run.trips if "trips" in keep else pl.DataFrame(),
        vehicles=prepared_run.vehicles if "vehicles" in keep else pl.DataFrame(),
        trip_hypothetical_skims=trip_sidecar,
        tour_hypothetical_skims=tour_sidecar,
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
        day_weight_col=prepared_run.day_weight_col,
        table_availability_metadata=TableAvailabilityMetadata(
            states=dict(prepared_run.table_availability_metadata.states),
            diagnostics=dict(prepared_run.table_availability_metadata.diagnostics),
        ),
        prepare_diagnostics=dict(prepared_run.prepare_diagnostics),
        skimjoin_artifacts=SkimjoinArtifacts(
            manifest=dict(prepared_run.skimjoin_artifacts.manifest),
            reports=dict(prepared_run.skimjoin_artifacts.reports),
        ),
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
