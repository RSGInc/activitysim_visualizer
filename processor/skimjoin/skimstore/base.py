from __future__ import annotations

from pathlib import Path
import re

import h5py
import numpy as np
import polars as pl


class SkimStore:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], np.ndarray] = {}
        self._keyed_cache: dict[tuple[str, str, str], dict[int, float]] = {}
        self._keyed_table_cache: dict[tuple[str, str, str], pl.DataFrame] = {}
        self._keyed_csv_cache: dict[tuple[str, str], pl.DataFrame] = {}
        self._keyed_csv_columns: dict[tuple[str, str], set[str]] = {}
        self._od_table_cache: dict[tuple[str, str, str, str], dict[tuple[int, int], float]] = {}
        self._od_table_frame_cache: dict[tuple[str, str, str, str], pl.DataFrame] = {}
        self._od_csv_cache: dict[tuple[str, str, str], pl.DataFrame] = {}
        self._od_csv_columns: dict[tuple[str, str, str], set[str]] = {}

    def plan_csv_tables(
        self,
        inventory: pl.DataFrame,
        *,
        matrix_templates: set[str],
    ) -> None:
        patterns = [_matrix_template_pattern(template) for template in matrix_templates]
        if not patterns:
            return

        rows = inventory.filter(
            pl.col("source_kind").is_in(["keyed_column", "od_table"])
        ).to_dicts()
        for row in rows:
            file_path = str(row["file_path"])
            matrix_name = str(row["matrix_name"])
            qualified_name = f"{Path(file_path).name}::{matrix_name}"
            if not any(
                pattern.fullmatch(matrix_name) or pattern.fullmatch(qualified_name)
                for pattern in patterns
            ):
                continue

            value_column = str(row["value_column_name"])
            if row["source_kind"] == "keyed_column":
                key = (file_path, str(row["key_column_name"]))
                self._keyed_csv_columns.setdefault(key, set()).add(value_column)
            else:
                key = (
                    file_path,
                    str(row["origin_column_name"]),
                    str(row["destination_column_name"]),
                )
                self._od_csv_columns.setdefault(key, set()).add(value_column)

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

    def lookup_values_frame(
        self,
        file_path: str,
        matrix_path: str,
        work: pl.DataFrame,
        *,
        lookup_name: str | None = None,
    ) -> pl.DataFrame:
        values, valid = self.lookup_values(
            file_path,
            matrix_path,
            work.get_column("lookup_origin").cast(pl.Int64).to_numpy(),
            work.get_column("lookup_destination").cast(pl.Int64).to_numpy(),
            lookup_name=lookup_name,
        )
        return work.with_columns(
            pl.Series("value", values),
            pl.Series("valid", valid),
        )

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

        table = self.get_keyed_table(
            file_path,
            key_column_name=key_column_name,
            value_column_name=value_column_name,
        )
        values = dict(
            zip(
                table.get_column("__lookup_key").cast(pl.Int64).to_list(),
                table.get_column("__lookup_value").to_list(),
                strict=True,
            )
        )
        self._keyed_cache[key] = values
        return values

    def get_keyed_table(
        self,
        file_path: str,
        *,
        key_column_name: str,
        value_column_name: str,
    ) -> pl.DataFrame:
        key = (file_path, key_column_name, value_column_name)
        if key in self._keyed_table_cache:
            return self._keyed_table_cache[key]

        csv_key = (file_path, key_column_name)
        value_columns = self._keyed_csv_columns.setdefault(csv_key, set())
        value_columns.add(value_column_name)
        combined = self._keyed_csv_cache.get(csv_key)
        if combined is None or value_column_name not in combined.columns:
            self._keyed_table_cache = {
                cache_key: table
                for cache_key, table in self._keyed_table_cache.items()
                if cache_key[:2] != csv_key
            }
            self._keyed_cache = {
                cache_key: values
                for cache_key, values in self._keyed_cache.items()
                if cache_key[:2] != csv_key
            }
            combined = (
                pl.scan_csv(file_path)
                .select(
                    pl.col(key_column_name).cast(pl.Float64).alias("__lookup_key"),
                    *(
                        pl.col(column).cast(pl.Float64)
                        for column in sorted(value_columns)
                    ),
                )
                .filter(pl.col("__lookup_key").is_not_null())
                .group_by("__lookup_key")
                .agg(
                    *(
                        pl.col(column)
                        .drop_nulls()
                        .last()
                        .alias(column)
                        for column in sorted(value_columns)
                    )
                )
                .collect(engine="streaming")
            )
            self._keyed_csv_cache[csv_key] = combined

        table = (
            combined.select(
                pl.col("__lookup_key"),
                pl.col(value_column_name).alias("__lookup_value"),
            )
            .filter(pl.col("__lookup_value").is_not_null())
        )
        self._keyed_table_cache[key] = table
        return table

    def lookup_keyed_values(
        self,
        file_path: str,
        keys: np.ndarray,
        *,
        key_column_name: str,
        value_column_name: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        table = self.get_keyed_table(
            file_path,
            key_column_name=key_column_name,
            value_column_name=value_column_name,
        )
        key_arr = np.asarray(keys, dtype=np.float64)
        work = pl.DataFrame(
            {
                "__row_id": np.arange(len(key_arr), dtype=np.int64),
                "__lookup_key": key_arr,
            }
        )
        joined = work.join(table, on="__lookup_key", how="left").sort("__row_id")
        value_series = joined.get_column("__lookup_value")
        return value_series.to_numpy(), value_series.is_not_null().to_numpy()

    def lookup_keyed_frame(
        self,
        file_path: str,
        work: pl.DataFrame,
        *,
        key_column_name: str,
        value_column_name: str,
    ) -> pl.DataFrame:
        table = self.get_keyed_table(
            file_path,
            key_column_name=key_column_name,
            value_column_name=value_column_name,
        )
        return (
            work.join(
                table,
                left_on="lookup_origin",
                right_on="__lookup_key",
                how="left",
            )
            .with_columns(
                pl.col("__lookup_value").alias("value"),
                pl.col("__lookup_value").is_not_null().alias("valid"),
            )
            .drop(["__lookup_value"])
        )

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

        table = self.get_od_table_frame(
            file_path,
            origin_column_name=origin_column_name,
            destination_column_name=destination_column_name,
            value_column_name=value_column_name,
        )
        values = dict(
            zip(
                zip(
                    table.get_column("__lookup_origin").cast(pl.Int64).to_list(),
                    table.get_column("__lookup_destination").cast(pl.Int64).to_list(),
                    strict=True,
                ),
                table.get_column("__lookup_value").to_list(),
                strict=True,
            )
        )
        self._od_table_cache[key] = values
        return values

    def get_od_table_frame(
        self,
        file_path: str,
        *,
        origin_column_name: str,
        destination_column_name: str,
        value_column_name: str,
    ) -> pl.DataFrame:
        key = (file_path, origin_column_name, destination_column_name, value_column_name)
        if key in self._od_table_frame_cache:
            return self._od_table_frame_cache[key]

        csv_key = (file_path, origin_column_name, destination_column_name)
        value_columns = self._od_csv_columns.setdefault(csv_key, set())
        value_columns.add(value_column_name)
        combined = self._od_csv_cache.get(csv_key)
        if combined is None or value_column_name not in combined.columns:
            self._od_table_frame_cache = {
                cache_key: table
                for cache_key, table in self._od_table_frame_cache.items()
                if cache_key[:3] != csv_key
            }
            self._od_table_cache = {
                cache_key: values
                for cache_key, values in self._od_table_cache.items()
                if cache_key[:3] != csv_key
            }
            combined = (
                pl.scan_csv(file_path)
                .select(
                    pl.col(origin_column_name)
                    .cast(pl.Float64)
                    .alias("__lookup_origin"),
                    pl.col(destination_column_name)
                    .cast(pl.Float64)
                    .alias("__lookup_destination"),
                    *(
                        pl.col(column).cast(pl.Float64)
                        for column in sorted(value_columns)
                    ),
                )
                .filter(
                    pl.col("__lookup_origin").is_not_null()
                    & pl.col("__lookup_destination").is_not_null()
                )
                .group_by(
                    ["__lookup_origin", "__lookup_destination"],
                )
                .agg(
                    *(
                        pl.col(column)
                        .drop_nulls()
                        .last()
                        .alias(column)
                        for column in sorted(value_columns)
                    )
                )
                .collect(engine="streaming")
            )
            self._od_csv_cache[csv_key] = combined

        table = (
            combined.select(
                "__lookup_origin",
                "__lookup_destination",
                pl.col(value_column_name).alias("__lookup_value"),
            )
            .filter(pl.col("__lookup_value").is_not_null())
        )
        self._od_table_frame_cache[key] = table
        return table

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
        table = self.get_od_table_frame(
            file_path,
            origin_column_name=origin_column_name,
            destination_column_name=destination_column_name,
            value_column_name=value_column_name,
        )
        o_arr = np.asarray(origins, dtype=np.float64)
        d_arr = np.asarray(destinations, dtype=np.float64)
        work = pl.DataFrame(
            {
                "__row_id": np.arange(len(o_arr), dtype=np.int64),
                "__lookup_origin": o_arr,
                "__lookup_destination": d_arr,
            }
        )
        joined = (
            work.join(
                table,
                on=["__lookup_origin", "__lookup_destination"],
                how="left",
            )
            .sort("__row_id")
        )
        value_series = joined.get_column("__lookup_value")
        return value_series.to_numpy(), value_series.is_not_null().to_numpy()

    def lookup_od_table_frame(
        self,
        file_path: str,
        work: pl.DataFrame,
        *,
        origin_column_name: str,
        destination_column_name: str,
        value_column_name: str,
    ) -> pl.DataFrame:
        table = self.get_od_table_frame(
            file_path,
            origin_column_name=origin_column_name,
            destination_column_name=destination_column_name,
            value_column_name=value_column_name,
        )
        return (
            work.join(
                table,
                left_on=["lookup_origin", "lookup_destination"],
                right_on=["__lookup_origin", "__lookup_destination"],
                how="left",
            )
            .with_columns(
                pl.col("__lookup_value").alias("value"),
                pl.col("__lookup_value").is_not_null().alias("valid"),
            )
            .drop(["__lookup_value"])
        )


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
        o_idx = _map_with_zone_map(o_arr, zone_map)
        d_idx = _map_with_zone_map(d_arr, zone_map)
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


def _map_with_zone_map(values: np.ndarray, zone_map: dict[int, int]) -> np.ndarray:
    if not zone_map:
        return np.full(len(values), -1, dtype=np.int64)

    keys = np.fromiter(zone_map.keys(), dtype=np.int64)
    mapped = np.fromiter(zone_map.values(), dtype=np.int64)
    order = np.argsort(keys)
    keys = keys[order]
    mapped = mapped[order]

    positions = np.searchsorted(keys, values)
    valid = (positions < len(keys)) & (keys[np.clip(positions, 0, len(keys) - 1)] == values)

    result = np.full(len(values), -1, dtype=np.int64)
    if valid.any():
        result[valid] = mapped[positions[valid]]
    return result


def _matrix_template_pattern(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    start = 0
    for match in re.finditer(r"\{[^{}]+\}", template):
        parts.append(re.escape(template[start : match.start()]))
        parts.append(".+")
        start = match.end()
    parts.append(re.escape(template[start:]))
    return re.compile("".join(parts))
