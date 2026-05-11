from __future__ import annotations

from collections import defaultdict

import numpy as np
import polars as pl

from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore


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
    inventory_by_name = {
        str(row["matrix_name"]): row
        for row in inventory.select(
            [
                "matrix_name",
                "file_path",
                "matrix_path",
                "shape_rows",
                "shape_cols",
                "source_kind",
                "key_column_name",
                "value_column_name",
                "origin_column_name",
                "destination_column_name",
            ]
        ).to_dicts()
    }
    mode_column = normalized.activitysim.mode_column
    trips = trips.with_row_index("_row_id")
    if mode_column not in trips.columns:
        return trips.drop("_row_id"), pl.DataFrame(), pl.DataFrame(
            [{"rule_name": None, "trip_id": None, "origin": None, "destination": None, "matrix_name": None, "reason": f"missing_mode_column:{mode_column}"}]
        )

    output_values: dict[str, dict[int, float | None]] = defaultdict(dict)
    lookup_rows: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []

    for rule in normalized.lookups:
        missing_columns = _missing_trip_columns_for_rule(trips, rule)
        if missing_columns:
            for column in missing_columns:
                missing_rows.append(
                    {
                        "rule_name": rule.name,
                        "trip_id": None,
                        "origin": None,
                        "destination": None,
                        "matrix_name": None,
                        "reason": f"missing_trip_column:{column}",
                    }
                )
            continue
        mask = _build_rule_mask(trips, mode_column, rule)
        subset = trips.filter(mask)
        if subset.is_empty():
            continue
        resolved = _resolve_subset(rule, subset)
        for error in resolved["errors"]:
            missing_rows.append(error)
        for matrix_name, group in resolved["groups"].items():
            if matrix_name not in inventory_by_name:
                for row in group.to_dicts():
                    missing_rows.append(
                        {
                            "rule_name": rule.name,
                            "trip_id": _row_trip_id(row),
                            "origin": row.get(rule.origin),
                            "destination": row.get(rule.destination),
                            "matrix_name": matrix_name,
                            "reason": "missing_matrix",
                        }
                    )
                continue

            inv_row = inventory_by_name[matrix_name]
            source_kind = str(inv_row["source_kind"])
            if source_kind == "keyed_column":
                values, valid = skim_store.lookup_keyed_values(
                    str(inv_row["file_path"]),
                    group.get_column(_rule_origin_column(rule)).cast(pl.Float64).to_numpy(),
                    key_column_name=str(inv_row["key_column_name"]),
                    value_column_name=str(inv_row["value_column_name"]),
                )
            elif source_kind == "od_table":
                values, valid = skim_store.lookup_od_table_values(
                    str(inv_row["file_path"]),
                    group.get_column(rule.origin).cast(pl.Float64).to_numpy(),
                    group.get_column(rule.destination).cast(pl.Float64).to_numpy(),
                    origin_column_name=str(inv_row["origin_column_name"]),
                    destination_column_name=str(inv_row["destination_column_name"]),
                    value_column_name=str(inv_row["value_column_name"]),
                )
            else:
                values, valid = skim_store.lookup_values(
                    str(inv_row["file_path"]),
                    str(inv_row["matrix_path"]),
                    group.get_column(rule.origin).cast(pl.Int64).to_numpy(),
                    group.get_column(rule.destination).cast(pl.Int64).to_numpy(),
                    lookup_name=normalized.zone_mapping.resolve_lookup_name(
                        str(inv_row["file_path"])
                    ),
                )
            values, valid, sentinel_mask = _nullify_sentinel_values(
                values,
                valid,
                rule.sentinel_values,
            )

            row_ids = group.get_column("_row_id").to_list()
            for row_id, value in zip(row_ids, values, strict=False):
                output_values[rule.output][int(row_id)] = None if np.isnan(value) else float(value)

            lookup_rows.append(
                {
                    "rule_name": rule.name,
                    "mode": rule.mode,
                    "component": rule.component,
                    "output": rule.output,
                    "matrix_name": matrix_name,
                    "n_trips": int(group.height),
                    "origin_column": _rule_origin_column(rule),
                    "destination_column": _rule_destination_column(rule),
                    "mean_value": float(np.nanmean(values)) if np.isfinite(values).any() else np.nan,
                    "min_value": float(np.nanmin(values)) if np.isfinite(values).any() else np.nan,
                    "max_value": float(np.nanmax(values)) if np.isfinite(values).any() else np.nan,
                    "n_missing": int((~valid).sum()),
                }
            )

            invalid_indices = [idx for idx, is_valid in enumerate(valid) if not is_valid]
            for idx in invalid_indices:
                row = group.row(idx, named=True)
                reason = "sentinel_value" if sentinel_mask[idx] else "missing_od"
                missing_rows.append(
                    {
                        "rule_name": rule.name,
                        "trip_id": _row_trip_id(row),
                        "origin": row.get(_rule_origin_column(rule)),
                        "destination": row.get(_rule_destination_column(rule)),
                        "matrix_name": matrix_name,
                        "reason": reason,
                    }
                )

    for output, values in output_values.items():
        trips = trips.with_columns(
            pl.col("_row_id").replace_strict(values, default=None).cast(pl.Float64).alias(output)
        )

    output_columns = sorted(output_values)
    for output in output_columns:
        if output not in trips.columns:
            trips = trips.with_columns(pl.lit(None, dtype=pl.Float64).alias(output))

    return (
        trips.drop("_row_id"),
        pl.DataFrame(
            lookup_rows,
            schema=_lookup_summary_schema(),
            infer_schema_length=None,
        ),
        pl.DataFrame(
            missing_rows,
            schema=_missing_report_schema(),
            infer_schema_length=None,
        ),
    )


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


