from __future__ import annotations

from dataclasses import dataclass
import glob
from pathlib import Path
from typing import Iterable

import h5py
import polars as pl


MATRIX_REFERENCE_SEPARATOR = "::"


@dataclass(frozen=True)
class MatrixRecord:
    file_path: str
    matrix_path: str
    matrix_name: str
    shape_rows: int
    shape_cols: int
    dtype: str
    source_kind: str = "od_matrix"
    key_column_name: str | None = None
    value_column_name: str | None = None
    origin_column_name: str | None = None
    destination_column_name: str | None = None


def qualified_matrix_reference(file_path: str | Path, matrix_name: str) -> str:
    return f"{Path(file_path).name}{MATRIX_REFERENCE_SEPARATOR}{matrix_name}"


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
                    source_kind="od_matrix",
                )
            )
    return rows


def inventory_csv_file(path: str | Path) -> list[MatrixRecord]:
    path = Path(path)
    table = pl.read_csv(path)
    if table.width < 2:
        raise ValueError(f"CSV skim file must contain one key column and at least one value column: {path}")

    if _looks_like_od_csv(table.columns):
        origin_column = table.columns[0]
        destination_column = table.columns[1]
        value_columns = [
            column
            for column in table.columns[2:]
            if table.schema[column].is_numeric()
        ]
        if not value_columns:
            raise ValueError(f"CSV O-D skim file must contain at least one numeric value column: {path}")
        rows: list[MatrixRecord] = []
        for value_column in value_columns:
            rows.append(
                MatrixRecord(
                    file_path=str(path),
                    matrix_path=value_column,
                    matrix_name=f"{path.stem}__{value_column}",
                    shape_rows=int(table.height),
                    shape_cols=1,
                    dtype=str(table.schema[value_column]),
                    source_kind="od_table",
                    value_column_name=value_column,
                    origin_column_name=origin_column,
                    destination_column_name=destination_column,
                )
            )
        return rows

    key_column = table.columns[0]
    value_columns = [
        column
        for column in table.columns[1:]
        if table.schema[column].is_numeric()
    ]
    if not value_columns:
        raise ValueError(f"CSV skim file must contain at least one numeric value column: {path}")

    rows: list[MatrixRecord] = []
    for value_column in value_columns:
        rows.append(
            MatrixRecord(
                file_path=str(path),
                matrix_path=value_column,
                matrix_name=f"{path.stem}__{value_column}",
                shape_rows=int(table.height),
                shape_cols=1,
                dtype=str(table.schema[value_column]),
                source_kind="keyed_column",
                key_column_name=key_column,
                value_column_name=value_column,
            )
        )
    return rows


def _looks_like_od_csv(columns: list[str]) -> bool:
    if len(columns) < 3:
        return False
    origin_name = _normalize_csv_column_name(columns[0])
    destination_name = _normalize_csv_column_name(columns[1])
    od_pairs = {
        ("origin", "destination"),
        ("otaz", "dtaz"),
        ("omaz", "dmaz"),
        ("orig", "dest"),
        ("from", "to"),
    }
    return (origin_name, destination_name) in od_pairs


def _normalize_csv_column_name(value: str) -> str:
    return "".join(char for char in str(value).strip().lower() if char.isalnum())


def inventory_skim_files(paths: Iterable[str | Path]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for path in expand_paths(paths):
        suffix = path.suffix.lower()
        if suffix in {".h5", ".hdf5", ".omx"}:
            rows.extend(record.__dict__ for record in inventory_hdf5_file(path))
            continue
        if suffix == ".csv":
            rows.extend(record.__dict__ for record in inventory_csv_file(path))
            continue
        if suffix not in {".h5", ".hdf5", ".omx", ".csv"}:
            raise ValueError(f"Unsupported skim file type: {path}")
    return pl.DataFrame(
        rows,
        schema={
            "file_path": pl.String,
            "matrix_path": pl.String,
            "matrix_name": pl.String,
            "shape_rows": pl.Int64,
            "shape_cols": pl.Int64,
            "dtype": pl.String,
            "source_kind": pl.String,
            "key_column_name": pl.String,
            "value_column_name": pl.String,
            "origin_column_name": pl.String,
            "destination_column_name": pl.String,
        },
        infer_schema_length=None,
    ).sort(["file_path", "matrix_name"])
