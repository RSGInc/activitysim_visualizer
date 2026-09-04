"""Build registered summary tables without cache or filesystem concerns."""

from __future__ import annotations

import hashlib
import inspect
import json

import polars as pl

from runtime.logging import get_logger
from processor.models import RunData
from runtime.weighting import WEIGHTING_MODES, normalize_weighting_modes
from processor.summarize.contracts import missing_summary_inputs
from processor.summarize.catalog import (
    DEFAULT_SUMMARY_IDS,
    SUMMARY_BY_ID,
)
from runtime.config import Config

LOGGER = get_logger("processor.summarize.builder")


def summary_builder_identity(summary_id: str) -> dict[str, object]:
    spec = SUMMARY_BY_ID[summary_id]
    try:
        source = inspect.getsource(spec.builder)
    except (OSError, TypeError):
        source = f"{spec.builder.__module__}.{spec.builder.__qualname__}"
    return {
        "summary_id": summary_id,
        "filename": spec.filename,
        "builder_module": spec.builder.__module__,
        "builder_qualname": spec.builder.__qualname__,
        "builder_source_digest": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }


def summary_digest(
    summary_id: str,
    config: Config,
    *,
    analysis_unit_identity: dict[str, object] | None = None,
) -> str:
    payload = {
        "summary_config_digest": config.summary_config_digest,
        "summary": summary_builder_identity(summary_id),
    }
    if analysis_unit_identity is not None:
        payload["analysis_unit"] = analysis_unit_identity
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def summary_digests(
    config: Config,
    summary_ids: list[str] | None = None,
    *,
    analysis_unit_identity: dict[str, object] | None = None,
) -> dict[str, str]:
    return {
        summary_id: summary_digest(
            summary_id,
            config,
            analysis_unit_identity=analysis_unit_identity,
        )
        for summary_id in (
            summary_ids if summary_ids is not None else DEFAULT_SUMMARY_IDS
        )
    }


def _summary_spec(summary_id: str):
    spec = SUMMARY_BY_ID.get(summary_id)
    if spec is None:
        raise KeyError(f"Unknown summary id: {summary_id}")
    return spec


def _summary_ids(summary_ids: list[str] | None) -> list[str]:
    return list(summary_ids) if summary_ids is not None else list(DEFAULT_SUMMARY_IDS)


def _empty_summary(summary_id: str) -> pl.DataFrame:
    return _summary_spec(summary_id).empty()


def _build_one(
    summary_id: str,
    run: RunData,
    config: Config,
    *,
    raise_on_error: bool = False,
) -> tuple[pl.DataFrame, dict[str, object]]:
    spec = _summary_spec(summary_id)
    missing_inputs = missing_summary_inputs(spec.builder, run)
    if missing_inputs:
        detail = "; ".join(
            f"{table_name} ({reason})"
            for table_name, reason in sorted(missing_inputs.items())
        )
        LOGGER.warning(
            "Skipping summary %r for run %r because required prepared inputs are unavailable: %s",
            summary_id,
            run.label,
            detail,
        )
        return _empty_summary(summary_id), {"state": "unavailable", "detail": detail}
    try:
        table = spec.builder(run, config)
    except Exception as exc:
        if raise_on_error:
            raise
        LOGGER.exception("Summary %r failed for run %r", summary_id, run.label)
        return _empty_summary(summary_id), {"state": "failed", "detail": str(exc)}
    return table, {"state": "empty" if table.is_empty() else "available"}


def build_summaries(
    run: RunData,
    config: Config,
    summary_ids: list[str] | None = None,
) -> dict[str, pl.DataFrame]:
    """Build requested tables, allowing builder exceptions to propagate."""
    return {
        summary_id: _summary_spec(summary_id).builder(run, config)
        for summary_id in _summary_ids(summary_ids)
    }


def build_summaries_with_metadata(
    run: RunData,
    config: Config,
    summary_ids: list[str] | None = None,
    *,
    raise_on_error: bool = False,
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, object]]]:
    """Build requested tables while recording unavailable and failed inputs."""
    tables: dict[str, pl.DataFrame] = {}
    metadata: dict[str, dict[str, object]] = {}
    for summary_id in _summary_ids(summary_ids):
        table, table_metadata = _build_one(
            summary_id,
            run,
            config,
            raise_on_error=raise_on_error,
        )
        tables[summary_id] = table
        metadata[summary_id] = table_metadata
    return tables, metadata


def _runs_by_weighting_mode(
    run: RunData,
    config: Config,
    weighting_modes: list[str] | None,
) -> dict[str, RunData]:
    modes = normalize_weighting_modes(
        weighting_modes or config.weighting_modes,
        additional_definitions=config.weighting_mode_definitions,
    )
    configured_definitions = {
        definition.mode_id: definition
        for definition in config.weighting_mode_definitions
    }
    runs: dict[str, RunData] = {}
    for mode in modes:
        definition = configured_definitions.get(mode)
        if definition is None:
            definition = WEIGHTING_MODES.get(mode)
        runs[mode] = definition.apply(run, config)
    return runs


def build_mode_summaries(
    run: RunData,
    config: Config,
    weighting_modes: list[str] | None = None,
    summary_ids: list[str] | None = None,
) -> dict[str, dict[str, pl.DataFrame]]:
    return {
        mode: build_summaries(mode_run, config, summary_ids)
        for mode, mode_run in _runs_by_weighting_mode(
            run, config, weighting_modes
        ).items()
    }


def build_mode_summaries_with_metadata(
    run: RunData,
    config: Config,
    weighting_modes: list[str] | None = None,
    summary_ids: list[str] | None = None,
    *,
    raise_on_error: bool = False,
) -> tuple[
    dict[str, dict[str, pl.DataFrame]],
    dict[str, dict[str, dict[str, object]]],
]:
    tables_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
    for mode, mode_run in _runs_by_weighting_mode(run, config, weighting_modes).items():
        tables, metadata = build_summaries_with_metadata(
            mode_run,
            config,
            summary_ids,
            raise_on_error=raise_on_error,
        )
        tables_by_mode[mode] = tables
        metadata_by_mode[mode] = metadata
    return tables_by_mode, metadata_by_mode
