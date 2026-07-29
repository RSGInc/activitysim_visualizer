from __future__ import annotations

import re
from typing import Any

from processor.time_periods import load_network_los_period_mapping
from processor.skimjoin.config.schema import (
    ActivitySimConfig,
    DimensionConfig,
    ExplicitConfig,
    NormalizedConfig,
    NormalizedLookupRule,
    ResolvedDimensionConfig,
)


PLACEHOLDER_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")
TOUR_DIRECTION_COLUMN = "__skimjoin_tour_direction"
RESERVED_KEYS = {
    "output_prefix",
    "origin",
    "destination",
    "dimensions",
    "when",
    "segment_on",
    "segments",
    "defaults",
    "missing_matrix_policy",
    "missing_od_policy",
    "sentinel_values",
    "skip",
    "apply_to",
    "combine",
    "fallbacks",
    "tour_origin",
    "tour_destination",
}


def extract_placeholders(matrix: str) -> list[str]:
    found: list[str] = []
    for match in PLACEHOLDER_RE.finditer(matrix):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def normalize_config(config: ExplicitConfig) -> NormalizedConfig:
    base_dimensions = _prepare_dimensions(config)
    base_context = {
        "origin": config.defaults.origin,
        "destination": config.defaults.destination,
        "output_prefix": config.defaults.output_prefix,
        "dimensions": base_dimensions,
        "when": {},
        "missing_matrix_policy": config.defaults.missing_matrix_policy,
        "missing_od_policy": config.defaults.missing_od_policy,
        "sentinel_values": list(config.defaults.sentinel_values),
    }
    trip_lookups: list[NormalizedLookupRule] = []
    tour_lookups: list[NormalizedLookupRule] = []
    segment_validations: dict[str, dict[str, Any]] = {}

    for mode_name, raw_mode_block in config.modes.items():
        if not isinstance(raw_mode_block, dict):
            raise ValueError(f"modes.{mode_name} must be a mapping.")
        if raw_mode_block.get("skip") is True:
            continue
        mode_context = _merge_context(base_context, raw_mode_block)
        segment_on = raw_mode_block.get("segment_on")
        segments = raw_mode_block.get("segments")
        if segment_on is not None:
            if not isinstance(segments, dict) or not segments:
                raise ValueError(f"modes.{mode_name} requires non-empty segments when segment_on is set.")
            segment_validations[mode_name] = {
                "column": str(segment_on),
                "values": list(segments.keys()),
            }
            for segment_key, segment_block in segments.items():
                if not isinstance(segment_block, dict):
                    raise ValueError(f"modes.{mode_name}.segments.{segment_key} must be a mapping.")
                segment_context = _merge_context(mode_context, segment_block)
                segment_context["when"] = _merge_when(segment_context["when"], {str(segment_on): segment_key})
                trip_lookups.extend(
                    _normalize_components(
                        mode_name=mode_name,
                        component_source=segment_block,
                        context=segment_context,
                        rule_prefix=f"{mode_name}.{segment_key}",
                        activitysim=config.activitysim,
                        target_table="trips",
                        direction=None,
                    )
                )
                tour_lookups.extend(
                    _normalize_components(
                        mode_name=mode_name,
                        component_source=segment_block,
                        context=segment_context,
                        rule_prefix=f"{mode_name}.{segment_key}",
                        activitysim=config.activitysim,
                        target_table="tours",
                        direction="outbound",
                    )
                )
                tour_lookups.extend(
                    _normalize_components(
                        mode_name=mode_name,
                        component_source=segment_block,
                        context=segment_context,
                        rule_prefix=f"{mode_name}.{segment_key}",
                        activitysim=config.activitysim,
                        target_table="tours",
                        direction="inbound",
                    )
                )
        else:
            trip_lookups.extend(
                _normalize_components(
                    mode_name=mode_name,
                    component_source=raw_mode_block,
                    context=mode_context,
                    rule_prefix=mode_name,
                    activitysim=config.activitysim,
                    target_table="trips",
                    direction=None,
                )
            )
            tour_lookups.extend(
                _normalize_components(
                    mode_name=mode_name,
                    component_source=raw_mode_block,
                    context=mode_context,
                    rule_prefix=mode_name,
                    activitysim=config.activitysim,
                    target_table="tours",
                    direction="outbound",
                )
            )
            tour_lookups.extend(
                _normalize_components(
                    mode_name=mode_name,
                    component_source=raw_mode_block,
                    context=mode_context,
                    rule_prefix=mode_name,
                    activitysim=config.activitysim,
                    target_table="tours",
                    direction="inbound",
                )
            )

    return NormalizedConfig(
        skim_files=config.skim_files,
        activitysim=config.activitysim,
        defaults=config.defaults,
        zone_mapping=config.zone_mapping,
        ignore_modes=config.ignore_modes,
        tour_aggregation=config.tour_aggregation,
        lookups=trip_lookups,
        trip_lookups=trip_lookups,
        tour_lookups=tour_lookups,
        segment_validations=segment_validations,
    )


