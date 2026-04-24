"""Zone, MAZ/TAZ, and skim-distance helpers for prepare enrichment."""

from __future__ import annotations

from typing import Optional

from activitysim_viz_logging import get_logger
import numpy as np
import polars as pl

from processor.prepare.enrichment.types import _PrepareState, _ZoneContext
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _skim_lookup(
    skim: np.ndarray,
    otaz: np.ndarray,
    dtaz: np.ndarray,
    zone_map: Optional[dict[int, int]] = None,
) -> np.ndarray:
    """Vectorized skim lookup; supports OMX mappings and 1-based fallback."""
    o_arr = np.asarray(otaz, dtype=int)
    d_arr = np.asarray(dtaz, dtype=int)
    if zone_map:
        o_idx = np.fromiter(
            (zone_map.get(int(z), -1) for z in o_arr), dtype=int, count=len(o_arr)
        )
        d_idx = np.fromiter(
            (zone_map.get(int(z), -1) for z in d_arr), dtype=int, count=len(d_arr)
        )
    else:
        o_min = int(np.min(o_arr)) if len(o_arr) else 0
        d_min = int(np.min(d_arr)) if len(d_arr) else 0
        o_max = int(np.max(o_arr)) if len(o_arr) else 0
        d_max = int(np.max(d_arr)) if len(d_arr) else 0
        if (
            (o_min >= 0 and d_min >= 0)
            and (o_max < skim.shape[0] and d_max < skim.shape[1])
            and ((o_arr == 0).any() or (d_arr == 0).any())
        ):
            o_idx = o_arr
            d_idx = d_arr
        else:
            o_idx = o_arr - 1
            d_idx = d_arr - 1
    valid = (
        (o_idx >= 0) & (d_idx >= 0) & (o_idx < skim.shape[0]) & (d_idx < skim.shape[1])
    )
    dist = np.zeros(len(o_idx), dtype=float)
    dist[valid] = skim[o_idx[valid], d_idx[valid]]
    return dist


def _build_zone_context(state: _PrepareState, config: Config) -> _ZoneContext:
    maz_taz: pl.DataFrame | None = None
    if (
        config.use_maz
        and config.maz_col in state.land_use.columns
        and config.taz_col in state.land_use.columns
    ):
        LOGGER.info("[prepare_data] Building MAZ->TAZ lookup for '%s'", state.label)
        maz_taz = (
            state.land_use.select([config.maz_col, config.taz_col])
            .rename({config.maz_col: "_maz", config.taz_col: "_taz"})
            .unique("_maz")
        )

    zone_geo: pl.DataFrame | None = None
    if (
        config.geography_enabled
        and config.geography_landuse_col
        and ((config.taz_col if config.use_maz else config.maz_col) in state.land_use.columns)
        and config.geography_landuse_col in state.land_use.columns
    ):
        LOGGER.info(
            "[prepare_data] Applying geography labels from '%s'",
            config.geography_landuse_col,
        )
        geo_col = config.geography_landuse_col
        zone_col = config.taz_col if config.use_maz else config.maz_col
        zone_geo = (
            state.land_use.select([zone_col, geo_col])
            .rename({zone_col: "_taz"})
            .unique("_taz")
        )
        if config.geography_mapping:
            zone_geo = zone_geo.with_columns(
                config.apply_geo_mapping(pl.col(geo_col)).alias(geo_col)
            )

    return _ZoneContext(maz_taz=maz_taz, zone_geo=zone_geo)


def _to_taz(
    df: pl.DataFrame,
    zone_col: str,
    out_col: str,
    *,
    config: Config,
    zone_context: _ZoneContext,
) -> pl.DataFrame:
    if not config.use_maz:
        if zone_col in df.columns:
            return df.with_columns(pl.col(zone_col).alias(out_col))
        return df
    if zone_context.maz_taz is None or zone_col not in df.columns:
        return df
    return df.join(
        zone_context.maz_taz.rename({"_maz": zone_col, "_taz": out_col}),
        on=zone_col,
        how="left",
    ).with_columns(pl.coalesce([pl.col(out_col), pl.col(zone_col)]).alias(out_col))


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
