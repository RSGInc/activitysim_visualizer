"""Zone, MAZ/TAZ, and skim-distance helpers for prepare enrichment."""

from __future__ import annotations

from typing import Optional

from runtime.logging import get_logger
import numpy as np
import polars as pl

from processor.prepare.enrichment.columns import _resolve_source_column
from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _record_prepare_metric(
    state: _PrepareState,
    metric_id: str,
    *,
    total: int,
    unresolved: int,
    details: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "total": int(total),
        "unresolved": int(unresolved),
    }
    if total > 0:
        payload["unresolved_share"] = float(unresolved) / float(total)
    if details:
        payload.update(details)
    state.prepare_diagnostics[metric_id] = payload


def _nullable_float_numpy(series: pl.Series) -> np.ndarray:
    return np.array(series.cast(pl.Float64).to_list(), dtype=float)


def _skim_series(name: str, values: np.ndarray) -> pl.Series:
    return pl.Series(name, values).fill_nan(None)


def _log_prepare_diagnostics(state: _PrepareState) -> None:
    for metric_id, payload in sorted(state.prepare_diagnostics.items()):
        if not isinstance(payload, dict):
            continue
        unresolved = int(payload.get("unresolved", 0) or 0)
        total = int(payload.get("total", 0) or 0)
        if unresolved <= 0:
            continue
        share = payload.get("unresolved_share")
        if isinstance(share, (int, float)):
            LOGGER.warning(
                "[prepare_data] %s for '%s': %s unresolved of %s rows (%.1f%%).",
                metric_id,
                state.label,
                unresolved,
                total,
                float(share) * 100.0,
            )
        else:
            LOGGER.warning(
                "[prepare_data] %s for '%s': %s unresolved rows.",
                metric_id,
                state.label,
                unresolved,
            )


def _build_aggregation_lookup_table(config: Config) -> dict[str, pl.DataFrame]:
    lookups: dict[str, pl.DataFrame] = {}
    for aggregation in config.geography_aggregations.aggregations:
        if not aggregation.lookup_rows:
            continue
        zone_ids = [zone_id for zone_id, _ in aggregation.lookup_rows]
        geography_ids = [geography_id for _, geography_id in aggregation.lookup_rows]
        lookups[aggregation.name] = pl.DataFrame(
            {
                "_zone_id": zone_ids,
                "_geography_id": geography_ids,
                "_geography_type": [aggregation.name] * len(zone_ids),
                "_source_zone_system": [aggregation.source_zone_system] * len(zone_ids),
            },
            schema={
                "_zone_id": pl.Int64,
                "_geography_id": pl.Utf8,
                "_geography_type": pl.Utf8,
                "_source_zone_system": pl.Utf8,
            },
        )
    return lookups


def _skim_lookup(
    skim: np.ndarray,
    otaz: np.ndarray,
    dtaz: np.ndarray,
    zone_map: Optional[dict[int, int]] = None,
) -> np.ndarray:
    """Vectorized skim lookup; supports OMX mappings and 1-based fallback."""
    o_arr = np.asarray(otaz, dtype=float)
    d_arr = np.asarray(dtaz, dtype=float)
    dist = np.full(len(o_arr), np.nan, dtype=float)
    valid_input = np.isfinite(o_arr) & np.isfinite(d_arr)
    if not valid_input.any():
        return dist

    o_valid = o_arr[valid_input].astype(int, copy=False)
    d_valid = d_arr[valid_input].astype(int, copy=False)
    if zone_map:
        o_idx = np.fromiter(
            (zone_map.get(int(z), -1) for z in o_valid), dtype=int, count=len(o_valid)
        )
        d_idx = np.fromiter(
            (zone_map.get(int(z), -1) for z in d_valid), dtype=int, count=len(d_valid)
        )
    else:
        o_min = int(np.min(o_valid)) if len(o_valid) else 0
        d_min = int(np.min(d_valid)) if len(d_valid) else 0
        o_max = int(np.max(o_valid)) if len(o_valid) else 0
        d_max = int(np.max(d_valid)) if len(d_valid) else 0
        if (
            (o_min >= 0 and d_min >= 0)
            and (o_max < skim.shape[0] and d_max < skim.shape[1])
            and ((o_valid == 0).any() or (d_valid == 0).any())
        ):
            o_idx = o_valid
            d_idx = d_valid
        else:
            o_idx = o_valid - 1
            d_idx = d_valid - 1
    valid = (
        (o_idx >= 0) & (d_idx >= 0) & (o_idx < skim.shape[0]) & (d_idx < skim.shape[1])
    )
    valid_positions = np.flatnonzero(valid_input)
    dist[valid_positions[valid]] = skim[o_idx[valid], d_idx[valid]]
    return dist