def _prepare_dimensions(config: ExplicitConfig) -> dict[str, DimensionConfig]:
    dimensions = {name: dim.model_copy(deep=True) for name, dim in config.dimensions.items()}
    period_dimension = dimensions.get("PERIOD")
    for name, dimension in dimensions.items():
        if name != "PERIOD" and dimension.values_from_network_los:
            raise ValueError(
                f"dimensions.{name}.values_from_network_los is only supported for PERIOD."
            )
    if period_dimension is None or not period_dimension.values_from_network_los:
        return dimensions
    project = config.project
    if project is None or project.network_los_file is None:
        raise ValueError(
            "dimensions.PERIOD.values_from_network_los requires project.network_los_file."
        )
    mapping = load_network_los_period_mapping(project.network_los_file)
    merged_values = dict(mapping)
    merged_values.update(period_dimension.values)
    dimensions["PERIOD"] = period_dimension.model_copy(update={"values": merged_values})
    return dimensions


def _merge_context(parent: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    context = dict(parent)
    defaults = block.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict):
            raise ValueError("defaults blocks must be mappings.")
        context = _merge_context(context, defaults)
    if "origin" in block:
        context["origin"] = str(block["origin"])
    if "destination" in block:
        context["destination"] = str(block["destination"])
    if "output_prefix" in block:
        context["output_prefix"] = str(block["output_prefix"])
    if "missing_matrix_policy" in block:
        context["missing_matrix_policy"] = str(block["missing_matrix_policy"])
    if "missing_od_policy" in block:
        context["missing_od_policy"] = str(block["missing_od_policy"])
    if "sentinel_values" in block:
        sentinel_values = block["sentinel_values"]
        if sentinel_values in (None, []):
            context["sentinel_values"] = []
        elif not isinstance(sentinel_values, list):
            raise ValueError("sentinel_values must be a list.")
        else:
            context["sentinel_values"] = [float(value) for value in sentinel_values]
    if "when" in block:
        when = block["when"]
        if not isinstance(when, dict):
            raise ValueError("when must be a mapping.")
        context["when"] = _merge_when(context.get("when", {}), when)
    if "dimensions" in block:
        context["dimensions"] = _merge_dimensions(context.get("dimensions", {}), block["dimensions"])
    return context


