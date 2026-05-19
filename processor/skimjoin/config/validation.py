from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from processor.skimjoin.config.normalize import TOUR_DIRECTION_COLUMN, normalize_config
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

    inventory_by_name, duplicate_failures = _inventory_by_name(inventory)
    failures.extend(duplicate_failures)

    trip_source = trips
    tour_source, tour_source_failures = _build_tour_validation_source(normalized, tours)
    failures.extend(tour_source_failures)

    failures.extend(_validate_required_table_columns(normalized, trips, tours))
    failures.extend(
        _validate_target_table(
            normalized=normalized,
            source=trip_source,
            rules=normalized.trip_lookups,
            inventory_by_name=inventory_by_name,
            mode_column=normalized.activitysim.mode_column,
            target_label="Trips",
            ignore_modes=set(normalized.ignore_modes),
            warnings=warnings,
        )
    )
    if tours is not None and tour_source is not None:
        failures.extend(
            _validate_target_table(
                normalized=normalized,
                source=tour_source,
                rules=normalized.tour_lookups,
                inventory_by_name=inventory_by_name,
                mode_column=normalized.activitysim.tour_mode_column,
                target_label="Tours",
                ignore_modes=set(),
                warnings=warnings,
            )
        )

    if normalized.activitysim.tour_id_column not in trips.columns:
        failures.append(
            f"Trips table is missing tour id column {normalized.activitysim.tour_id_column!r}."
        )
    if tours is not None and normalized.activitysim.tour_id_column not in tours.columns:
        failures.append(
            f"Tours table is missing tour id column {normalized.activitysim.tour_id_column!r}."
        )

    normalized.failures = failures
    normalized.warnings = warnings
    normalized.referenced_matrices = sorted(_referenced_matrices(normalized, inventory_by_name, trip_source, tour_source))

    if strict and failures:
        raise ConfigValidationError("\n".join(failures))
    return ValidationArtifacts(config=config, normalized=normalized, inventory=inventory)


def _inventory_by_name(
    inventory: pl.DataFrame,
) -> tuple[dict[str, dict[str, object]], list[str]]:
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
    failures = []
    if duplicate_names:
        failures.append(
            "Duplicate matrix names in skim inventory: "
            + ", ".join(sorted(set(duplicate_names)))
        )
    return inventory_by_name, failures


def _validate_required_table_columns(
    normalized: NormalizedConfig,
    trips: pl.DataFrame,
    tours: pl.DataFrame | None,
) -> list[str]:
    failures: list[str] = []
    trip_mode_column = normalized.activitysim.mode_column
    if trip_mode_column not in trips.columns:
        failures.append(f"Trips table is missing mode column {trip_mode_column!r}.")

    if tours is not None:
        tour_mode_column = normalized.activitysim.tour_mode_column
        if tour_mode_column not in tours.columns:
            failures.append(f"Tours table is missing mode column {tour_mode_column!r}.")
        for column in (
            normalized.activitysim.tour_origin_column,
            normalized.activitysim.tour_destination_column,
        ):
            if column not in tours.columns:
                failures.append(
                    f"Tours table is missing required tour endpoint column {column!r}."
                )
    return failures


def _build_tour_validation_source(
    normalized: NormalizedConfig,
    tours: pl.DataFrame | None,
) -> tuple[pl.DataFrame | None, list[str]]:
    if tours is None:
        return None, []

    activitysim = normalized.activitysim
    required = [
        activitysim.tour_id_column,
        activitysim.tour_mode_column,
        activitysim.tour_origin_column,
        activitysim.tour_destination_column,
    ]
    missing = [column for column in required if column not in tours.columns]
    if missing:
        return None, []

    tours_with_ids = tours.with_row_index("_row_id")
    outbound_origin = pl.col(activitysim.tour_origin_column)
    outbound_destination = pl.col(activitysim.tour_destination_column)

    def _context_frame(*, outbound: bool) -> pl.DataFrame:
        context_origin = outbound_origin if outbound else outbound_destination
        context_destination = outbound_destination if outbound else outbound_origin
        return tours_with_ids.with_columns(
            pl.col("_row_id").cast(pl.Int64),
            pl.col(activitysim.tour_id_column)
            .cast(pl.Int64, strict=False)
            .alias("trip_id"),
            pl.lit(outbound).alias(activitysim.outbound_column),
            pl.lit("outbound" if outbound else "inbound").alias(
                TOUR_DIRECTION_COLUMN
            ),
            context_origin.cast(pl.Float64).alias("OTAZ"),
            context_destination.cast(pl.Float64).alias("DTAZ"),
            context_origin.cast(pl.Float64).alias("o_maz"),
            context_destination.cast(pl.Float64).alias("d_maz"),
        )

    return (
        pl.concat(
            [_context_frame(outbound=True), _context_frame(outbound=False)],
            how="vertical_relaxed",
        ),
        [],
    )


