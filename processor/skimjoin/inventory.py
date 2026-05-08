from __future__ import annotations

from dataclasses import dataclass
import glob
from pathlib import Path
from typing import Iterable

import h5py
import polars as pl


@dataclass(frozen=True)
class MatrixRecord:
    file_path: str
    matrix_path: str
    matrix_name: str
    shape_rows: int
    shape_cols: int
    dtype: str


def expand_paths(paths: Iterable[str | Path]) -> list[Path]:
    expanded: list[Path] = []
    for raw_path in paths:
        path_text = str(raw_path)
        path = Path(path_text)
        if any(char in path_text for char in "*?[]"):
            matches = sorted(Path(match) for match in glob.glob(path_text))
            if not matches:
                raise ValueError(f"No skim files matched pattern: {path_text}")
            expanded.extend(matches)
        else:
            if not path.exists():
                raise ValueError(f"Skim file does not exist: {path_text}")
            expanded.append(path)
    return expanded


def _iter_hdf5_datasets(handle: h5py.File) -> Iterable[tuple[str, h5py.Dataset]]:
    datasets: list[tuple[str, h5py.Dataset]] = []

    def visitor(name: str, obj: h5py.Dataset) -> None:
        if isinstance(obj, h5py.Dataset) and len(obj.shape) == 2:
            datasets.append((name, obj))

    handle.visititems(visitor)
    return datasets


def inventory_hdf5_file(path: str | Path) -> list[MatrixRecord]:
    path = Path(path)
    rows: list[MatrixRecord] = []
    with h5py.File(path, "r") as handle:
        for matrix_path, dataset in _iter_hdf5_datasets(handle):
            rows.append(
                MatrixRecord(
                    file_path=str(path),
                    matrix_path=f"/{matrix_path}",
                    matrix_name=Path(matrix_path).name,
                    shape_rows=int(dataset.shape[0]),
                    shape_cols=int(dataset.shape[1]),
                    dtype=str(dataset.dtype),
                )
            )
    return rows


def inventory_skim_files(paths: Iterable[str | Path]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for path in expand_paths(paths):
        if path.suffix.lower() not in {".h5", ".hdf5", ".omx"}:
            raise ValueError(f"Unsupported skim file type: {path}")
        rows.extend(record.__dict__ for record in inventory_hdf5_file(path))
    return pl.DataFrame(rows).sort(["file_path", "matrix_name"])