def _merge_when(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        merged[str(key)] = value
    return merged


def _merge_dimensions(base: dict[str, DimensionConfig], override: Any) -> dict[str, DimensionConfig]:
    if override is None:
        return dict(base)
    if not isinstance(override, dict):
        raise ValueError("dimensions must be a mapping.")
    merged = dict(base)
    for name, raw_config in override.items():
        if isinstance(raw_config, dict):
            merged[str(name)] = DimensionConfig.model_validate(raw_config)
        else:
            raise ValueError(f"Unsupported dimensions override for {name!r}.")
    return merged


def _normalize_components(
    *,
    mode_name: str,
    component_source: dict[str, Any],
    context: dict[str, Any],
    rule_prefix: str,
    activitysim: ActivitySimConfig,
    target_table: str,
    direction: str | None,
) -> list[NormalizedLookupRule]:
    lookups: list[NormalizedLookupRule] = []
    for component_name, raw_component in component_source.items():
        if component_name in RESERVED_KEYS:
            continue
        rules = _normalize_component(
            mode_name=mode_name,
            component_name=str(component_name),
            raw_component=raw_component,
            parent_context=context,
            rule_name=f"{rule_prefix}.{component_name}",
            activitysim=activitysim,
            target_table=target_table,
            direction=direction,
        )
        lookups.extend(rules)
    return lookups


def _normalize_component(
    *,
    mode_name: str,
    component_name: str,
    raw_component: Any,
    parent_context: dict[str, Any],
    rule_name: str,
    activitysim: ActivitySimConfig,
    target_table: str,
    direction: str | None,
) -> list[NormalizedLookupRule]:
    component_block = _component_block(raw_component, rule_name)
    apply_to = str(component_block.get("apply_to", "both"))
    if not _applies_to_target(apply_to, target_table):
        return []

    fallback_blocks = component_block.get("fallbacks") or []
    if not isinstance(fallback_blocks, list):
        raise ValueError(f"{rule_name}.fallbacks must be a list.")

    chain_id = rule_name
    combine_method = str(component_block.get("combine", "replace"))
    rules = [
        _build_lookup_rule(
            mode_name=mode_name,
            component_name=component_name,
            component_block=component_block,
            parent_context=parent_context,
            rule_name=rule_name,
            chain_id=chain_id,
            lookup_step_index=0,
            lookup_role="primary",
            combine_method=combine_method,
            activitysim=activitysim,
            target_table=target_table,
            direction=direction,
        )
    ]
    for index, fallback_raw in enumerate(fallback_blocks, start=1):
        fallback_block = _component_block(fallback_raw, f"{rule_name}.fallback_{index}")
        rules.append(
            _build_lookup_rule(
                mode_name=mode_name,
                component_name=component_name,
                component_block=fallback_block,
                parent_context=parent_context,
                rule_name=f"{rule_name}.fallback_{index}",
                chain_id=chain_id,
                lookup_step_index=index,
                lookup_role="fallback",
                combine_method=combine_method,
                activitysim=activitysim,
                target_table=target_table,
                direction=direction,
                output_override=str(component_block.get("output"))
                if component_block.get("output") is not None
                else None,
            )
        )
    return rules


def _component_block(raw_component: Any, rule_name: str) -> dict[str, Any]:
    if isinstance(raw_component, str):
        component_block: dict[str, Any] = {"matrix": raw_component}
    elif isinstance(raw_component, dict):
        component_block = dict(raw_component)
    else:
        raise ValueError(f"{rule_name} must be a string or mapping.")
    if "matrix" not in component_block:
        raise ValueError(f"{rule_name} requires matrix.")
    return component_block


def _applies_to_target(apply_to: str, target_table: str) -> bool:
    if apply_to not in {"trips", "tours", "both"}:
        raise ValueError(f"Unsupported apply_to value: {apply_to!r}")
    if apply_to == "both":
        return True
    return apply_to == target_table


def _build_lookup_rule(
    *,
    mode_name: str,
    component_name: str,
    component_block: dict[str, Any],
    parent_context: dict[str, Any],
    rule_name: str,
    chain_id: str,
    lookup_step_index: int,
    lookup_role: str,
    combine_method: str,
    activitysim: ActivitySimConfig,
    target_table: str,
    direction: str | None,
    output_override: str | None = None,
) -> NormalizedLookupRule:
    context = _merge_context(parent_context, component_block)
    dimensions = _dimensions_for_target(
        context["dimensions"],
        target_table=target_table,
        direction=direction,
    )
    matrix = str(component_block["matrix"])
    dimensions_used = extract_placeholders(matrix)
    output = str(output_override or component_block.get("output") or f"{context['output_prefix']}{component_name}")
    when = dict(context["when"])
    if target_table == "tours" and direction is not None:
        when = _merge_when(when, {TOUR_DIRECTION_COLUMN: direction})
    origin, destination = _resolve_lookup_columns(
        component_block=component_block,
        context=context,
        activitysim=activitysim,
        target_table=target_table,
        direction=direction,
    )
    if target_table == "tours" and direction is not None:
        output = f"{output}_{direction}"
    return NormalizedLookupRule(
        name=rule_name if direction is None else f"{rule_name}.{direction}",
        mode=mode_name,
        component=component_name,
        output=output,
        matrix=matrix,
        lookup=str(component_block.get("lookup", "od")),
        key_column=(
            str(component_block["key_column"])
            if component_block.get("key_column") is not None
            else None
        ),
        origin=origin,
        destination=destination,
        when=when,
        dimensions_used=dimensions_used,
        dimensions=dimensions,
        missing_matrix_policy=str(component_block.get("missing_matrix_policy", context["missing_matrix_policy"])),
        missing_od_policy=str(component_block.get("missing_od_policy", context["missing_od_policy"])),
        sentinel_values=list(context.get("sentinel_values", [])),
        combine_method=combine_method,
        lookup_chain_id=chain_id if direction is None else f"{chain_id}.{direction}",
        lookup_step_index=lookup_step_index,
        lookup_role=lookup_role,
        target_table=target_table,
        direction=direction,
    )


def _dimensions_for_target(
    dimensions: dict[str, DimensionConfig],
    *,
    target_table: str,
    direction: str | None,
) -> dict[str, ResolvedDimensionConfig]:
    resolved: dict[str, ResolvedDimensionConfig] = {}
    for name, dimension in dimensions.items():
        resolved[name] = ResolvedDimensionConfig(
            source_columns=dimension.source_columns,
            resolved_source_column=_dimension_source_column(
                dimension,
                target_table=target_table,
                direction=direction,
            ),
            values_from_network_los=dimension.values_from_network_los,
            values=dict(dimension.values),
        )
    return resolved


def _dimension_source_column(
    dimension: DimensionConfig,
    *,
    target_table: str,
    direction: str | None,
) -> str:
    if target_table == "trips":
        return dimension.source_columns.trip_source_column
    if direction == "inbound":
        return dimension.source_columns.inbound_tour_source_column
    return dimension.source_columns.outbound_tour_source_column


def _resolve_lookup_columns(
    *,
    component_block: dict[str, Any],
    context: dict[str, Any],
    activitysim: ActivitySimConfig,
    target_table: str,
    direction: str | None,
) -> tuple[str, str]:
    return (
        str(component_block.get("origin", context["origin"])),
        str(component_block.get("destination", context["destination"])),
    )
