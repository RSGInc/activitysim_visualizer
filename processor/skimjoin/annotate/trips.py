from __future__ import annotations

import re

import numpy as np
import polars as pl

from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore


_PLACEHOLDER_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")


def _lookup_summary_schema() -> dict[str, pl.DataType]:
    return {
        "rule_name": pl.String,
        "mode": pl.String,
        "component": pl.String,
        "output": pl.String,
        "matrix_name": pl.String,
        "n_trips": pl.Int64,
        "origin_column": pl.String,
        "destination_column": pl.String,
        "mean_value": pl.Float64,
        "min_value": pl.Float64,
        "max_value": pl.Float64,
        "n_missing": pl.Int64,
    }


def _missing_report_schema() -> dict[str, pl.DataType]:
    return {
        "rule_name": pl.String,
        "trip_id": pl.Int64,
        "origin": pl.Int64,
        "destination": pl.Int64,
        "matrix_name": pl.String,
        "reason": pl.String,
    }


def _row_trip_id(row: dict[str, object]) -> object:
    return row.get("trip_id", row.get("_row_id"))


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

    result_frames: list[pl.DataFrame] = []
    missing_frames: list[pl.DataFrame] = []
    work_item_frames: list[pl.DataFrame] = []
    rule_by_name = {rule.name: rule for rule in normalized.lookups}

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

    if work_item_frames:
        work_queue = pl.concat(work_item_frames, how="vertical")
        metadata = _inventory_metadata_frame(inventory, normalized)
        queued = work_queue.join(metadata, on="matrix_name", how="left")

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
                missing_frames.append(
                    _missing_matrix_frame(rule, str(matrix_name), group)
                )

        executable = queued.filter(pl.col("file_path").is_not_null())
        if not executable.is_empty():
            result_frames = _execute_lookup_batches(
                executable,
                skim_store=skim_store,
                normalized=normalized,
            )

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

    return (
        trips.drop("_row_id"),
        lookup_summary,
        missing_report,
    )


def _missing_mode_column_frame(mode_column: str) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "rule_name": None,
                "trip_id": None,
                "origin": None,
                "destination": None,
                "matrix_name": None,
                "reason": f"missing_mode_column:{mode_column}",
            }
        ],
        schema=_missing_report_schema(),
        infer_schema_length=None,
    )


def _missing_rule_columns_frame(
    trips: pl.DataFrame,
    rule: NormalizedLookupRule,
) -> pl.DataFrame:
    missing_columns = _missing_trip_columns_for_rule(trips, rule)
    if not missing_columns:
        return _empty_missing_report_frame()
    return pl.DataFrame(
        [
            {
                "rule_name": rule.name,
                "trip_id": None,
                "origin": None,
                "destination": None,
                "matrix_name": None,
                "reason": f"missing_trip_column:{column}",
            }
            for column in missing_columns
        ],
        schema=_missing_report_schema(),
        infer_schema_length=None,
    )


def _subset_for_rule(
    mode_subset: pl.DataFrame | None,
    rule: NormalizedLookupRule,
) -> pl.DataFrame:
    if mode_subset is None or mode_subset.is_empty():
        return mode_subset.head(0) if mode_subset is not None else pl.DataFrame()
    mask = _build_when_mask(mode_subset, rule)
    return mode_subset.filter(mask)


def _partition_trips_by_mode(
    trips: pl.DataFrame,
    mode_column: str,
) -> dict[str, pl.DataFrame]:
    subsets: dict[str, pl.DataFrame] = {}
    for mode_value in trips.get_column(mode_column).drop_nulls().unique().to_list():
        subsets[str(mode_value)] = trips.filter(trips.get_column(mode_column) == mode_value)
    return subsets


def _missing_matrix_frame(
    rule: NormalizedLookupRule,
    matrix_name: str,
    group: pl.DataFrame,
) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "rule_name": rule.name,
                "trip_id": _row_trip_id(row),
                "origin": row.get("lookup_origin"),
                "destination": row.get("lookup_destination"),
                "matrix_name": matrix_name,
                "reason": "missing_matrix",
            }
            for row in group.to_dicts()
        ],
        schema=_missing_report_schema(),
        infer_schema_length=None,
    )


def _apply_output_columns(
    trips: pl.DataFrame,
    results: pl.DataFrame,
) -> pl.DataFrame:
    if results.is_empty():
        return trips

    outputs_wide = (
        results.select("_row_id", "output", "value")
        .pivot(on="output", index="_row_id", values="value", aggregate_function="first")
        .with_columns(pl.col("_row_id").cast(pl.Int64))
    )
    value_columns = [column for column in outputs_wide.columns if column != "_row_id"]
    if value_columns:
        outputs_wide = outputs_wide.with_columns(
            [
                pl.when(pl.col(column).is_nan())
                .then(None)
                .otherwise(pl.col(column))
                .cast(pl.Float64)
                .alias(column)
                for column in value_columns
            ]
        )
    return trips.join(outputs_wide, on="_row_id", how="left")


