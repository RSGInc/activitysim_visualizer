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
    _build_lookup_summary_frame,
    _concat_missing_frames,
    _empty_lookup_results_frame,
    _missing_report_schema,
    _select_resolved_chain_results,
)
from processor.skimjoin.annotate.trip_rule_selection import (
    _missing_mode_column_frame,
    _missing_trip_columns_for_rule,
    _partition_trips_by_mode,
    _subset_for_rule,
)
from processor.skimjoin.annotate.trip_work_items import _resolve_rule_work_items
from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
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
        pl.concat(result_frames, how="vertical_relaxed")
        if result_frames
        else _empty_lookup_results_frame()
    )
    lookup_summary = _build_lookup_summary_frame(results, rule_by_name)
    resolved_results = _select_resolved_chain_results(results)
    trips = _apply_output_columns(trips, resolved_results)
    missing_report = _concat_missing_frames(missing_frames)

    return trips.drop("_row_id"), lookup_summary, missing_report


def _rule_work_items_and_errors(
    *,
    normalized: NormalizedConfig,
    mode_subsets: dict[str, pl.DataFrame],
) -> tuple[list[pl.DataFrame], list[pl.DataFrame]]:
    work_item_frames: list[pl.DataFrame] = []
    missing_frames: list[pl.DataFrame] = []

    for chain_rules in _group_rules_by_chain(normalized.lookups):
        chain_work_items, chain_missing = _resolve_chain_work_items(
            chain_rules=chain_rules,
            mode_subsets=mode_subsets,
        )
        work_item_frames.extend(chain_work_items)
        if not chain_missing.is_empty():
            missing_frames.append(chain_missing)

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

    metadata = _inventory_metadata_frame(inventory, normalized)
    rule_by_name = {rule.name: rule for rule in normalized.lookups}
    work_queue = pl.concat(work_item_frames, how="vertical")

    result_frames: list[pl.DataFrame] = []
    for _, chain_queue in work_queue.group_by("lookup_chain_id", maintain_order=True):
        chain_results, chain_missing = _execute_chain_queue(
            chain_queue=chain_queue,
            metadata=metadata,
            rule_by_name=rule_by_name,
            normalized=normalized,
            skim_store=skim_store,
        )
        result_frames.extend(chain_results)
        if not chain_missing.is_empty():
            missing_frames.append(chain_missing)
    return result_frames


def _group_rules_by_chain(
    rules: list[NormalizedLookupRule],
) -> list[list[NormalizedLookupRule]]:
    grouped: dict[str, list[NormalizedLookupRule]] = {}
    for rule in rules:
        grouped.setdefault(rule.lookup_chain_id, []).append(rule)
    return [
        sorted(chain_rules, key=lambda rule: rule.lookup_step_index)
        for chain_rules in grouped.values()
    ]


def _resolve_chain_work_items(
    *,
    chain_rules: list[NormalizedLookupRule],
    mode_subsets: dict[str, pl.DataFrame],
) -> tuple[list[pl.DataFrame], pl.DataFrame]:
    if not chain_rules:
        return [], _empty_missing_report()

    base_rule = chain_rules[0]
    subset = _subset_for_rule(mode_subsets.get(base_rule.mode), base_rule)
    if subset.is_empty():
        return [], _empty_missing_report()

    work_item_frames: list[pl.DataFrame] = []
    failure_history: list[pl.DataFrame] = []
    planned_row_ids: list[pl.DataFrame] = []

    for rule in chain_rules:
        missing_columns = _missing_trip_columns_for_rule(subset, rule)
        if missing_columns:
            failure_history.append(
                _chain_failure_frame_for_rows(
                    subset,
                    rule=rule,
                    reason=f"missing_trip_column:{missing_columns[0]}",
                )
            )
            continue

        valid_items, resolution_errors = _resolve_rule_work_items(rule, subset)
        if not resolution_errors.is_empty():
            failure_history.append(
                _decorate_failure_frame(resolution_errors, rule=rule)
            )
        if valid_items.is_empty():
            continue

        work_item_frames.append(valid_items)
        planned_row_ids.append(valid_items.select("_row_id").unique())

    if planned_row_ids:
        planned = pl.concat(planned_row_ids, how="vertical").unique(maintain_order=True)
        unresolved = subset.join(planned, on="_row_id", how="anti")
    else:
        unresolved = subset

    return work_item_frames, _finalize_chain_failures(failure_history, unresolved)


