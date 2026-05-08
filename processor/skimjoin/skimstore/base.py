from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


class SkimStore:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], np.ndarray] = {}

    def get_matrix(self, file_path: str, matrix_path: str) -> np.ndarray:
        key = (file_path, matrix_path)
        if key not in self._cache:
            with h5py.File(Path(file_path), "r") as handle:
                self._cache[key] = handle[matrix_path][:]
        return self._cache[key]

    def get_zone_map(
        self,
        file_path: str,
        *,
        lookup_name: str | None = None,
    ) -> dict[int, int] | None:
        return None

    def lookup_values(
        self,
        file_path: str,
        matrix_path: str,
        origins: np.ndarray,
        destinations: np.ndarray,
        *,
        lookup_name: str | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        matrix = self.get_matrix(file_path, matrix_path)
        zone_map = self.get_zone_map(file_path, lookup_name=lookup_name)
        o_idx, d_idx = _zone_indices(origins, destinations, matrix, zone_map=zone_map)
        valid = (
            (o_idx >= 0)
            & (d_idx >= 0)
            & (o_idx < matrix.shape[0])
            & (d_idx < matrix.shape[1])
        )
        values = np.full(len(o_idx), np.nan, dtype=float)
        values[valid] = matrix[o_idx[valid], d_idx[valid]]
        return values, valid


def _zone_indices(
    origins: np.ndarray,
    destinations: np.ndarray,
    matrix: np.ndarray,
    *,
    zone_map: dict[int, int] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    o_arr = np.asarray(origins, dtype=np.int64)
    d_arr = np.asarray(destinations, dtype=np.int64)
    if zone_map:
        o_idx = np.fromiter(
            (zone_map.get(int(value), -1) for value in o_arr),
            dtype=np.int64,
            count=len(o_arr),
        )
        d_idx = np.fromiter(
            (zone_map.get(int(value), -1) for value in d_arr),
            dtype=np.int64,
            count=len(d_arr),
        )
        return o_idx, d_idx

    o_min = int(np.min(o_arr)) if len(o_arr) else 0
    d_min = int(np.min(d_arr)) if len(d_arr) else 0
    o_max = int(np.max(o_arr)) if len(o_arr) else 0
    d_max = int(np.max(d_arr)) if len(d_arr) else 0
    if (
        (o_min >= 0 and d_min >= 0)
        and (o_max < matrix.shape[0] and d_max < matrix.shape[1])
        and ((o_arr == 0).any() or (d_arr == 0).any())
    ):
        return o_arr, d_arr
    return o_arr - 1, d_arr - 1