def _resolve_rule_work_items(
    rule: NormalizedLookupRule,
    subset: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    work = _base_rule_work_frame(rule, subset)
    token_columns: list[str] = []
    missing_reason_expr = pl.lit(None, dtype=pl.String)

    for dimension_name in rule.dimensions_used:
        dimension = rule.dimensions[dimension_name]
        token_column = f"__token_{dimension_name}"
        token_columns.append(token_column)
        work = _attach_dimension_token(work, dimension_name, dimension.source_column, dimension.values, token_column)
        missing_reason_expr = (
            pl.when(pl.col(token_column).is_null() & missing_reason_expr.is_null())
            .then(pl.lit(f"missing_dimension_value:{dimension_name}"))
            .otherwise(missing_reason_expr)
        )

    work = work.with_columns(missing_reason_expr.alias("__missing_reason"))
    work = work.with_columns(_matrix_name_expr(rule.matrix, rule.dimensions_used).alias("matrix_name"))

    errors = (
        work.filter(pl.col("__missing_reason").is_not_null())
        .select(
            pl.col("rule_name"),
            pl.col("trip_id"),
            pl.col("lookup_origin").cast(pl.Int64, strict=False).alias("origin"),
            pl.col("lookup_destination").cast(pl.Int64, strict=False).alias("destination"),
            pl.lit(None, dtype=pl.String).alias("matrix_name"),
            pl.col("__missing_reason").alias("reason"),
        )
    )

    valid = (
        work.filter(pl.col("__missing_reason").is_null())
        .select(
            "_row_id",
            "trip_id",
            "rule_name",
            "mode",
            "component",
            "output",
            "lookup_origin",
            "lookup_destination",
            "matrix_name",
        )
    )
    return valid, errors


def _base_rule_work_frame(rule: NormalizedLookupRule, subset: pl.DataFrame) -> pl.DataFrame:
    added_names = {"_row_id", "rule_name", "mode", "component", "output", "lookup_origin", "trip_id"}
    select_exprs: list[pl.Expr] = [
        pl.col("_row_id").cast(pl.Int64),
        pl.lit(rule.name).alias("rule_name"),
        pl.lit(rule.mode).alias("mode"),
        pl.lit(rule.component).alias("component"),
        pl.lit(rule.output).alias("output"),
        pl.col(_rule_origin_column(rule)).cast(pl.Float64).alias("lookup_origin"),
    ]
    if "trip_id" in subset.columns:
        select_exprs.append(pl.col("trip_id").cast(pl.Int64, strict=False))
    else:
        select_exprs.append(pl.col("_row_id").cast(pl.Int64).alias("trip_id"))
    destination_column = _rule_destination_column(rule)
    if destination_column is not None:
        select_exprs.append(
            pl.col(destination_column).cast(pl.Float64).alias("lookup_destination")
        )
        added_names.add("lookup_destination")
    else:
        select_exprs.append(pl.lit(None, dtype=pl.Float64).alias("lookup_destination"))
        added_names.add("lookup_destination")

    for dimension_name in rule.dimensions_used:
        source_column = rule.dimensions[dimension_name].source_column
        if source_column not in added_names:
            select_exprs.append(pl.col(source_column))
            added_names.add(source_column)

    return subset.select(select_exprs)


def _attach_dimension_token(
    work: pl.DataFrame,
    dimension_name: str,
    source_column: str,
    values: dict[str, str],
    token_column: str,
) -> pl.DataFrame:
    if not values:
        return work.with_columns(
            pl.when(pl.col(source_column).is_null())
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col(source_column).cast(pl.Utf8))
            .alias(token_column)
        )

    mapping = pl.DataFrame(
        {
            "__dimension_key": list(values.keys()),
            token_column: list(values.values()),
        },
        schema={"__dimension_key": pl.String, token_column: pl.String},
    )
    return (
        work.with_columns(pl.col(source_column).cast(pl.Utf8).alias("__dimension_key"))
        .join(mapping, on="__dimension_key", how="left")
        .drop("__dimension_key")
    )


