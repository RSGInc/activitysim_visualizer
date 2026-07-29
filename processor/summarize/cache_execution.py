"""Summary execution helpers separate from cache persistence."""

from __future__ import annotations

import polars as pl

from runtime.logging import get_logger
from processor.models import RunData
from processor.summarize.cache_types import normalize_weighting_modes, strip_weights
from processor.summarize.contracts import empty_summary_frame, missing_summary_inputs
from runtime.config import Config

LOGGER = get_logger("processor.summarize.cache")


def _summary_spec(
    summary_id: str,
    *,
    summary_spec_by_id: dict[str, object],
):
    spec = summary_spec_by_id.get(summary_id)
    if spec is None:
        raise KeyError(f"Unknown summary id: {summary_id}")
    return spec


def _resolved_summary_ids(
    *,
    config: Config,
    summary_ids: list[str] | None,
    default_summary_ids: list[str],
) -> list[str]:
    return summary_ids or list(default_summary_ids)


def _empty_summary_result(
    summary_id: str,
    *,
    summary_spec_by_id: dict[str, object],
) -> pl.DataFrame:
    return empty_summary_frame(_summary_spec(summary_id, summary_spec_by_id=summary_spec_by_id).builder)


def _detail_from_missing_inputs(missing_inputs: dict[str, str]) -> str:
    return "; ".join(
        f"{table_name} ({reason})"
        for table_name, reason in sorted(missing_inputs.items())
    )


def _summary_state_for_table(table: pl.DataFrame) -> str:
    return "empty" if table.is_empty() else "available"


def _run_data_by_weighting_mode(
    rd: RunData,
    weighting_modes: list[str],
) -> dict[str, RunData]:
    mode_runs: dict[str, RunData] = {"weighted": rd}
    if "unweighted" in weighting_modes:
        mode_runs["unweighted"] = strip_weights(rd)
    return mode_runs


def _build_one_summary_with_metadata(
    summary_id: str,
    *,
    rd: RunData,
    config: Config,
    summary_spec_by_id: dict[str, object],
) -> tuple[pl.DataFrame, dict[str, object]]:
    spec = _summary_spec(summary_id, summary_spec_by_id=summary_spec_by_id)
    missing_inputs = missing_summary_inputs(spec.builder, rd)
    if missing_inputs:
        detail = _detail_from_missing_inputs(missing_inputs)
        LOGGER.warning(
            "Skipping summary %r for run %r because required prepared inputs are unavailable: %s",
            summary_id,
            rd.label,
            detail,
        )
        return _empty_summary_result(
            summary_id,
            summary_spec_by_id=summary_spec_by_id,
        ), {"state": "unavailable", "detail": detail}

    try:
        table = spec.builder(rd, config)
    except Exception as exc:
        LOGGER.warning(
            "Summary %r failed for run %r: %s",
            summary_id,
            rd.label,
            exc,
        )
        return _empty_summary_result(
            summary_id,
            summary_spec_by_id=summary_spec_by_id,
        ), {"state": "failed", "detail": str(exc)}

    return table, {"state": _summary_state_for_table(table)}


def build_summaries(
    rd: RunData,
    config: Config,
    *,
    summary_ids: list[str] | None,
    default_summary_ids: list[str],
    summary_spec_by_id: dict[str, object],
) -> dict[str, pl.DataFrame]:
    """Build the requested summary tables for one prepared run."""
    resolved_summary_ids = _resolved_summary_ids(
        config=config,
        summary_ids=summary_ids,
        default_summary_ids=default_summary_ids,
    )
    tables: dict[str, pl.DataFrame] = {}
    for summary_id in resolved_summary_ids:
        spec = _summary_spec(summary_id, summary_spec_by_id=summary_spec_by_id)
        tables[summary_id] = spec.builder(rd, config)
    return tables


def build_summaries_with_metadata(
    rd: RunData,
    config: Config,
    *,
    summary_ids: list[str] | None,
    default_summary_ids: list[str],
    summary_spec_by_id: dict[str, object],
) -> tuple[dict[str, pl.DataFrame], dict[str, dict[str, object]]]:
    """Build summaries plus per-summary execution metadata."""
    resolved_summary_ids = _resolved_summary_ids(
        config=config,
        summary_ids=summary_ids,
        default_summary_ids=default_summary_ids,
    )
    tables: dict[str, pl.DataFrame] = {}
    metadata: dict[str, dict[str, object]] = {}
    for summary_id in resolved_summary_ids:
        table, summary_metadata = _build_one_summary_with_metadata(
            summary_id,
            rd=rd,
            config=config,
            summary_spec_by_id=summary_spec_by_id,
        )
        tables[summary_id] = table
        metadata[summary_id] = summary_metadata
    return tables, metadata


def build_mode_summaries(
    rd: RunData,
    config: Config,
    *,
    weighting_modes: list[str] | None,
    summary_ids: list[str] | None,
    default_summary_ids: list[str],
    summary_spec_by_id: dict[str, object],
) -> dict[str, dict[str, pl.DataFrame]]:
    """Build the requested summaries for every enabled weighting mode."""
    resolved_weighting_modes = normalize_weighting_modes(
        weighting_modes or config.weighting_modes
    )
    mode_runs = _run_data_by_weighting_mode(rd, resolved_weighting_modes)
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    for mode in resolved_weighting_modes:
        mode_rd = mode_runs["weighted"] if mode == "weighted" else mode_runs[mode]
        summaries_by_mode[mode] = build_summaries(
            mode_rd,
            config,
            summary_ids=summary_ids,
            default_summary_ids=default_summary_ids,
            summary_spec_by_id=summary_spec_by_id,
        )
    return summaries_by_mode


def build_mode_summaries_with_metadata(
    rd: RunData,
    config: Config,
    *,
    weighting_modes: list[str] | None,
    summary_ids: list[str] | None,
    default_summary_ids: list[str],
    summary_spec_by_id: dict[str, object],
) -> tuple[
    dict[str, dict[str, pl.DataFrame]],
    dict[str, dict[str, dict[str, object]]],
]:
    """Build requested summaries plus per-mode execution metadata."""
    resolved_weighting_modes = normalize_weighting_modes(
        weighting_modes or config.weighting_modes
    )
    mode_runs = _run_data_by_weighting_mode(rd, resolved_weighting_modes)
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
    for mode in resolved_weighting_modes:
        mode_rd = mode_runs["weighted"] if mode == "weighted" else mode_runs[mode]
        mode_tables, mode_metadata = build_summaries_with_metadata(
            mode_rd,
            config,
            summary_ids=summary_ids,
            default_summary_ids=default_summary_ids,
            summary_spec_by_id=summary_spec_by_id,
        )
        summaries_by_mode[mode] = mode_tables
        metadata_by_mode[mode] = mode_metadata
    return summaries_by_mode, metadata_by_mode

