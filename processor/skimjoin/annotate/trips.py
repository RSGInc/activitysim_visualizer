from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.trip_lookup_execution import (
    _execute_lookup_batches,
    _inventory_metadata_frame,
    _missing_matrix_frame,
)
from processor.skimjoin.annotate.trip_lookup_reports import (
    _apply_output_columns,
    _apply_rule_sentinel_values,
    _build_invalid_lookup_frame,
    _build_lookup_summary_frame,
    _concat_missing_frames,
    _empty_lookup_results_frame,
)
from processor.skimjoin.annotate.trip_rule_selection import (
    _missing_mode_column_frame,
    _missing_rule_columns_frame,
    _partition_trips_by_mode,
    _subset_for_rule,
)
from processor.skimjoin.annotate.trip_work_items import _resolve_rule_work_items
from processor.skimjoin.config.schema import NormalizedConfig
from processor.skimjoin.skimstore.base import SkimStore


def annotate_trips(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    skim_store = skim_store or SkimStore()
    mode_column = normalized.activitysim.mode_column
    trips = trips.with_row_index("_row_id")
    if mode_column not in trips.columns:
        return trips.drop("_row_id"), pl.DataFrame(), _missing_mode_column_frame(
            mode_column
        )

    mode_subsets = _partition_trips_by_mode(trips, mode_column)
    work_item_frames, missing_frames = _rule_work_items_and_errors(
        trips=trips,
        normalized=normalized,
        mode_subsets=mode_subsets,
    )
    result_frames = _executed_lookup_results(
        work_item_frames=work_item_frames,
        missing_frames=missing_frames,
        inventory=inventory,
        normalized=normalized,
        skim_store=skim_store,
    )

    rule_by_name = {rule.name: rule for rule in normalized.lookups}
    results = (
        pl.concat(result_frames, how="vertical")
        if result_frames
        else _empty_lookup_results_frame()
    )
    results = _apply_rule_sentinel_values(results, rule_by_name)
    lookup_summary = _build_lookup_summary_frame(results, rule_by_name)
    invalid_lookup_frame = _build_invalid_lookup_frame(results, rule_by_name)
    if not invalid_lookup_frame.is_empty():
        missing_frames.append(invalid_lookup_frame)
    trips = _apply_output_columns(trips, results)
    missing_report = _concat_missing_frames(missing_frames)

    return trips.drop("_row_id"), lookup_summary, missing_report


def _rule_work_items_and_errors(
    *,
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    mode_subsets: dict[str, pl.DataFrame],
) -> tuple[list[pl.DataFrame], list[pl.DataFrame]]:
    work_item_frames: list[pl.DataFrame] = []
    missing_frames: list[pl.DataFrame] = []

    for rule in normalized.lookups:
        missing_columns_frame = _missing_rule_columns_frame(trips, rule)
        if not missing_columns_frame.is_empty():
            missing_frames.append(missing_columns_frame)
            continue
        subset = _subset_for_rule(mode_subsets.get(rule.mode), rule)
        if subset.is_empty():
            continue
        valid_items, resolution_errors = _resolve_rule_work_items(rule, subset)
        if not resolution_errors.is_empty():
            missing_frames.append(resolution_errors)
        if not valid_items.is_empty():
            work_item_frames.append(valid_items)

    return work_item_frames, missing_frames


def _executed_lookup_results(
    *,
    work_item_frames: list[pl.DataFrame],
    missing_frames: list[pl.DataFrame],
    inventory: pl.DataFrame,
    normalized: NormalizedConfig,
    skim_store: SkimStore,
) -> list[pl.DataFrame]:
    if not work_item_frames:
        return []

    work_queue = pl.concat(work_item_frames, how="vertical")
    metadata = _inventory_metadata_frame(inventory, normalized)
    queued = work_queue.join(metadata, on="matrix_name", how="left")
    rule_by_name = {rule.name: rule for rule in normalized.lookups}

    missing_matrix = queued.filter(pl.col("file_path").is_null())
    if not missing_matrix.is_empty():
        for rule_name, matrix_name in missing_matrix.select(
            ["rule_name", "matrix_name"]
        ).unique(maintain_order=True).iter_rows():
            rule = rule_by_name[str(rule_name)]
            group = missing_matrix.filter(
                (pl.col("rule_name") == rule_name)
                & (pl.col("matrix_name") == matrix_name)
            )
            missing_frames.append(_missing_matrix_frame(rule, str(matrix_name), group))

    executable = queued.filter(pl.col("file_path").is_not_null())
    if executable.is_empty():
        return []
    return _execute_lookup_batches(
        executable,
        skim_store=skim_store,
        normalized=normalized,
    )