def _matrix_name_expr(matrix_template: str, dimensions_used: list[str]) -> pl.Expr:
    if not dimensions_used:
        return pl.lit(matrix_template)

    parts: list[pl.Expr] = []
    last = 0
    for match in _PLACEHOLDER_RE.finditer(matrix_template):
        if match.start() > last:
            parts.append(pl.lit(matrix_template[last : match.start()]))
        parts.append(pl.col(f"__token_{match.group(1)}"))
        last = match.end()
    if last < len(matrix_template):
        parts.append(pl.lit(matrix_template[last:]))
    return pl.concat_str(parts, separator="")


def _inventory_metadata_frame(
    inventory: pl.DataFrame,
    normalized: NormalizedConfig,
) -> pl.DataFrame:
    selected = inventory.select(
        [
            "matrix_name",
            "file_path",
            "matrix_path",
            "source_kind",
            "key_column_name",
            "value_column_name",
            "origin_column_name",
            "destination_column_name",
        ]
    )
    rows = selected.to_dicts()
    for row in rows:
        row["lookup_name"] = normalized.zone_mapping.resolve_lookup_name(
            str(row["file_path"])
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def _empty_lookup_results_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "_row_id": pl.Int64,
            "trip_id": pl.Int64,
            "rule_name": pl.String,
            "mode": pl.String,
            "component": pl.String,
            "output": pl.String,
            "lookup_origin": pl.Float64,
            "lookup_destination": pl.Float64,
            "matrix_name": pl.String,
            "source_kind": pl.String,
            "origin_column": pl.String,
            "destination_column": pl.String,
            "value": pl.Float64,
            "valid": pl.Boolean,
            "sentinel_hit": pl.Boolean,
        }
    )


def _empty_missing_report_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_missing_report_schema())


def _execute_lookup_batches(
    executable: pl.DataFrame,
    *,
    skim_store: SkimStore,
    normalized: NormalizedConfig,
) -> list[pl.DataFrame]:
    result_frames: list[pl.DataFrame] = []
    batch_columns = [
        "source_kind",
        "file_path",
        "matrix_path",
        "lookup_name",
        "key_column_name",
        "value_column_name",
        "origin_column_name",
        "destination_column_name",
    ]
    for _, batch in executable.group_by(batch_columns, maintain_order=True):
        result_frames.append(
            _execute_lookup_batch(batch, skim_store=skim_store, normalized=normalized)
        )
    return result_frames


def _execute_lookup_batch(
    batch: pl.DataFrame,
    *,
    skim_store: SkimStore,
    normalized: NormalizedConfig,
) -> pl.DataFrame:
    source_kind = str(batch.item(0, "source_kind"))
    file_path = str(batch.item(0, "file_path"))
    if source_kind == "keyed_column":
        results = skim_store.lookup_keyed_frame(
            file_path,
            batch,
            key_column_name=str(batch.item(0, "key_column_name")),
            value_column_name=str(batch.item(0, "value_column_name")),
        )
    elif source_kind == "od_table":
        results = skim_store.lookup_od_table_frame(
            file_path,
            batch,
            origin_column_name=str(batch.item(0, "origin_column_name")),
            destination_column_name=str(batch.item(0, "destination_column_name")),
            value_column_name=str(batch.item(0, "value_column_name")),
        )
    else:
        results = skim_store.lookup_values_frame(
            file_path,
            str(batch.item(0, "matrix_path")),
            batch,
            lookup_name=normalized.zone_mapping.resolve_lookup_name(file_path),
        )

    if "valid" not in results.columns:
        results = results.with_columns(pl.col("value").is_not_null().alias("valid"))
    return results.with_columns(pl.lit(False).alias("sentinel_hit"))


def _apply_rule_sentinel_values(
    results: pl.DataFrame,
    rule_by_name: dict[str, NormalizedLookupRule],
) -> pl.DataFrame:
    if results.is_empty():
        return results
    adjusted_frames: list[pl.DataFrame] = []
    for rule_name, group in results.group_by("rule_name", maintain_order=True):
        rule = rule_by_name[str(rule_name[0] if isinstance(rule_name, tuple) else rule_name)]
        values = group.get_column("value").cast(pl.Float64).to_numpy()
        valid = group.get_column("valid").cast(pl.Boolean).to_numpy()
        values, valid, sentinel_mask = _nullify_sentinel_values(
            values,
            valid,
            rule.sentinel_values,
        )
        adjusted_frames.append(
            group.with_columns(
                pl.Series("value", values),
                pl.Series("valid", valid),
                pl.Series("sentinel_hit", sentinel_mask),
                pl.lit(_rule_origin_column(rule)).alias("origin_column"),
                pl.lit(_rule_destination_column(rule)).alias("destination_column"),
            )
        )
    return pl.concat(adjusted_frames, how="vertical")


