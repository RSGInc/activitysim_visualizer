"""Read raw ActivitySim outputs before processor enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from runtime.logging import get_logger
import numpy as np
import polars as pl

from processor.models import RunData
from processor.prepare.availability import attach_table_availability
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _resolve_skim(
    run_skim: Optional[str], global_skim: Optional[str], run_dir: Path
) -> Optional[str]:
    """Pick the skim file for a run: per-run > global > None."""
    candidate = run_skim or global_skim
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = run_dir / path
    return str(path)


def resolve_skim_path(
    run_skim: Optional[str],
    global_skim: Optional[str],
    run_dir: str | Path,
) -> Optional[str]:
    """Public wrapper used by the cache layer to fingerprint run inputs."""
    return _resolve_skim(run_skim, global_skim, Path(run_dir))


def resolve_run_file_map(
    config: Config,
    run_file_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the effective raw input file mapping for one run."""
    effective = dict(config.files)
    if run_file_map:
        effective.update(run_file_map)
    return effective


def resolve_run_file_paths(
    run_dir: str | Path,
    config: Config,
    run_file_map: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """Resolve the concrete raw input files the reader would use."""
    root = Path(run_dir).expanduser()
    resolved: dict[str, str | None] = {}
    for table_id, configured in resolve_run_file_map(config, run_file_map).items():
        configured_path = Path(configured)
        suffix = configured_path.suffix.lower()
        candidates = (
            [root / configured_path]
            if suffix in {".csv", ".parquet"}
            else [
                root / f"{configured_path.name}.parquet",
                root / f"{configured_path.name}.csv",
            ]
        )
        selected = next((candidate for candidate in candidates if candidate.is_file()), None)
        if selected is None:
            fallback = config.fallback_files.get(table_id)
            fallback_path = Path(fallback).expanduser() if fallback else None
            selected = fallback_path if fallback_path is not None and fallback_path.is_file() else None
        resolved[table_id] = str(selected.resolve()) if selected is not None else None
    return resolved


def _find_and_read(run_dir: Path, configured: str) -> pl.DataFrame:
    """Read a table from run_dir, resolving file format."""
    path = Path(configured)
    run_dir = run_dir.expanduser()
    suffix = path.suffix.lower()
    stem = path.stem if suffix in (".csv", ".parquet") else path.name

    if suffix == ".parquet":
        LOGGER.info("[read_run] Reading parquet: %s", run_dir / path)
        return pl.read_parquet(run_dir / path)
    if suffix == ".csv":
        LOGGER.info("[read_run] Reading csv: %s", run_dir / path)
        return pl.read_csv(run_dir / path, infer_schema_length=None)

    parquet_path = run_dir / f"{stem}.parquet"
    csv_path = run_dir / f"{stem}.csv"
    if parquet_path.exists():
        return pl.read_parquet(parquet_path)
    if csv_path.exists():
        return pl.read_csv(csv_path, infer_schema_length=None)
    raise FileNotFoundError(
        f"Cannot find '{stem}.parquet' or '{stem}.csv' in {run_dir}"
    )


def _read_fallback_file(configured: str) -> pl.DataFrame:
    """Read one resolved fallback file path with explicit extension."""
    path = Path(configured).expanduser()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        LOGGER.info("[read_run] Reading fallback parquet: %s", path)
        return pl.read_parquet(path)
    if suffix == ".csv":
        LOGGER.info("[read_run] Reading fallback csv: %s", path)
        return pl.read_csv(path, infer_schema_length=None)
    raise FileNotFoundError(f"Fallback file must end with '.parquet' or '.csv': {path}")


def read_run(
    run_dir: str | Path,
    config: Config,
    label: Optional[str] = None,
    file_map: dict[str, str] | None = None,
    skim_file: Optional[str] = None,
    hh_weight_col: Optional[str] = None,
    person_weight_col: Optional[str] = None,
    trip_weight_col: Optional[str] = None,
) -> RunData:
    """Read ActivitySim outputs and optionally the OMX skim for one run."""
    run_dir = Path(run_dir)
    if label is None:
        label = run_dir.name
    effective_file_map = resolve_run_file_map(config, file_map)

    table_states: dict[str, str] = {}
    table_reasons: dict[str, str] = {}

    def _read(key: str) -> pl.DataFrame:
        configured = effective_file_map[key]
        try:
            table = _find_and_read(run_dir, configured)
        except FileNotFoundError as exc:
            fallback_configured = config.fallback_files.get(key)
            if fallback_configured:
                try:
                    table = _read_fallback_file(fallback_configured)
                    table_states[key] = "empty" if table.width == 0 else "available"
                    LOGGER.info(
                        "[read_run] Using fallback file for run '%s', table '%s': %s",
                        label,
                        key,
                        fallback_configured,
                    )
                    return table
                except FileNotFoundError as fallback_exc:
                    combined_reason = f"{exc}; fallback failed: {fallback_exc}"
                else:
                    combined_reason = str(exc)
            else:
                combined_reason = str(exc)

            table_states[key] = "unavailable"
            table_reasons[key] = combined_reason
            LOGGER.warning(
                "Prepare input unavailable for run '%s', table '%s': %s",
                label,
                key,
                combined_reason,
            )
            return pl.DataFrame()

        table_states[key] = "empty" if table.width == 0 else "available"
        return table

    hh = _read("households")
    per = _read("persons")
    day = _read("day")
    tours = _read("tours")
    trips = _read("trips")
    vehicles = _read("vehicles")
    joint_parts = _read("joint_tour_participants")
    land_use = _read("land_use")

    resolved_skim = _resolve_skim(skim_file, config.skim_file, run_dir)
    skim_matrix: Optional[np.ndarray] = None
    skim_zone_map: Optional[dict[int, int]] = None
    if resolved_skim:
        try:
            import openmatrix as omx

            file = omx.open_file(resolved_skim)
            skim_matrix = np.array(file[config.skim_matrix])
            mappings = file.list_mappings()
            if mappings:
                mapping_name = mappings[0]
                raw_map = file.mapping(mapping_name)
                norm_map: dict[int, int] = {}
                for key, value in raw_map.items():
                    normalized_key = (
                        key.decode("utf-8")
                        if isinstance(key, (bytes, bytearray))
                        else key
                    )
                    try:
                        norm_map[int(normalized_key)] = int(value)
                    except Exception:
                        continue
                skim_zone_map = norm_map if norm_map else None
                LOGGER.info(
                    "[read_run] Loaded skim mapping '%s' with %s zones.",
                    mapping_name,
                    len(norm_map),
                )
            file.close()
            LOGGER.info(
                "[read_run] Loaded skim matrix '%s' from %s",
                config.skim_matrix,
                resolved_skim,
            )
        except Exception as exc:
            LOGGER.warning("Warning: could not read skim '%s': %s", resolved_skim, exc)
    else:
        LOGGER.info("[read_run] No skim configured for run '%s'.", label)

    return attach_table_availability(
        RunData(
            label=label,
            run_dir=str(run_dir),
            skim_file=resolved_skim,
            hh=hh,
            per=per,
            day=day,
            tours=tours,
            trips=trips,
            vehicles=vehicles,
            joint_participants=joint_parts,
            land_use=land_use,
            skim_matrix=skim_matrix,
            skim_zone_map=skim_zone_map,
            hh_weight_col=hh_weight_col or None,
            person_weight_col=person_weight_col or None,
            trip_weight_col=trip_weight_col or None,
        ),
        table_states=table_states,
        table_reasons=table_reasons,
    )


__all__ = [
    "RunData",
    "read_run",
    "resolve_run_file_map",
    "resolve_run_file_paths",
    "resolve_skim_path",
]