def _build_zone_context(state: _PrepareState, config: Config) -> _ZoneContext:
    maz_taz: pl.DataFrame | None = None
    maz_source_col = None
    taz_source_col = _resolve_source_column(state.land_use, config.taz_col)
    if config.use_maz and taz_source_col is not None:
        maz_source_col = _resolve_source_column(state.land_use, config.maz_col)
    if maz_source_col is not None:
        LOGGER.info("[prepare_data] Building MAZ->TAZ lookup for '%s'", state.label)
        if maz_source_col != config.maz_col[0]:
            LOGGER.warning(
                "Warning: configured MAZ column '%s' not found for run '%s'; using '%s' for MAZ->TAZ lookup.",
                config.maz_col[0],
                state.label,
                maz_source_col,
            )
        maz_taz = (
            state.land_use.select([maz_source_col, taz_source_col])
            .rename({maz_source_col: "_maz", taz_source_col: "_taz"})
            .unique("_maz")
        )
    elif config.use_maz:
        LOGGER.warning(
            "[prepare_data] Could not build MAZ->TAZ lookup for '%s'; MAZ-based TAZ fields will remain unresolved.",
            state.label,
        )

    zone_geo: pl.DataFrame | None = None
    geography_zone_source = _resolve_source_column(
        state.land_use,
        config.taz_col if config.use_maz else config.maz_col,
    )
    if (
        config.geography_enabled
        and config.geography_landuse_col
        and geography_zone_source is not None
        and config.geography_landuse_col in state.land_use.columns
    ):
        LOGGER.info(
            "[prepare_data] Applying geography labels from '%s'",
            config.geography_landuse_col,
        )
        geo_col = config.geography_landuse_col
        zone_geo = (
            state.land_use.select([geography_zone_source, geo_col])
            .rename({geography_zone_source: "_taz"})
            .unique("_taz")
        )
        if config.geography_mapping:
            zone_geo = zone_geo.with_columns(
                config.apply_geo_mapping(pl.col(geo_col)).alias(geo_col)
            )

    return _ZoneContext(
        maz_taz=maz_taz,
        zone_geo=zone_geo,
        aggregation_lookups=_build_aggregation_lookup_table(config),
    )


def _to_taz(
    df: pl.DataFrame,
    zone_col: str,
    out_col: str,
    *,
    state: _PrepareState,
    metric_id: str,
    config: Config,
    zone_context: _ZoneContext,
) -> pl.DataFrame:
    if not config.use_maz:
        if zone_col in df.columns:
            return df.with_columns(pl.col(zone_col).alias(out_col))
        return df
    if zone_col not in df.columns:
        return df
    source = df.get_column(zone_col)
    total = source.drop_nulls().len()
    if zone_context.maz_taz is None:
        unresolved_df = df.with_columns(pl.lit(None, dtype=pl.Int64).alias(out_col))
        _record_prepare_metric(
            state,
            metric_id,
            total=total,
            unresolved=total,
            details={"source_column": zone_col, "lookup_available": False},
        )
        return unresolved_df
    mapped = df.join(
        zone_context.maz_taz.rename({"_maz": zone_col, "_taz": out_col}),
        on=zone_col,
        how="left",
    )
    unresolved = mapped.filter(pl.col(zone_col).is_not_null() & pl.col(out_col).is_null()).height
    _record_prepare_metric(
        state,
        metric_id,
        total=total,
        unresolved=unresolved,
        details={"source_column": zone_col, "lookup_available": True},
    )
    return mapped


def _add_geo(
    df: pl.DataFrame,
    taz_col: str,
    out_col: str,
    *,
    config: Config,
    zone_context: _ZoneContext,
) -> pl.DataFrame:
    if zone_context.zone_geo is None or taz_col not in df.columns:
        return df
    geo_col = config.geography_landuse_col
    return df.join(
        zone_context.zone_geo.rename({"_taz": taz_col, geo_col: out_col}),
        on=taz_col,
        how="left",
    )


def _add_aggregated_geography(
    df: pl.DataFrame,
    zone_col: str,
    out_col: str,
    *,
    aggregation_name: str,
    source_zone_system: str,
    zone_context: _ZoneContext,
) -> pl.DataFrame:
    lookup = zone_context.aggregation_lookups.get(aggregation_name)
    if lookup is None or zone_col not in df.columns:
        return df
    return df.join(
        lookup.filter(pl.col("_source_zone_system") == source_zone_system)
        .rename({"_zone_id": zone_col, "_geography_id": out_col})
        .select([zone_col, out_col]),
        on=zone_col,
        how="left",
    )


def _add_land_use_aggregated_geographies(
    land_use: pl.DataFrame,
    *,
    config: Config,
    zone_context: _ZoneContext,
) -> pl.DataFrame:
    result = land_use
    for aggregation in config.geography_aggregations.aggregations:
        zone_col = "MAZ" if aggregation.source_zone_system == "maz" else "TAZ"
        result = _add_aggregated_geography(
            result,
            zone_col,
            f"land_use_geo__{aggregation.name}",
            aggregation_name=aggregation.name,
            source_zone_system=aggregation.source_zone_system,
            zone_context=zone_context,
        )
    return result