def _validate_target_table(
    *,
    normalized: NormalizedConfig,
    source: pl.DataFrame,
    rules: list[NormalizedLookupRule],
    inventory_by_name: dict[str, dict[str, object]],
    mode_column: str,
    target_label: str,
    ignore_modes: set[str],
    warnings: list[str],
) -> list[str]:
    failures: list[str] = []
    if mode_column not in source.columns:
        return failures

    failures.extend(
        _validate_mode_coverage(
            source=source,
            mode_column=mode_column,
            rules=rules,
            target_label=target_label,
            ignore_modes=ignore_modes,
        )
    )
    failures.extend(
        _validate_segment_coverage(
            normalized=normalized,
            source=source,
            mode_column=mode_column,
            rules=rules,
            target_label=target_label,
        )
    )

    output_masks: dict[str, list[tuple[NormalizedLookupRule, pl.Series]]] = {}
    chains = _group_rules_by_chain(rules)
    for chain_rules in chains:
        failures.extend(_validate_chain_structure(chain_rules))
        viable_rules = _viable_rules_for_source(chain_rules, source)
        if not viable_rules:
            failures.extend(_missing_columns_failures(chain_rules, source, target_label))
            continue

        for rule in viable_rules:
            structure_failures = _validate_rule_structure(rule)
            failures.extend(f"{rule.name}: {message}" for message in structure_failures)
            if structure_failures:
                continue

            mask, rule_failures = _rule_mask(source, mode_column, rule)
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

            subset = source.filter(mask)
            if subset.is_empty():
                warnings.append(f"{rule.name}: rule matched zero {target_label.lower()}")
                continue

            combos, combo_failures = _rule_matrix_combinations(rule, subset)
            failures.extend(f"{rule.name}: {message}" for message in combo_failures)
            for combo in combos:
                matrix_name = str(combo["matrix_name"])
                if matrix_name not in inventory_by_name:
                    failures.append(
                        f"{rule.name}: referenced matrix {matrix_name!r} was not found in skim inventory"
                    )
                    continue
                if (
                    str(inventory_by_name[matrix_name]["source_kind"]) == "od_matrix"
                    and rule.lookup == "od"
                ):
                    shape_rows = int(inventory_by_name[matrix_name]["shape_rows"])
                    shape_cols = int(inventory_by_name[matrix_name]["shape_cols"])
                    zone_failures, zone_warnings = _validate_od_bounds(
                        rule,
                        combo["rows"],
                        shape_rows,
                        shape_cols,
                    )
                    failures.extend(f"{rule.name}: {message}" for message in zone_failures)
                    warnings.extend(f"{rule.name}: {message}" for message in zone_warnings)

    return failures


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


def _validate_chain_structure(chain_rules: list[NormalizedLookupRule]) -> list[str]:
    if not chain_rules:
        return []
    failures: list[str] = []
    chain_id = chain_rules[0].lookup_chain_id
    step_indexes = [int(rule.lookup_step_index) for rule in chain_rules]
    if step_indexes != list(range(len(chain_rules))):
        failures.append(
            f"{chain_id}: lookup chain steps must start at 0 and increase by 1."
        )
    outputs = {rule.output for rule in chain_rules}
    if len(outputs) > 1:
        failures.append(
            f"{chain_id}: fallback chain steps must share the same final output."
        )
    return failures


def _viable_rules_for_source(
    chain_rules: list[NormalizedLookupRule],
    source: pl.DataFrame,
) -> list[NormalizedLookupRule]:
    viable: list[NormalizedLookupRule] = []
    for rule in chain_rules:
        if _missing_rule_columns(rule, source):
            continue
        viable.append(rule)
    return viable


def _missing_columns_failures(
    chain_rules: list[NormalizedLookupRule],
    source: pl.DataFrame,
    target_label: str,
) -> list[str]:
    if not chain_rules:
        return []
    chain_id = chain_rules[0].lookup_chain_id
    missing_union = sorted(
        {
            column
            for rule in chain_rules
            for column in _missing_rule_columns(rule, source)
        }
    )
    if not missing_union:
        return []
    return [
        f"{chain_id}: no usable {target_label.lower()} lookup step remains after missing columns: "
        + ", ".join(missing_union)
    ]


def _missing_rule_columns(
    rule: NormalizedLookupRule,
    source: pl.DataFrame,
) -> list[str]:
    required_columns = set(rule.when.keys())
    if rule.lookup == "key":
        if rule.key_column is not None:
            required_columns.add(rule.key_column)
    else:
        required_columns.add(rule.origin)
        required_columns.add(rule.destination)
    for dimension_name in rule.dimensions_used:
        if dimension_name not in rule.dimensions:
            continue
        required_columns.add(rule.dimensions[dimension_name].source_column)
    return sorted(column for column in required_columns if column not in source.columns)


def _validate_mode_coverage(
    *,
    source: pl.DataFrame,
    mode_column: str,
    rules: list[NormalizedLookupRule],
    target_label: str,
    ignore_modes: set[str],
) -> list[str]:
    if not rules:
        return []
    observed = {
        str(value)
        for value in source.get_column(mode_column).drop_nulls().unique().to_list()
    }
    covered = {rule.mode for rule in rules}
    missing = sorted(mode for mode in observed if mode not in covered and mode not in ignore_modes)
    return [f"Uncovered {target_label} modes: {', '.join(missing)}"] if missing else []