def _build_rule_mask(trips: pl.DataFrame, mode_column: str, rule: NormalizedLookupRule) -> pl.Series:
    mask = trips.get_column(mode_column) == rule.mode
    for column, condition in rule.when.items():
        if isinstance(condition, dict):
            mask = mask & trips.get_column(column).is_in(condition["in"])
        else:
            mask = mask & (trips.get_column(column) == condition)
    return mask


def _resolve_subset(rule: NormalizedLookupRule, subset: pl.DataFrame) -> dict[str, object]:
    required_columns = [_rule_origin_column(rule)]
    destination_column = _rule_destination_column(rule)
    if destination_column is not None:
        required_columns.append(destination_column)
    for dimension_name in rule.dimensions_used:
        required_columns.append(rule.dimensions[dimension_name].source_column)
    select_columns = ["_row_id"]
    if "trip_id" in subset.columns:
        select_columns.append("trip_id")
    select_columns.extend(dict.fromkeys(required_columns))
    rows = subset.select(select_columns).to_dicts()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    errors: list[dict[str, object]] = []
    for row in rows:
        matrix_name = rule.matrix
        failed = False
        for dimension_name in rule.dimensions_used:
            dimension = rule.dimensions[dimension_name]
            raw_value = row.get(dimension.source_column)
            raw_key = str(raw_value)
            if dimension.values:
                token = dimension.values.get(raw_key)
                if token is None:
                    errors.append(
                        {
                            "rule_name": rule.name,
                            "trip_id": _row_trip_id(row),
                            "origin": row.get(_rule_origin_column(rule)),
                            "destination": row.get(_rule_destination_column(rule)),
                            "matrix_name": None,
                            "reason": f"missing_dimension_value:{dimension_name}",
                        }
                    )
                    failed = True
                    break
            else:
                if raw_value is None:
                    errors.append(
                        {
                            "rule_name": rule.name,
                            "trip_id": _row_trip_id(row),
                            "origin": row.get(_rule_origin_column(rule)),
                            "destination": row.get(_rule_destination_column(rule)),
                            "matrix_name": None,
                            "reason": f"missing_dimension_value:{dimension_name}",
                        }
                    )
                    failed = True
                    break
                token = str(raw_value)
            matrix_name = matrix_name.replace(f"{{{dimension_name}}}", token)
        if failed:
            continue
        groups[matrix_name].append(row)
    return {
        "groups": {
            name: pl.DataFrame(rows, infer_schema_length=None)
            for name, rows in groups.items()
        },
        "errors": errors,
    }


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
