from __future__ import annotations

import re
from typing import Any

from processor.skimjoin.config.network_los import load_network_los_period_mapping
from processor.skimjoin.config.schema import (
    DimensionConfig,
    ExplicitConfig,
    NormalizedConfig,
    NormalizedLookupRule,
)


PLACEHOLDER_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")
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
    "skip",
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
    }
    lookups: list[NormalizedLookupRule] = []
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
                lookups.extend(
                    _normalize_components(
                        mode_name=mode_name,
                        component_source=segment_block,
                        context=segment_context,
                        rule_prefix=f"{mode_name}.{segment_key}",
                    )
                )
        else:
            lookups.extend(
                _normalize_components(
                    mode_name=mode_name,
                    component_source=raw_mode_block,
                    context=mode_context,
                    rule_prefix=mode_name,
                )
            )

    return NormalizedConfig(
        skim_files=config.skim_files,
        activitysim=config.activitysim,
        defaults=config.defaults,
        zone_mapping=config.zone_mapping,
        ignore_modes=config.ignore_modes,
        tour_aggregation=config.tour_aggregation,
        lookups=lookups,
        segment_validations=segment_validations,
    )


def _prepare_dimensions(config: ExplicitConfig) -> dict[str, DimensionConfig]:
    dimensions = {name: dim.model_copy(deep=True) for name, dim in config.dimensions.items()}
    project = config.project
    if project is None or project.network_los_file is None:
        return dimensions
    period_dimension = dimensions.get("PERIOD")
    if period_dimension is None or period_dimension.values:
        return dimensions
    mapping = load_network_los_period_mapping(project.network_los_file)
    dimensions["PERIOD"] = period_dimension.model_copy(update={"values": mapping})
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
        if isinstance(raw_config, str):
            merged[str(name)] = DimensionConfig(source_column=raw_config)
        elif isinstance(raw_config, dict):
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
) -> list[NormalizedLookupRule]:
    lookups: list[NormalizedLookupRule] = []
    for component_name, raw_component in component_source.items():
        if component_name in RESERVED_KEYS:
            continue
        rule = _normalize_component(
            mode_name=mode_name,
            component_name=str(component_name),
            raw_component=raw_component,
            parent_context=context,
            rule_name=f"{rule_prefix}.{component_name}",
        )
        lookups.append(rule)
    return lookups


def _normalize_component(
    *,
    mode_name: str,
    component_name: str,
    raw_component: Any,
    parent_context: dict[str, Any],
    rule_name: str,
) -> NormalizedLookupRule:
    if isinstance(raw_component, str):
        component_block: dict[str, Any] = {"matrix": raw_component}
    elif isinstance(raw_component, dict):
        component_block = dict(raw_component)
    else:
        raise ValueError(f"{rule_name} must be a string or mapping.")
    if "matrix" not in component_block:
        raise ValueError(f"{rule_name} requires matrix.")

    context = _merge_context(parent_context, component_block)
    matrix = str(component_block["matrix"])
    dimensions_used = extract_placeholders(matrix)
    output = str(component_block.get("output") or f"{context['output_prefix']}{component_name}")
    return NormalizedLookupRule(
        name=rule_name,
        mode=mode_name,
        component=component_name,
        output=output,
        matrix=matrix,
        origin=str(component_block.get("origin", context["origin"])),
        destination=str(component_block.get("destination", context["destination"])),
        when=context["when"],
        dimensions_used=dimensions_used,
        dimensions=context["dimensions"],
        missing_matrix_policy=str(component_block.get("missing_matrix_policy", context["missing_matrix_policy"])),
        missing_od_policy=str(component_block.get("missing_od_policy", context["missing_od_policy"])),
    )
