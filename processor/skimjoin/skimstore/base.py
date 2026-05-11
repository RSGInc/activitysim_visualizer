from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import polars as pl


class SkimStore:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], np.ndarray] = {}
        self._keyed_cache: dict[tuple[str, str, str], dict[int, float]] = {}
        self._od_table_cache: dict[tuple[str, str, str, str], dict[tuple[int, int], float]] = {}

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

    def get_keyed_values(
        self,
        file_path: str,
        *,
        key_column_name: str,
        value_column_name: str,
    ) -> dict[int, float]:
        key = (file_path, key_column_name, value_column_name)
        if key in self._keyed_cache:
            return self._keyed_cache[key]

        table = pl.read_csv(file_path).select([key_column_name, value_column_name])
        values: dict[int, float] = {}
        for row in table.iter_rows(named=True):
            raw_key = row.get(key_column_name)
            raw_value = row.get(value_column_name)
            if raw_key is None or raw_value is None:
                continue
            try:
                values[int(raw_key)] = float(raw_value)
            except (TypeError, ValueError):
                continue
        self._keyed_cache[key] = values
        return values

    def lookup_keyed_values(
        self,
        file_path: str,
        keys: np.ndarray,
        *,
        key_column_name: str,
        value_column_name: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        lookup = self.get_keyed_values(
            file_path,
            key_column_name=key_column_name,
            value_column_name=value_column_name,
        )
        key_arr = np.asarray(keys, dtype=np.float64)
        values = np.full(len(key_arr), np.nan, dtype=float)
        valid = np.zeros(len(key_arr), dtype=bool)
        for idx, raw_key in enumerate(key_arr):
            if np.isnan(raw_key):
                continue
            key_value = int(raw_key)
            if key_value not in lookup:
                continue
            values[idx] = lookup[key_value]
            valid[idx] = True
        return values, valid

    def get_od_table_values(
        self,
        file_path: str,
        *,
        origin_column_name: str,
        destination_column_name: str,
        value_column_name: str,
    ) -> dict[tuple[int, int], float]:
        key = (file_path, origin_column_name, destination_column_name, value_column_name)
        if key in self._od_table_cache:
            return self._od_table_cache[key]

        table = pl.read_csv(file_path).select(
            [origin_column_name, destination_column_name, value_column_name]
        )
        values: dict[tuple[int, int], float] = {}
        for row in table.iter_rows(named=True):
            raw_origin = row.get(origin_column_name)
            raw_destination = row.get(destination_column_name)
            raw_value = row.get(value_column_name)
            if raw_origin is None or raw_destination is None or raw_value is None:
                continue
            try:
                values[(int(raw_origin), int(raw_destination))] = float(raw_value)
            except (TypeError, ValueError):
                continue
        self._od_table_cache[key] = values
        return values

    def lookup_od_table_values(
        self,
        file_path: str,
        origins: np.ndarray,
        destinations: np.ndarray,
        *,
        origin_column_name: str,
        destination_column_name: str,
        value_column_name: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        lookup = self.get_od_table_values(
            file_path,
            origin_column_name=origin_column_name,
            destination_column_name=destination_column_name,
            value_column_name=value_column_name,
        )
        o_arr = np.asarray(origins, dtype=np.float64)
        d_arr = np.asarray(destinations, dtype=np.float64)
        values = np.full(len(o_arr), np.nan, dtype=float)
        valid = np.zeros(len(o_arr), dtype=bool)
        for idx, (raw_origin, raw_destination) in enumerate(zip(o_arr, d_arr, strict=False)):
            if np.isnan(raw_origin) or np.isnan(raw_destination):
                continue
            key = (int(raw_origin), int(raw_destination))
            if key not in lookup:
                continue
            values[idx] = lookup[key]
            valid[idx] = True
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
