from __future__ import annotations

import polars as pl

from processor.skimjoin.config.schema import NormalizedLookupRule
from processor.skimjoin.annotate.trip_lookup_reports import (
    _empty_missing_report_frame,
    _missing_report_schema,
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


def _missing_trip_columns_for_rule(
    trips: pl.DataFrame, rule: NormalizedLookupRule
) -> list[str]:
    required_columns = {*rule.when.keys()}
    if rule.lookup == "key":
        if rule.key_column is not None:
            required_columns.add(rule.key_column)
    else:
        required_columns.add(rule.origin)
        required_columns.add(rule.destination)
    for dimension_name in rule.dimensions_used:
        required_columns.add(rule.dimensions[dimension_name].resolved_source_column)
    return sorted(column for column in required_columns if column not in trips.columns)


def _build_when_mask(trips: pl.DataFrame, rule: NormalizedLookupRule) -> pl.Series:
    mask = pl.Series([True] * trips.height)
    for column, condition in rule.when.items():
        if isinstance(condition, dict):
            mask = mask & trips.get_column(column).is_in(condition["in"])
        else:
            mask = mask & (trips.get_column(column) == condition)
    return mask
