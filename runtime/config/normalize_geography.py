"""Geography mapping and aggregation normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from .models import GeographyAggregationDefinition, GeographyAggregationSettings


def normalize_geography_zone_id(
    raw_value,
    *,
    field_name: str,
) -> int:
    if isinstance(raw_value, bool):
        raise ValueError(f"{field_name} must be an integer zone id.")
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        if raw_value.is_integer():
            return int(raw_value)
        raise ValueError(f"{field_name} must be an integer zone id.")
    token = str(raw_value).strip()
    if not token:
        raise ValueError(f"{field_name} must be a non-empty zone id.")
    try:
        return int(token)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer zone id.") from exc


def normalize_geography_lookup_rows(
    rows: list[tuple[int, str]],
    *,
    field_name: str,
) -> tuple[tuple[int, str], ...]:
    if not rows:
        raise ValueError(f"{field_name} resolved to no geography mappings.")

    seen_zone_labels: dict[int, str] = {}
    normalized: list[tuple[int, str]] = []
    for zone_id, geography_label in rows:
        prior = seen_zone_labels.get(zone_id)
        if prior is not None and prior != geography_label:
            raise ValueError(
                f"{field_name} assigns zone id {zone_id} to multiple geography labels."
            )
        if prior is None:
            seen_zone_labels[zone_id] = geography_label
            normalized.append((zone_id, geography_label))
    normalized.sort(key=lambda item: (item[0], item[1]))
    return tuple(normalized)


def normalize_inline_geography_mapping(
    raw_value,
    *,
    field_name: str,
) -> tuple[tuple[int, str], ...]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    rows: list[tuple[int, str]] = []
    for raw_label, raw_zone_ids in raw_value.items():
        geography_label = str(raw_label).strip()
        if not geography_label:
            raise ValueError(f"{field_name} contains a blank geography label.")
        zone_values = raw_zone_ids if isinstance(raw_zone_ids, list) else [raw_zone_ids]
        if not zone_values:
            raise ValueError(f"{field_name}.{geography_label} must list at least one zone id.")
        for idx, zone_id in enumerate(zone_values):
            rows.append(
                (
                    normalize_geography_zone_id(
                        zone_id,
                        field_name=f"{field_name}.{geography_label}[{idx}]",
                    ),
                    geography_label,
                )
            )
    return normalize_geography_lookup_rows(rows, field_name=field_name)


def normalize_file_geography_mapping(
    raw_value: dict[str, Any],
    *,
    field_name: str,
    config_dir: Path,
) -> tuple[str, str, str, tuple[tuple[int, str], ...]]:
    file_raw = raw_value.get("file")
    zone_id_col = str(raw_value.get("zone_id_col", "")).strip()
    geography_col = str(raw_value.get("geography_col", "")).strip()
    if not isinstance(file_raw, str) or not file_raw.strip():
        raise ValueError(f"{field_name}.file must be a non-empty string.")
    if not zone_id_col:
        raise ValueError(f"{field_name}.zone_id_col is required with file-based mappings.")
    if not geography_col:
        raise ValueError(f"{field_name}.geography_col is required with file-based mappings.")

    resolved_path = Path(file_raw).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = (config_dir / resolved_path).resolve()
    if not resolved_path.exists():
        raise ValueError(f"{field_name}.file does not exist: {resolved_path}")

    lookup = pl.read_csv(resolved_path)
    required_columns = {zone_id_col, geography_col}
    missing_columns = sorted(required_columns - set(lookup.columns))
    if missing_columns:
        raise ValueError(
            f"{field_name}.file is missing required columns: {', '.join(missing_columns)}"
        )

    rows: list[tuple[int, str]] = []
    for idx, row in enumerate(
        lookup.select([zone_id_col, geography_col]).iter_rows(named=True)
    ):
        geography_label = (
            str(row[geography_col]).strip() if row[geography_col] is not None else ""
        )
        if not geography_label:
            raise ValueError(
                f"{field_name}.file contains a blank geography label at row {idx + 1}."
            )
        rows.append(
            (
                normalize_geography_zone_id(
                    row[zone_id_col],
                    field_name=f"{field_name}.file row {idx + 1} zone id",
                ),
                geography_label,
            )
        )

    return (
        str(resolved_path),
        zone_id_col,
        geography_col,
        normalize_geography_lookup_rows(rows, field_name=f"{field_name}.file"),
    )


def normalize_geography_aggregations(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> GeographyAggregationSettings:
    if raw_value is None:
        return GeographyAggregationSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    enabled = raw_value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"{field_name}.enabled must be true or false when provided.")

    aggregations_raw = raw_value.get("aggregations")
    if aggregations_raw is None:
        return GeographyAggregationSettings(enabled=enabled)
    if not isinstance(aggregations_raw, dict):
        raise ValueError(f"{field_name}.aggregations must be a mapping when provided.")

    aggregations: list[GeographyAggregationDefinition] = []
    for raw_name, raw_definition in aggregations_raw.items():
        name = str(raw_name).strip()
        entry_name = f"{field_name}.aggregations.{name or raw_name}"
        if not name:
            raise ValueError(f"{field_name}.aggregations contains a blank aggregation name.")
        if not isinstance(raw_definition, dict):
            raise ValueError(f"{entry_name} must be a mapping.")

        source_zone_system = str(raw_definition.get("source_zone_system", "")).strip().lower()
        if source_zone_system not in {"maz", "taz"}:
            raise ValueError(f"{entry_name}.source_zone_system must be 'maz' or 'taz'.")

        has_inline_mapping = "mapping" in raw_definition
        has_file_mapping = "file" in raw_definition
        if has_inline_mapping == has_file_mapping:
            raise ValueError(f"{entry_name} must define exactly one of 'mapping' or 'file'.")

        if has_inline_mapping:
            aggregations.append(
                GeographyAggregationDefinition(
                    name=name,
                    source_zone_system=source_zone_system,
                    lookup_rows=normalize_inline_geography_mapping(
                        raw_definition["mapping"],
                        field_name=f"{entry_name}.mapping",
                    ),
                )
            )
            continue

        file_path, zone_id_col, geography_col, lookup_rows = normalize_file_geography_mapping(
            raw_definition,
            field_name=entry_name,
            config_dir=config_dir,
        )
        aggregations.append(
            GeographyAggregationDefinition(
                name=name,
                source_zone_system=source_zone_system,
                lookup_rows=lookup_rows,
                file=file_path,
                zone_id_col=zone_id_col,
                geography_col=geography_col,
            )
        )

    aggregations.sort(key=lambda entry: entry.name)
    return GeographyAggregationSettings(enabled=enabled, aggregations=tuple(aggregations))
