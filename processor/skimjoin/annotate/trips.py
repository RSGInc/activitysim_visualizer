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
    include_fallback_report: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame] | tuple[
    pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame
]:
    skim_store = skim_store or SkimStore()
    mode_column = normalized.activitysim.mode_column
    trips = trips.with_row_index("_row_id")
    if mode_column not in trips.columns:
        return trips.drop("_row_id"), pl.DataFrame(), _missing_mode_column_frame(
            mode_column
        )

    mode_subsets = _partition_trips_by_mode(trips, mode_column)
    work_item_frames, missing_frames, attempt_failure_frames, final_failure_frames = _rule_work_items_and_errors(
        normalized=normalized,
        mode_subsets=mode_subsets,
    )
    result_frames, execution_failure_frames, execution_final_failure_frames = _executed_lookup_results(
        work_item_frames=work_item_frames,
        missing_frames=missing_frames,
        inventory=inventory,
        normalized=normalized,
        skim_store=skim_store,
    )
    attempt_failure_frames.extend(execution_failure_frames)
    final_failure_frames.extend(execution_final_failure_frames)

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
    fallback_report = _build_fallback_lookup_report(
        resolved_results=resolved_results,
        attempt_failure_frames=attempt_failure_frames,
        final_failure_frames=final_failure_frames,
        rule_by_name=rule_by_name,
    )

    if include_fallback_report:
        return trips.drop("_row_id"), lookup_summary, missing_report, fallback_report
    return trips.drop("_row_id"), lookup_summary, missing_report


def _rule_work_items_and_errors(
    *,
    normalized: NormalizedConfig,
    mode_subsets: dict[str, pl.DataFrame],
) -> tuple[list[pl.DataFrame], list[pl.DataFrame]]:
    work_item_frames: list[pl.DataFrame] = []
    missing_frames: list[pl.DataFrame] = []
    attempt_failure_frames: list[pl.DataFrame] = []
    final_failure_frames: list[pl.DataFrame] = []

    for chain_rules in _group_rules_by_chain(normalized.lookups):
        chain_work_items, chain_missing, chain_failures = _resolve_chain_work_items(
            chain_rules=chain_rules,
            mode_subsets=mode_subsets,
        )
        work_item_frames.extend(chain_work_items)
        attempt_failure_frames.extend(chain_failures)
        if not chain_missing.is_empty():
            final_failure_frames.append(chain_missing)
            missing_frames.append(_public_missing_frame(chain_missing))

    return work_item_frames, missing_frames, attempt_failure_frames, final_failure_frames


def _executed_lookup_results(
    *,
    work_item_frames: list[pl.DataFrame],
    missing_frames: list[pl.DataFrame],
    inventory: pl.DataFrame,
    normalized: NormalizedConfig,
    skim_store: SkimStore,
) -> tuple[list[pl.DataFrame], list[pl.DataFrame], list[pl.DataFrame]]:
    if not work_item_frames:
        return [], [], []

    metadata = _inventory_metadata_frame(inventory, normalized)
    rule_by_name = {rule.name: rule for rule in normalized.lookups}
    work_queue = pl.concat(work_item_frames, how="vertical")

    result_frames: list[pl.DataFrame] = []
    attempt_failure_frames: list[pl.DataFrame] = []
    final_failure_frames: list[pl.DataFrame] = []
    for _, chain_queue in work_queue.group_by("lookup_chain_id", maintain_order=True):
        chain_results, chain_missing, chain_failures = _execute_chain_queue(
            chain_queue=chain_queue,
            metadata=metadata,
            rule_by_name=rule_by_name,
            normalized=normalized,
            skim_store=skim_store,
        )
        result_frames.extend(chain_results)
        attempt_failure_frames.extend(chain_failures)
        if not chain_missing.is_empty():
            final_failure_frames.append(chain_missing)
            missing_frames.append(_public_missing_frame(chain_missing))
    return result_frames, attempt_failure_frames, final_failure_frames


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
) -> tuple[list[pl.DataFrame], pl.DataFrame, list[pl.DataFrame]]:
    if not chain_rules:
        return [], _empty_missing_detail_report(), []

    base_rule = chain_rules[0]
    subset = _subset_for_rule(mode_subsets.get(base_rule.mode), base_rule)
    if subset.is_empty():
        return [], _empty_missing_detail_report(), []

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

    return (
        work_item_frames,
        _finalize_chain_failures(failure_history, unresolved),
        failure_history,
    )


def _execute_chain_queue(
    *,
    chain_queue: pl.DataFrame,
    metadata: pl.DataFrame,
    rule_by_name: dict[str, NormalizedLookupRule],
    normalized: NormalizedConfig,
    skim_store: SkimStore,
) -> tuple[list[pl.DataFrame], pl.DataFrame, list[pl.DataFrame]]:
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

    return (
        result_frames,
        _finalize_chain_failures(failure_history, unresolved),
        failure_history,
    )


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
        return _empty_missing_detail_report()

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
    return final


def _public_missing_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return _empty_missing_report()
    return frame.select(
        ["rule_name", "trip_id", "origin", "destination", "matrix_name", "reason"]
    ).cast(_missing_report_schema(), strict=False)


def _empty_missing_report() -> pl.DataFrame:
    return pl.DataFrame(schema=_missing_report_schema())


