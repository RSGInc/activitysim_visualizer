"""Prepared non-motorized trip distance lookup."""

from __future__ import annotations

from pathlib import Path

from activitysim_viz_logging import get_logger
import numpy as np
import polars as pl

from processor.prepare.enrichment.types import _PrepareState
from processor.prepare.enrichment.zones import (
    _nullable_float_numpy,
    _record_prepare_metric,
    _skim_lookup,
    _skim_series,
)
from runtime.config import Config

LOGGER = get_logger("processor.prepare")
OUTPUT_COLUMN = "prepared_non_motorized_distance"
DIAGNOSTIC_ID = f"trips.{OUTPUT_COLUMN}"
NON_MOTORIZED_MODES = {"WALK", "BIKE", "EBIKE"}


def _load_matrix(path: str, matrix_name: str) -> tuple[np.ndarray, dict[int, int] | None]:
    import openmatrix as omx

    handle = omx.open_file(path)
    try:
        matrix = np.array(handle[matrix_name])
        zone_map: dict[int, int] | None = None
        mappings = handle.list_mappings()
        if mappings:
            raw_map = handle.mapping(mappings[0])
            normalized: dict[int, int] = {}
            for key, value in raw_map.items():
                normalized_key = (
                    key.decode("utf-8")
                    if isinstance(key, (bytes, bytearray))
                    else key
                )
                try:
                    normalized[int(normalized_key)] = int(value)
                except Exception:
                    continue
            zone_map = normalized or None
        return matrix, zone_map
    finally:
        handle.close()


def _eligible_non_motorized_expr() -> pl.Expr:
    return (
        pl.col("trip_mode")
        .cast(pl.Utf8)
        .str.to_uppercase()
        .is_in(sorted(NON_MOTORIZED_MODES))
    )


def _record_diagnostics(
    state: _PrepareState,
    *,
    source_type: str,
    source_file: str,
    matrix_or_column: str | None,
    total: int,
    unresolved: int,
) -> None:
    eligible_unresolved = 0
    if "trip_mode" in state.trips.columns and OUTPUT_COLUMN in state.trips.columns:
        eligible_unresolved = state.trips.filter(
            _eligible_non_motorized_expr() & pl.col(OUTPUT_COLUMN).is_null()
        ).height
    _record_prepare_metric(
        state,
        DIAGNOSTIC_ID,
        total=total,
        unresolved=unresolved,
        details={
            "source_type": source_type,
            "source_file": source_file,
            "matrix": matrix_or_column,
            "value_column": matrix_or_column if source_type == "csv" else None,
            "eligible_non_motorized_unresolved": int(eligible_unresolved),
        },
    )


def _derive_from_csv(state: _PrepareState, config: Config) -> _PrepareState:
    settings = config.prepare_non_motorized_distance_skim
    required = {"o_maz", "d_maz"}
    if not required.issubset(set(state.trips.columns)):
        LOGGER.info(
            "[prepare_data] Non-motorized CSV distance skipped for '%s'; trips need o_maz and d_maz.",
            state.label,
        )
        return state

    lookup = (
        pl.read_csv(settings.file)
        .with_row_index("_nm_lookup_row_id")
        .select(
            pl.col("_nm_lookup_row_id"),
            pl.col("OMAZ").cast(pl.Int64).alias("_nm_o_maz"),
            pl.col("DMAZ").cast(pl.Int64).alias("_nm_d_maz"),
            pl.col(settings.value_column).cast(pl.Float64).alias(OUTPUT_COLUMN),
        )
        .group_by(["_nm_o_maz", "_nm_d_maz"], maintain_order=True)
        .agg(pl.col(OUTPUT_COLUMN).sort_by("_nm_lookup_row_id").last())
    )
    trips = state.trips.drop(OUTPUT_COLUMN, strict=False).with_row_index("_nm_row_id")
    joined = (
        trips.join(
            lookup,
            left_on=["o_maz", "d_maz"],
            right_on=["_nm_o_maz", "_nm_d_maz"],
            how="left",
        )
        .sort("_nm_row_id")
        .drop("_nm_row_id")
    )
    state.trips = joined
    total = state.trips.filter(
        pl.col("o_maz").is_not_null() & pl.col("d_maz").is_not_null()
    ).height
    unresolved = state.trips.filter(
        pl.col("o_maz").is_not_null()
        & pl.col("d_maz").is_not_null()
        & pl.col(OUTPUT_COLUMN).is_null()
    ).height
    _record_diagnostics(
        state,
        source_type="csv",
        source_file=settings.file,
        matrix_or_column=settings.value_column,
        total=total,
        unresolved=unresolved,
    )
    return state


def _derive_from_omx(state: _PrepareState, config: Config) -> _PrepareState:
    settings = config.prepare_non_motorized_distance_skim
    required = {"OTAZ", "DTAZ"}
    if not required.issubset(set(state.trips.columns)):
        LOGGER.info(
            "[prepare_data] Non-motorized OMX distance skipped for '%s'; trips need OTAZ and DTAZ.",
            state.label,
        )
        return state

    matrix, zone_map = _load_matrix(settings.file, settings.matrix)
    origins = _nullable_float_numpy(state.trips["OTAZ"])
    destinations = _nullable_float_numpy(state.trips["DTAZ"])
    distances = _skim_lookup(matrix, origins, destinations, zone_map)
    state.trips = state.trips.drop(OUTPUT_COLUMN, strict=False).with_columns(
        _skim_series(OUTPUT_COLUMN, distances)
    )
    total = state.trips.filter(
        pl.col("OTAZ").is_not_null() & pl.col("DTAZ").is_not_null()
    ).height
    unresolved = state.trips.filter(
        pl.col("OTAZ").is_not_null()
        & pl.col("DTAZ").is_not_null()
        & pl.col(OUTPUT_COLUMN).is_null()
    ).height
    _record_diagnostics(
        state,
        source_type="omx",
        source_file=settings.file,
        matrix_or_column=settings.matrix,
        total=total,
        unresolved=unresolved,
    )
    return state


def _derive_non_motorized_distance(state: _PrepareState, config: Config) -> _PrepareState:
    settings = config.prepare_non_motorized_distance_skim
    if not settings.enabled:
        return state
    if state.trips.is_empty():
        return state

    source_file = Path(settings.file)
    LOGGER.info(
        "[prepare_data] Computing non-motorized distances for '%s' from %s",
        state.label,
        source_file,
    )
    if settings.source_type == "csv":
        return _derive_from_csv(state, config)
    if settings.source_type == "omx":
        return _derive_from_omx(state, config)
    return state
