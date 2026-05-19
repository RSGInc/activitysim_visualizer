from __future__ import annotations

import numpy as np
import polars as pl

from processor.skimjoin.config.schema import NormalizedLookupRule
from processor.skimjoin.annotate.trip_work_items import (
    _rule_destination_column,
    _rule_origin_column,
)


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


def _apply_output_columns(
    trips: pl.DataFrame,
    results: pl.DataFrame,
) -> pl.DataFrame:
    if results.is_empty():
        return trips

    outputs_long = (
        results.group_by(["_row_id", "output", "combine_method"], maintain_order=True)
        .agg(
            pl.when(pl.col("combine_method").first() == "sum")
            .then(pl.col("value").sum())
            .otherwise(pl.col("value").first())
            .alias("value")
        )
        .select("_row_id", "output", "value")
    )

    outputs_wide = (
        outputs_long.pivot(
            on="output",
            index="_row_id",
            values="value",
            aggregate_function="first",
        )
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


def _empty_lookup_results_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "_row_id": pl.Int64,
            "trip_id": pl.Int64,
            "rule_name": pl.String,
            "mode": pl.String,
            "component": pl.String,
            "output": pl.String,
            "combine_method": pl.String,
            "lookup_chain_id": pl.String,
            "lookup_step_index": pl.Int64,
            "lookup_role": pl.String,
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


def _select_resolved_chain_results(results: pl.DataFrame) -> pl.DataFrame:
    if results.is_empty():
        return results
    valid = results.filter(pl.col("valid"))
    if valid.is_empty():
        return valid
    return (
        valid.sort(["_row_id", "output", "lookup_chain_id", "lookup_step_index"])
        .group_by(["_row_id", "output", "lookup_chain_id"], maintain_order=True)
        .agg(pl.all().sort_by("lookup_step_index").first())
        .select(results.columns)
    )


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
