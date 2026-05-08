from __future__ import annotations

from collections import defaultdict

import numpy as np
import polars as pl

from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore


def annotate_trips(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    skim_store = skim_store or SkimStore()
    inventory_by_name = {
        str(row["matrix_name"]): row
        for row in inventory.select(["matrix_name", "file_path", "matrix_path", "shape_rows", "shape_cols"]).to_dicts()
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
                            "trip_id": row.get("trip_id", row["_row_id"]),
                            "origin": row.get(rule.origin),
                            "destination": row.get(rule.destination),
                            "matrix_name": matrix_name,
                            "reason": "missing_matrix",
                        }
                    )
                continue

            inv_row = inventory_by_name[matrix_name]
            values, valid = skim_store.lookup_values(
                str(inv_row["file_path"]),
                str(inv_row["matrix_path"]),
                group.get_column(rule.origin).cast(pl.Int64).to_numpy(),
                group.get_column(rule.destination).cast(pl.Int64).to_numpy(),
                lookup_name=normalized.zone_mapping.lookup_name,
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
                    "origin_column": rule.origin,
                    "destination_column": rule.destination,
                    "mean_value": float(np.nanmean(values)) if np.isfinite(values).any() else np.nan,
                    "min_value": float(np.nanmin(values)) if np.isfinite(values).any() else np.nan,
                    "max_value": float(np.nanmax(values)) if np.isfinite(values).any() else np.nan,
                    "n_missing": int((~valid).sum()),
                }
            )

            invalid_indices = [idx for idx, is_valid in enumerate(valid) if not is_valid]
            for idx in invalid_indices:
                row = group.row(idx, named=True)
                missing_rows.append(
                    {
                        "rule_name": rule.name,
                        "trip_id": row.get("trip_id", row["_row_id"]),
                        "origin": row.get(rule.origin),
                        "destination": row.get(rule.destination),
                        "matrix_name": matrix_name,
                        "reason": "missing_od",
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

    return trips.drop("_row_id"), pl.DataFrame(lookup_rows), pl.DataFrame(missing_rows)


def _missing_trip_columns_for_rule(trips: pl.DataFrame, rule: NormalizedLookupRule) -> list[str]:
    required_columns = {rule.origin, rule.destination, *rule.when.keys()}
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
    required_columns = [rule.origin, rule.destination]
    for dimension_name in rule.dimensions_used:
        required_columns.append(rule.dimensions[dimension_name].source_column)
    rows = subset.select(["_row_id", "trip_id", *dict.fromkeys(required_columns)]).to_dicts()
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
                            "trip_id": row.get("trip_id", row["_row_id"]),
                            "origin": row.get(rule.origin),
                            "destination": row.get(rule.destination),
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
                            "trip_id": row.get("trip_id", row["_row_id"]),
                            "origin": row.get(rule.origin),
                            "destination": row.get(rule.destination),
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
        "groups": {name: pl.DataFrame(rows) for name, rows in groups.items()},
        "errors": errors,
    }