def _execute_chain_queue(
    *,
    chain_queue: pl.DataFrame,
    metadata: pl.DataFrame,
    rule_by_name: dict[str, NormalizedLookupRule],
    normalized: NormalizedConfig,
    skim_store: SkimStore,
) -> tuple[list[pl.DataFrame], pl.DataFrame]:
    result_frames: list[pl.DataFrame] = []
    failure_history: list[pl.DataFrame] = []
    unresolved = chain_queue.select(["_row_id", "trip_id"]).unique(maintain_order=True)

    for step_index in sorted(
        int(value) for value in chain_queue.get_column("lookup_step_index").unique().to_list()
    ):
        if unresolved.is_empty():
            break
        step_queue = (
            chain_queue.filter(pl.col("lookup_step_index") == step_index)
            .join(unresolved, on=["_row_id", "trip_id"], how="inner")
        )
        if step_queue.is_empty():
            continue

        queued = step_queue.join(metadata, on="matrix_name", how="left")

        missing_matrix = queued.filter(pl.col("file_path").is_null())
        if not missing_matrix.is_empty():
            for row in missing_matrix.select(
                ["rule_name", "matrix_name"]
            ).unique(maintain_order=True).iter_rows(named=True):
                rule = rule_by_name[str(row["rule_name"])]
                group = missing_matrix.filter(
                    (pl.col("rule_name") == row["rule_name"])
                    & (pl.col("matrix_name") == row["matrix_name"])
                )
                failure_history.append(
                    _decorate_failure_frame(
                        _missing_matrix_frame(rule, str(row["matrix_name"]), group),
                        rule=rule,
                    )
                )

        executable = queued.filter(pl.col("file_path").is_not_null())
        if executable.is_empty():
            continue

        step_results_frames = _execute_lookup_batches(
            executable,
            skim_store=skim_store,
            normalized=normalized,
        )
        if not step_results_frames:
            continue

        step_results = pl.concat(step_results_frames, how="vertical")
        step_results = _apply_rule_sentinel_values(step_results, rule_by_name)
        result_frames.append(step_results)

        invalid = step_results.filter(~pl.col("valid"))
        if not invalid.is_empty():
            failure_history.append(_invalid_chain_failure_frame(invalid))

        resolved_row_ids = (
            step_results.filter(pl.col("valid")).select("_row_id").unique()
        )
        if not resolved_row_ids.is_empty():
            unresolved = unresolved.join(resolved_row_ids, on="_row_id", how="anti")

    return result_frames, _finalize_chain_failures(failure_history, unresolved)


def _chain_failure_frame_for_rows(
    rows: pl.DataFrame,
    *,
    rule: NormalizedLookupRule,
    reason: str,
) -> pl.DataFrame:
    trip_id_expr = (
        pl.col("trip_id").cast(pl.Int64, strict=False)
        if "trip_id" in rows.columns
        else pl.col("_row_id").cast(pl.Int64).alias("trip_id")
    )
    origin_expr = (
        pl.col(rule.origin).cast(pl.Int64, strict=False).alias("origin")
        if rule.origin in rows.columns
        else pl.lit(None, dtype=pl.Int64).alias("origin")
    )
    destination_expr = (
        pl.col(rule.destination).cast(pl.Int64, strict=False).alias("destination")
        if rule.lookup != "key" and rule.destination in rows.columns
        else pl.lit(None, dtype=pl.Int64).alias("destination")
    )
    return rows.select(
        pl.col("_row_id").cast(pl.Int64),
        pl.lit(rule.name).alias("rule_name"),
        trip_id_expr,
        origin_expr,
        destination_expr,
        pl.lit(None, dtype=pl.String).alias("matrix_name"),
        pl.lit(reason).alias("reason"),
        pl.lit(rule.lookup_chain_id).alias("lookup_chain_id"),
        pl.lit(rule.lookup_step_index).cast(pl.Int64).alias("lookup_step_index"),
    )


def _decorate_failure_frame(
    frame: pl.DataFrame,
    *,
    rule: NormalizedLookupRule,
) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.with_columns(
        pl.col("trip_id").cast(pl.Int64, strict=False),
        pl.lit(rule.lookup_chain_id).alias("lookup_chain_id"),
        pl.lit(rule.lookup_step_index).cast(pl.Int64).alias("lookup_step_index"),
    )


def _invalid_chain_failure_frame(results: pl.DataFrame) -> pl.DataFrame:
    return results.select(
        pl.col("_row_id").cast(pl.Int64),
        "rule_name",
        pl.col("trip_id").cast(pl.Int64, strict=False),
        pl.col("lookup_origin").cast(pl.Int64, strict=False).alias("origin"),
        pl.col("lookup_destination").cast(pl.Int64, strict=False).alias("destination"),
        "matrix_name",
        pl.when(pl.col("sentinel_hit"))
        .then(pl.lit("sentinel_value"))
        .otherwise(pl.lit("missing_od"))
        .alias("reason"),
        "lookup_chain_id",
        pl.col("lookup_step_index").cast(pl.Int64),
    )


def _finalize_chain_failures(
    failure_history: list[pl.DataFrame],
    unresolved: pl.DataFrame,
) -> pl.DataFrame:
    frames = [frame for frame in failure_history if not frame.is_empty()]
    if not frames or unresolved.is_empty():
        return _empty_missing_report()

    failures = pl.concat(frames, how="vertical")
    final = (
        failures.join(unresolved.select("_row_id"), on="_row_id", how="inner")
        .sort(["_row_id", "lookup_step_index"])
        .group_by("_row_id", maintain_order=True)
        .agg(pl.all().sort_by("lookup_step_index").last())
        .select(
            [
                "rule_name",
                "trip_id",
                "origin",
                "destination",
                "matrix_name",
                "reason",
            ]
        )
    )
    return final.cast(_missing_report_schema(), strict=False)


def _empty_missing_report() -> pl.DataFrame:
    return pl.DataFrame(schema=_missing_report_schema())
