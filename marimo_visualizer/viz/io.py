"""Raw file loading and skim resolution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import polars as pl

from .models import Config, RunData, RunSpec


def resolve_skim_path(run_skim: str | None, global_skim: str | None, run_dir: Path) -> str | None:
    """Pick the skim file path for a run: per-run override, then global, then none."""
    candidate = run_skim or global_skim
    if not candidate:
        return None
    path = Path(candidate)
    if not path.is_absolute():
        path = run_dir / path
    return str(path)


def read_dataframe(run_dir: Path, configured: str) -> pl.DataFrame:
    """Read a configured ActivitySim output table as CSV or Parquet."""
    configured_path = Path(configured)
    suffix = configured_path.suffix.lower()
    stem = configured_path.stem if suffix in (".csv", ".parquet") else configured_path.name

    if suffix == ".parquet":
        return pl.read_parquet(run_dir / configured_path)
    if suffix == ".csv":
        return pl.read_csv(run_dir / configured_path, infer_schema_length=10000)

    parquet_path = run_dir / f"{stem}.parquet"
    csv_path = run_dir / f"{stem}.csv"
    if parquet_path.exists():
        return pl.read_parquet(parquet_path)
    if csv_path.exists():
        return pl.read_csv(csv_path, infer_schema_length=10000)
    raise FileNotFoundError(f"Cannot find '{stem}.parquet' or '{stem}.csv' in {run_dir}")


def load_skim_matrix(path: str | None, matrix_name: str) -> tuple[np.ndarray | None, dict[int, int] | None]:
    """Load an OMX skim matrix and optional zone mapping."""
    if not path:
        return None, None

    try:
        import openmatrix as omx
    except ImportError as exc:
        raise RuntimeError("openmatrix is required to load skim files.") from exc

    with omx.open_file(path) as skim_file:
        skim_matrix = np.array(skim_file[matrix_name])
        mappings = skim_file.list_mappings()
        if not mappings:
            return skim_matrix, None

        raw_map = skim_file.mapping(mappings[0])
        normalized: dict[int, int] = {}
        for key, value in raw_map.items():
            decoded = key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else key
            try:
                normalized[int(decoded)] = int(value)
            except Exception:
                continue
        return skim_matrix, normalized or None


def read_run(run_spec: RunSpec, config: Config) -> RunData:
    """Read one ActivitySim run from disk into RunData."""
    run_dir = Path(run_spec.dir)

    def _read(name: str) -> pl.DataFrame:
        return read_dataframe(run_dir, config.files[name])

    resolved_skim = resolve_skim_path(run_spec.skim_file, config.skim_file, run_dir)
    skim_matrix, skim_zone_map = load_skim_matrix(resolved_skim, config.skim_matrix)

    return RunData(
        label=run_spec.label,
        run_dir=str(run_dir),
        skim_file=resolved_skim,
        hh=_read("households"),
        per=_read("persons"),
        tours=_read("tours"),
        trips=_read("trips"),
        joint_participants=_read("joint_tour_participants"),
        land_use=_read("land_use"),
        skim_matrix=skim_matrix,
        skim_zone_map=skim_zone_map,
        hh_weight_col=run_spec.hh_weight_col,
        person_weight_col=run_spec.person_weight_col,
        trip_weight_col=run_spec.trip_weight_col,
    )


def load_runs(config: Config, run_specs: Sequence[RunSpec] | None = None) -> list[tuple[str, RunData]]:
    """Load all configured runs into memory."""
    specs = list(run_specs or config.runs)
    if not specs:
        raise ValueError("No runs are configured.")
    loaded: list[tuple[str, RunData]] = []
    for run_spec in specs:
        run_data = read_run(run_spec, config)
        loaded.append((run_spec.label, run_data))
    return loaded