def _empty_missing_detail_report() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "_row_id": pl.Int64,
            "rule_name": pl.String,
            "trip_id": pl.Int64,
            "origin": pl.Int64,
            "destination": pl.Int64,
            "matrix_name": pl.String,
            "reason": pl.String,
            "lookup_chain_id": pl.String,
            "lookup_step_index": pl.Int64,
        }
    )


def _build_fallback_lookup_report(
    *,
    resolved_results: pl.DataFrame,
    attempt_failure_frames: list[pl.DataFrame],
    final_failure_frames: list[pl.DataFrame],
    rule_by_name: dict[str, NormalizedLookupRule],
) -> pl.DataFrame:
    schema = {
        "table_name": pl.String,
        "rule_name": pl.String,
        "output": pl.String,
        "logical_id": pl.Int64,
        "direction": pl.String,
        "primary_matrix_name": pl.String,
        "fallback_matrix_name": pl.String,
        "fallback_step_index": pl.Int64,
        "fallback_reason": pl.String,
        "fallback_eligible": pl.Boolean,
        "fallback_attempted": pl.Boolean,
        "fallback_succeeded": pl.Boolean,
        "fallback_exhausted": pl.Boolean,
    }
    if not attempt_failure_frames and not final_failure_frames and resolved_results.is_empty():
        return pl.DataFrame(schema=schema)

    chain_max_step: dict[str, int] = {}
    for rule in rule_by_name.values():
        chain_max_step[rule.lookup_chain_id] = max(
            chain_max_step.get(rule.lookup_chain_id, 0),
            int(rule.lookup_step_index),
        )
    eligible_chains = {chain_id for chain_id, step in chain_max_step.items() if step > 0}
    if not eligible_chains:
        return pl.DataFrame(schema=schema)

    prior_failures = (
        pl.concat([frame for frame in attempt_failure_frames if not frame.is_empty()], how="vertical_relaxed")
        if attempt_failure_frames
        else _empty_missing_detail_report()
    )
    rows: list[dict[str, object]] = []

    succeeded = resolved_results.filter(
        (pl.col("lookup_chain_id").is_in(list(eligible_chains)))
        & (pl.col("lookup_step_index") > 0)
    )
    for row in succeeded.iter_rows(named=True):
        failures = _prior_failures_for_row(prior_failures, row_id=int(row["_row_id"]), chain_id=str(row["lookup_chain_id"]), step_index=int(row["lookup_step_index"]))
        rows.append(
            {
                "table_name": "trips",
                "rule_name": row["rule_name"],
                "output": row["output"],
                "logical_id": row["trip_id"],
                "direction": rule_by_name[str(row["rule_name"])].direction,
                "primary_matrix_name": _primary_matrix_name(failures),
                "fallback_matrix_name": row["matrix_name"],
                "fallback_step_index": int(row["lookup_step_index"]),
                "fallback_reason": _last_failure_reason(failures),
                "fallback_eligible": True,
                "fallback_attempted": True,
                "fallback_succeeded": True,
                "fallback_exhausted": False,
            }
        )

    for failure in final_failure_frames:
        if failure.is_empty():
            continue
        for row in failure.iter_rows(named=True):
            chain_id = str(row["lookup_chain_id"])
            if chain_id not in eligible_chains:
                continue
            failures = _prior_failures_for_row(prior_failures, row_id=int(row["_row_id"]), chain_id=chain_id)
            rows.append(
                {
                    "table_name": "trips",
                    "rule_name": row["rule_name"],
                    "output": rule_by_name[str(row["rule_name"])].output,
                    "logical_id": row["trip_id"],
                    "direction": rule_by_name[str(row["rule_name"])].direction,
                    "primary_matrix_name": _primary_matrix_name(failures),
                    "fallback_matrix_name": row["matrix_name"],
                    "fallback_step_index": int(row["lookup_step_index"]),
                    "fallback_reason": row["reason"],
                    "fallback_eligible": True,
                    "fallback_attempted": True,
                    "fallback_succeeded": False,
                    "fallback_exhausted": True,
                }
            )

    return pl.DataFrame(rows, schema=schema, infer_schema_length=None).sort(
        ["logical_id", "fallback_succeeded", "fallback_step_index"],
        descending=[False, True, False],
    ) if rows else pl.DataFrame(schema=schema)


def _prior_failures_for_row(
    failures: pl.DataFrame,
    *,
    row_id: int,
    chain_id: str,
    step_index: int | None = None,
) -> pl.DataFrame:
    frame = failures.filter(
        (pl.col("_row_id") == row_id) & (pl.col("lookup_chain_id") == chain_id)
    )
    if step_index is not None:
        frame = frame.filter(pl.col("lookup_step_index") < step_index)
    return frame.sort("lookup_step_index")


def _primary_matrix_name(failures: pl.DataFrame) -> str | None:
    if failures.is_empty():
        return None
    primary = failures.filter(pl.col("lookup_step_index") == 0)
    if primary.is_empty():
        return None
    value = primary.item(0, "matrix_name")
    return str(value) if value is not None else None


def _last_failure_reason(failures: pl.DataFrame) -> str | None:
    if failures.is_empty():
        return None
    value = failures.item(failures.height - 1, "reason")
    return str(value) if value is not None else None