def _build_lookup_summary_frame(
    results: pl.DataFrame,
    rule_by_name: dict[str, NormalizedLookupRule],
) -> pl.DataFrame:
    if results.is_empty():
        return pl.DataFrame(schema=_lookup_summary_schema())
    rows: list[dict[str, object]] = []
    for group_key, group in results.group_by(
        ["rule_name", "matrix_name"], maintain_order=True
    ):
        rule_name, matrix_name = group_key
        rule = rule_by_name[str(rule_name)]
        values = group.get_column("value").cast(pl.Float64).to_numpy()
        valid = group.get_column("valid").cast(pl.Boolean).to_numpy()
        rows.append(
            {
                "rule_name": rule.name,
                "mode": rule.mode,
                "component": rule.component,
                "output": rule.output,
                "matrix_name": str(matrix_name),
                "n_trips": int(group.height),
                "origin_column": _rule_origin_column(rule),
                "destination_column": _rule_destination_column(rule),
                "mean_value": float(np.nanmean(values))
                if np.isfinite(values).any()
                else np.nan,
                "min_value": float(np.nanmin(values))
                if np.isfinite(values).any()
                else np.nan,
                "max_value": float(np.nanmax(values))
                if np.isfinite(values).any()
                else np.nan,
                "n_missing": int((~valid).sum()),
            }
        )
    return pl.DataFrame(
        rows,
        schema=_lookup_summary_schema(),
        infer_schema_length=None,
    )


def _build_invalid_lookup_frame(
    results: pl.DataFrame,
    rule_by_name: dict[str, NormalizedLookupRule],
) -> pl.DataFrame:
    if results.is_empty():
        return _empty_missing_report_frame()
    invalid = results.filter(~pl.col("valid"))
    if invalid.is_empty():
        return _empty_missing_report_frame()
    rows: list[dict[str, object]] = []
    for row in invalid.select(
        [
            "rule_name",
            "trip_id",
            "lookup_origin",
            "lookup_destination",
            "matrix_name",
            "sentinel_hit",
        ]
    ).iter_rows(named=True):
        rule = rule_by_name[str(row["rule_name"])]
        rows.append(
            {
                "rule_name": rule.name,
                "trip_id": row["trip_id"],
                "origin": row["lookup_origin"],
                "destination": row["lookup_destination"],
                "matrix_name": row["matrix_name"],
                "reason": "sentinel_value" if row["sentinel_hit"] else "missing_od",
            }
        )
    return pl.DataFrame(
        rows,
        schema=_missing_report_schema(),
        infer_schema_length=None,
    )


def _concat_missing_frames(missing_frames: list[pl.DataFrame]) -> pl.DataFrame:
    populated = [frame for frame in missing_frames if not frame.is_empty()]
    if not populated:
        return _empty_missing_report_frame()
    return pl.concat(populated, how="vertical")


def _missing_trip_columns_for_rule(trips: pl.DataFrame, rule: NormalizedLookupRule) -> list[str]:
    required_columns = {*rule.when.keys()}
    if rule.lookup == "key":
        if rule.key_column is not None:
            required_columns.add(rule.key_column)
    else:
        required_columns.add(rule.origin)
        required_columns.add(rule.destination)
    for dimension_name in rule.dimensions_used:
        required_columns.add(rule.dimensions[dimension_name].source_column)
    return sorted(column for column in required_columns if column not in trips.columns)


def _build_when_mask(trips: pl.DataFrame, rule: NormalizedLookupRule) -> pl.Series:
    mask = pl.Series([True] * trips.height)
    for column, condition in rule.when.items():
        if isinstance(condition, dict):
            mask = mask & trips.get_column(column).is_in(condition["in"])
        else:
            mask = mask & (trips.get_column(column) == condition)
    return mask


def _rule_origin_column(rule: NormalizedLookupRule) -> str:
    return rule.key_column if rule.lookup == "key" and rule.key_column is not None else rule.origin


def _rule_destination_column(rule: NormalizedLookupRule) -> str | None:
    if rule.lookup == "key":
        return None
    return rule.destination


def _nullify_sentinel_values(
    values: np.ndarray,
    valid: np.ndarray,
    sentinel_values: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sentinel_mask = np.zeros(len(values), dtype=bool)
    if not sentinel_values:
        return values, valid, sentinel_mask
    finite_mask = np.isfinite(values) & valid
    for sentinel_value in sentinel_values:
        sentinel_mask = sentinel_mask | (finite_mask & np.isclose(values, sentinel_value))
    if sentinel_mask.any():
        values = values.copy()
        valid = valid.copy()
        values[sentinel_mask] = np.nan
        valid[sentinel_mask] = False
    return values, valid, sentinel_mask