def _validate_segment_coverage(
    *,
    normalized: NormalizedConfig,
    source: pl.DataFrame,
    mode_column: str,
    rules: list[NormalizedLookupRule],
    target_label: str,
) -> list[str]:
    failures: list[str] = []
    modes_with_rules = {rule.mode for rule in rules}
    for mode_name, metadata in normalized.segment_validations.items():
        if mode_name not in modes_with_rules:
            continue
        column = str(metadata["column"])
        if column not in source.columns:
            failures.append(
                f"{target_label} modes.{mode_name}: segment_on column {column!r} is missing."
            )
            continue
        subset = source.filter(pl.col(mode_column) == mode_name)
        observed = {
            value for value in subset.get_column(column).drop_nulls().unique().to_list()
        }
        configured = set(metadata["values"])
        missing = observed - configured
        if missing:
            failures.append(
                f"{target_label} modes.{mode_name}: segment_on {column!r} is missing configured values for "
                + ", ".join(map(str, sorted(missing, key=str)))
            )
    return failures


def _validate_rule_structure(rule: NormalizedLookupRule) -> list[str]:
    failures: list[str] = []
    if rule.lookup == "key" and not rule.key_column:
        failures.append("lookup 'key' requires key_column")
    for dimension_name in rule.dimensions_used:
        if dimension_name not in rule.dimensions:
            failures.append(
                f"placeholder {{{dimension_name}}} is not defined in dimensions"
            )
    return failures


def _rule_mask(
    source: pl.DataFrame,
    mode_column: str,
    rule: NormalizedLookupRule,
) -> tuple[pl.Series, list[str]]:
    failures: list[str] = []
    mask = source.get_column(mode_column) == rule.mode
    for column, condition in rule.when.items():
        if column not in source.columns:
            failures.append(f"when references missing source column {column!r}")
            continue
        if isinstance(condition, dict):
            extra_keys = set(condition) - {"in"}
            if extra_keys:
                failures.append(
                    f"unsupported when operators for column {column!r}: {', '.join(sorted(extra_keys))}"
                )
                continue
            values = condition.get("in")
            if not isinstance(values, list):
                failures.append(f"when.{column}.in must be a list")
                continue
            mask = mask & source.get_column(column).is_in(values)
        else:
            mask = mask & (source.get_column(column) == condition)
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
    select_columns.extend(
        {rule.dimensions[name].source_column for name in rule.dimensions_used}
    )
    rows = subset.select(select_columns).to_dicts()
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        matrix_name, error = _render_matrix_name(rule, row)
        if error is not None:
            failures.append(error)
            continue
        grouped.setdefault(matrix_name, []).append(row)
    return [
        {"matrix_name": matrix_name, "rows": combo_rows}
        for matrix_name, combo_rows in grouped.items()
    ], failures


def _render_matrix_name(
    rule: NormalizedLookupRule, row: dict[str, object]
) -> tuple[str, str | None]:
    matrix_name = rule.matrix
    for dimension_name in rule.dimensions_used:
        dimension = rule.dimensions[dimension_name]
        raw_value = row.get(dimension.source_column)
        raw_key = str(raw_value)
        if dimension.values:
            if raw_key not in dimension.values:
                return (
                    "",
                    f"dimension {dimension_name!r} has no configured token for observed value {raw_value!r}",
                )
            token = dimension.values[raw_key]
        else:
            if raw_value is None:
                return (
                    "",
                    f"dimension {dimension_name!r} source column {dimension.source_column!r} is null",
                )
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
    return (
        rule.key_column if rule.lookup == "key" and rule.key_column is not None else rule.origin
    )


def _rule_destination_column(rule: NormalizedLookupRule) -> str | None:
    if rule.lookup == "key":
        return None
    return rule.destination


def _referenced_matrices(
    normalized: NormalizedConfig,
    inventory_by_name: dict[str, dict[str, object]],
    trip_source: pl.DataFrame,
    tour_source: pl.DataFrame | None,
) -> set[str]:
    referenced: set[str] = set()
    target_specs: list[tuple[list[NormalizedLookupRule], pl.DataFrame | None, str]] = [
        (normalized.trip_lookups, trip_source, normalized.activitysim.mode_column),
        (normalized.tour_lookups, tour_source, normalized.activitysim.tour_mode_column),
    ]
    for rules, source, mode_column in target_specs:
        if source is None or mode_column not in source.columns:
            continue
        for rule in rules:
            if _missing_rule_columns(rule, source):
                continue
            mask, failures = _rule_mask(source, mode_column, rule)
            if failures:
                continue
            subset = source.filter(mask)
            combos, _ = _rule_matrix_combinations(rule, subset)
            for combo in combos:
                matrix_name = str(combo["matrix_name"])
                if matrix_name in inventory_by_name:
                    referenced.add(matrix_name)
    return referenced
