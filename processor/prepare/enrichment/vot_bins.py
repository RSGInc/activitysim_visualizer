"""Run-aware VOT bin normalization for prepared skimjoin inputs."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import polars as pl

from processor.prepare.enrichment.types import _PrepareState
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _map_vot_bins(
    df: pl.DataFrame,
    *,
    source_column: str,
    output_column: str,
    mapping: dict[str, str] | None,
    fallback_value: str | None,
) -> pl.DataFrame:
    if output_column in df.columns and source_column == output_column:
        return df
    if source_column not in df.columns:
        return df.with_columns(pl.lit(fallback_value, dtype=pl.Utf8).alias(output_column))

    def _resolve(raw_value: object) -> str | None:
        if raw_value is None:
            return fallback_value
        if mapping is None:
            return fallback_value
        return mapping.get(str(raw_value), fallback_value)

    return df.with_columns(
        pl.col(source_column)
        .map_elements(_resolve, return_dtype=pl.Utf8)
        .alias(output_column)
    )


def _normalize_vot_bins(state: _PrepareState, config: Config) -> _PrepareState:
    settings = config.prepare_vot_bins
    if not settings.enabled:
        return state

    mapping = settings.mapping_for_run(state.label)
    if mapping is None:
        LOGGER.warning(
            "[prepare_data] No VOT bin mapping configured for run '%s'; filling '%s' with fallback values.",
            state.label,
            settings.output_column,
        )

    state.tours = _map_vot_bins(
        state.tours,
        source_column=settings.source_column,
        output_column=settings.output_column,
        mapping=mapping,
        fallback_value=settings.fallback_value,
    )
    state.trips = _map_vot_bins(
        state.trips,
        source_column=settings.source_column,
        output_column=settings.output_column,
        mapping=mapping,
        fallback_value=settings.fallback_value,
    )
    return state

