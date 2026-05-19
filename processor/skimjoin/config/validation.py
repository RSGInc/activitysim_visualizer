from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from processor.skimjoin.config.normalize import normalize_config
from processor.skimjoin.config.schema import (
    ExplicitConfig,
    NormalizedConfig,
    NormalizedLookupRule,
)


class ConfigValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationArtifacts:
    config: ExplicitConfig
    normalized: NormalizedConfig
    inventory: pl.DataFrame


def load_config(
    data: dict[str, Any],
    *,
    require_activitysim_tables: bool = True,
) -> ExplicitConfig:
    config = ExplicitConfig.model_validate(data)
    if require_activitysim_tables and not config.activitysim.trips_table:
        raise ConfigValidationError(
            "activitysim.trips_table is required for standalone skimjoin workflows."
        )
    return config


def validate_config(
    config_data: dict[str, Any],
    inventory: pl.DataFrame,
    trips: pl.DataFrame,
    tours: pl.DataFrame | None = None,
    *,
    strict: bool = True,
) -> ValidationArtifacts:
    config = load_config(config_data)
    normalized = normalize_config(config)
    failures: list[str] = []
    warnings: list[str] = []

    matrix_rows = inventory.select(
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
    inventory_by_name: dict[str, dict[str, object]] = {}
    duplicate_names: list[str] = []
    for row in matrix_rows:
        matrix_name = str(row["matrix_name"])
        if matrix_name in inventory_by_name:
            duplicate_names.append(matrix_name)
            continue
        inventory_by_name[matrix_name] = row
    if duplicate_names:
        failures.append("Duplicate matrix names in skim inventory: " + ", ".join(sorted(set(duplicate_names))))

    failures.extend(_validate_required_columns(normalized, trips, tours))
    failures.extend(_validate_mode_coverage(normalized, trips))
    failures.extend(_validate_segment_coverage(normalized, trips))

    output_masks: dict[str, list[tuple[NormalizedLookupRule, pl.Series]]] = {}
    referenced_matrices: set[str] = set()
    mode_column_available = normalized.activitysim.mode_column in trips.columns

    for rule in normalized.lookups:
        structure_failures = _validate_rule_structure(rule)
        failures.extend(structure_failures)
        if structure_failures:
            continue
        missing_columns = _missing_trip_columns_for_rule(rule, trips)
        if missing_columns:
            continue
        if not mode_column_available:
            continue
        mask, rule_failures = _rule_mask(trips, normalized.activitysim.mode_column, rule)
        failures.extend(f"{rule.name}: {message}" for message in rule_failures)
        if rule_failures:
            continue

        prior_entries = output_masks.get(rule.output, [])
        for prior_rule, prior_mask in prior_entries:
            overlap = prior_mask & mask
            if int(overlap.sum()) <= 0:
                continue
            if prior_rule.lookup_chain_id == rule.lookup_chain_id:
                continue
            if (
                prior_rule.combine_method == "sum"
                and rule.combine_method == "sum"
            ):
                continue
            failures.append(
                f"Output collision on {rule.output!r}: overlapping rows include {rule.name}"
            )
        prior_entries.append((rule, mask))
        output_masks[rule.output] = prior_entries

        subset = trips.filter(mask)
        if subset.is_empty():
            warnings.append(f"{rule.name}: rule matched zero trips")
            continue

        combos, combo_failures = _rule_matrix_combinations(rule, subset)
        failures.extend(f"{rule.name}: {message}" for message in combo_failures)
        for combo in combos:
            matrix_name = str(combo["matrix_name"])
            referenced_matrices.add(matrix_name)
            if matrix_name not in inventory_by_name:
                failures.append(f"{rule.name}: referenced matrix {matrix_name!r} was not found in skim inventory")
                continue
            if str(inventory_by_name[matrix_name]["source_kind"]) == "od_matrix" and rule.lookup == "od":
                shape_rows = int(inventory_by_name[matrix_name]["shape_rows"])
                shape_cols = int(inventory_by_name[matrix_name]["shape_cols"])
                zone_failures, zone_warnings = _validate_od_bounds(rule, combo["rows"], shape_rows, shape_cols)
                failures.extend(f"{rule.name}: {message}" for message in zone_failures)
                warnings.extend(f"{rule.name}: {message}" for message in zone_warnings)

    if normalized.activitysim.tour_id_column not in trips.columns:
        failures.append(f"Trips table is missing tour id column {normalized.activitysim.tour_id_column!r}.")
    if tours is not None and normalized.activitysim.tour_id_column not in tours.columns:
        failures.append(f"Tours table is missing tour id column {normalized.activitysim.tour_id_column!r}.")

    normalized.failures = failures
    normalized.warnings = warnings
    normalized.referenced_matrices = sorted(referenced_matrices)

    if strict and failures:
        raise ConfigValidationError("\n".join(failures))
    return ValidationArtifacts(config=config, normalized=normalized, inventory=inventory)


def _validate_required_columns(
    normalized: NormalizedConfig,
    trips: pl.DataFrame,
    tours: pl.DataFrame | None,
) -> list[str]:
    failures: list[str] = []
    mode_column = normalized.activitysim.mode_column
    if mode_column not in trips.columns:
        failures.append(f"Trips table is missing mode column {mode_column!r}.")
    outbound_column = normalized.activitysim.outbound_column
    if normalized.tour_aggregation.directional_outputs and outbound_column not in trips.columns:
        failures.append(f"Trips table is missing outbound column {outbound_column!r}.")

    for rule in normalized.lookups:
        required_trip_columns = {*rule.when.keys()}
        if rule.lookup == "key":
            if rule.key_column is not None:
                required_trip_columns.add(rule.key_column)
        else:
            required_trip_columns.add(rule.origin)
            required_trip_columns.add(rule.destination)
        for dimension_name in rule.dimensions_used:
            if dimension_name not in rule.dimensions:
                continue
            required_trip_columns.add(rule.dimensions[dimension_name].source_column)
        missing = sorted(column for column in required_trip_columns if column not in trips.columns)
        if missing:
            failures.append(f"{rule.name}: missing trips columns: {', '.join(missing)}")

    if tours is not None:
        if normalized.activitysim.tour_id_column not in tours.columns:
            failures.append(f"Tours table is missing {normalized.activitysim.tour_id_column!r}.")
    return failures


def _missing_trip_columns_for_rule(rule: NormalizedLookupRule, trips: pl.DataFrame) -> list[str]:
    required_trip_columns = {*rule.when.keys()}
    if rule.lookup == "key":
        if rule.key_column is not None:
            required_trip_columns.add(rule.key_column)
    else:
        required_trip_columns.add(rule.origin)
        required_trip_columns.add(rule.destination)
    for dimension_name in rule.dimensions_used:
        if dimension_name not in rule.dimensions:
            continue
        required_trip_columns.add(rule.dimensions[dimension_name].source_column)
    return sorted(column for column in required_trip_columns if column not in trips.columns)


def _validate_mode_coverage(normalized: NormalizedConfig, trips: pl.DataFrame) -> list[str]:
    mode_column = normalized.activitysim.mode_column
    if mode_column not in trips.columns:
        return []
    observed = {str(value) for value in trips.get_column(mode_column).drop_nulls().unique().to_list()}
    covered = {rule.mode for rule in normalized.lookups}
    ignored = set(normalized.ignore_modes)
    missing = sorted(mode for mode in observed if mode not in covered and mode not in ignored)
    return [f"Uncovered ActivitySim modes: {', '.join(missing)}"] if missing else []


def _validate_segment_coverage(normalized: NormalizedConfig, trips: pl.DataFrame) -> list[str]:
    failures: list[str] = []
    mode_column = normalized.activitysim.mode_column
    if mode_column not in trips.columns:
        return failures
    for mode_name, metadata in normalized.segment_validations.items():
        column = str(metadata["column"])
        if column not in trips.columns:
            failures.append(f"modes.{mode_name}: segment_on column {column!r} is missing from trips.")
            continue
        subset = trips.filter(pl.col(mode_column) == mode_name)
        observed = {value for value in subset.get_column(column).drop_nulls().unique().to_list()}
        configured = set(metadata["values"])
        missing = observed - configured
        if missing:
            failures.append(
                f"modes.{mode_name}: segment_on {column!r} is missing configured values for {', '.join(map(str, sorted(missing, key=str)))}"
            )
    return failures


def _validate_rule_structure(rule: NormalizedLookupRule) -> list[str]:
    failures: list[str] = []
    if rule.lookup == "key" and not rule.key_column:
        failures.append("lookup 'key' requires key_column")
    for dimension_name in rule.dimensions_used:
        if dimension_name not in rule.dimensions:
            failures.append(f"placeholder {{{dimension_name}}} is not defined in dimensions")
    return failures


def _rule_mask(
    trips: pl.DataFrame,
    mode_column: str,
    rule: NormalizedLookupRule,
) -> tuple[pl.Series, list[str]]:
    failures: list[str] = []
    mask = trips.get_column(mode_column) == rule.mode
    for column, condition in rule.when.items():
        if column not in trips.columns:
            failures.append(f"when references missing trips column {column!r}")
            continue
        if isinstance(condition, dict):
            extra_keys = set(condition) - {"in"}
            if extra_keys:
                failures.append(f"unsupported when operators for column {column!r}: {', '.join(sorted(extra_keys))}")
                continue
            values = condition.get("in")
            if not isinstance(values, list):
                failures.append(f"when.{column}.in must be a list")
                continue
            mask = mask & trips.get_column(column).is_in(values)
        else:
            mask = mask & (trips.get_column(column) == condition)
    return mask, failures


def _rule_matrix_combinations(
    rule: NormalizedLookupRule,
    subset: pl.DataFrame,
) -> tuple[list[dict[str, object]], list[str]]:
    failures: list[str] = []
    if subset.is_empty():
        return [], failures
    select_columns = [_rule_origin_column(rule)]
    destination_column = _rule_destination_column(rule)
    if destination_column is not None:
        select_columns.append(destination_column)
    select_columns.extend({rule.dimensions[name].source_column for name in rule.dimensions_used})
    rows = subset.select(select_columns).to_dicts()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        matrix_name, error = _render_matrix_name(rule, row)
        if error is not None:
            failures.append(error)
            continue
        grouped.setdefault(matrix_name, []).append(row)
    return [{"matrix_name": matrix_name, "rows": combo_rows} for matrix_name, combo_rows in grouped.items()], failures


def _render_matrix_name(rule: NormalizedLookupRule, row: dict[str, object]) -> tuple[str, str | None]:
    matrix_name = rule.matrix
    for dimension_name in rule.dimensions_used:
        dimension = rule.dimensions[dimension_name]
        raw_value = row.get(dimension.source_column)
        raw_key = str(raw_value)
        if dimension.values:
            if raw_key not in dimension.values:
                return "", f"dimension {dimension_name!r} has no configured token for observed value {raw_value!r}"
            token = dimension.values[raw_key]
        else:
            if raw_value is None:
                return "", f"dimension {dimension_name!r} source column {dimension.source_column!r} is null"
            token = str(raw_value)
        matrix_name = matrix_name.replace(f"{{{dimension_name}}}", token)
    return matrix_name, None


def _validate_od_bounds(
    rule: NormalizedLookupRule,
    rows: list[dict[str, object]],
    shape_rows: int,
    shape_cols: int,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    for row in rows:
        origin = row.get(rule.origin)
        destination = row.get(rule.destination)
        invalid = (
            origin is None
            or destination is None
            or not isinstance(origin, (int, float))
            or not isinstance(destination, (int, float))
            or int(origin) < 1
            or int(destination) < 1
            or int(origin) > shape_rows
            or int(destination) > shape_cols
        )
        if not invalid:
            continue
        message = (
            f"OD values origin={origin!r}, destination={destination!r} are outside matrix bounds "
            f"({shape_rows}, {shape_cols})"
        )
        policy = rule.missing_od_policy
        if policy == "error":
            failures.append(message)
        elif policy == "warn":
            warnings.append(message)
    return failures, warnings


def _rule_origin_column(rule: NormalizedLookupRule) -> str:
    return rule.key_column if rule.lookup == "key" and rule.key_column is not None else rule.origin


def _rule_destination_column(rule: NormalizedLookupRule) -> str | None:
    if rule.lookup == "key":
        return None
    return rule.destination
