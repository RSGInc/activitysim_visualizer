"""Segmentation config normalization."""

from __future__ import annotations

import json
from pathlib import Path
import re

import polars as pl

from .models import (
    CsvLookupSegmentationSource,
    DashboardSegmentationSettings,
    PreparedColumnSegmentationSource,
    SegmentSpec,
    SegmentationDefinition,
    SegmentationSettings,
    SegmentationSourceConfig,
)


def normalize_segment_values(
    raw_value,
    *,
    field_name: str,
) -> tuple[object, ...]:
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    if not values:
        raise ValueError(f"{field_name} must define at least one value.")
    return tuple(values)


def normalize_segmentation_source(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> SegmentationSourceConfig:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    source_type = str(raw_value.get("type", "prepared_column")).strip().lower()
    if source_type == "prepared_column":
        column = str(raw_value.get("column", "")).strip()
        if not column:
            raise ValueError(f"{field_name}.column is required.")
        source_table_raw = raw_value.get("source_table")
        source_table = str(source_table_raw).strip() if source_table_raw is not None else None
        if source_table == "":
            source_table = None
        if source_table is not None and source_table not in {
            "hh",
            "per",
            "tours",
            "trips",
            "land_use",
        }:
            raise ValueError(
                f"{field_name}.source_table must be one of hh, per, tours, trips, land_use."
            )
        return PreparedColumnSegmentationSource(column=column, source_table=source_table)

    if source_type != "csv_lookup":
        raise ValueError(f"{field_name}.type must be 'prepared_column' or 'csv_lookup'.")

    file_raw = raw_value.get("file")
    if not isinstance(file_raw, str) or not file_raw.strip():
        raise ValueError(f"{field_name}.file must be a non-empty string.")
    join_raw = raw_value.get("join")
    if not isinstance(join_raw, dict):
        raise ValueError(f"{field_name}.join must be a mapping.")
    join_source_table = str(join_raw.get("source_table", "")).strip()
    join_source_key_column = str(join_raw.get("source_key_column", "")).strip()
    csv_key_column = str(join_raw.get("csv_key_column", "")).strip()
    segment_value_column = str(raw_value.get("segment_value_column", "")).strip()
    if join_source_table not in {"hh", "per", "tours", "trips", "land_use"}:
        raise ValueError(
            f"{field_name}.join.source_table must be one of hh, per, tours, trips, land_use."
        )
    if not join_source_key_column:
        raise ValueError(f"{field_name}.join.source_key_column is required.")
    if not csv_key_column:
        raise ValueError(f"{field_name}.join.csv_key_column is required.")
    if not segment_value_column:
        raise ValueError(f"{field_name}.segment_value_column is required.")

    resolved_path = Path(file_raw).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = (config_dir / resolved_path).resolve()
    if not resolved_path.exists():
        raise ValueError(f"{field_name}.file does not exist: {resolved_path}")

    lookup = pl.read_csv(resolved_path)
    required_columns = {csv_key_column, segment_value_column}
    missing_columns = sorted(required_columns - set(lookup.columns))
    if missing_columns:
        raise ValueError(
            f"{field_name}.file is missing required columns: {', '.join(missing_columns)}"
        )

    seen_key_to_value: dict[str, str] = {}
    normalized_rows: list[tuple[str, str]] = []
    for idx, row in enumerate(
        lookup.select([csv_key_column, segment_value_column]).iter_rows(named=True)
    ):
        key = "" if row[csv_key_column] is None else str(row[csv_key_column]).strip()
        if not key:
            raise ValueError(f"{field_name}.file contains a blank join key at row {idx + 1}.")
        value = (
            ""
            if row[segment_value_column] is None
            else str(row[segment_value_column]).strip()
        )
        if not value:
            raise ValueError(
                f"{field_name}.file contains a blank segment value at row {idx + 1}."
            )
        prior = seen_key_to_value.get(key)
        if prior is not None and prior != value:
            raise ValueError(
                f"{field_name}.file assigns key {key!r} to multiple segment values."
            )
        if prior is None:
            seen_key_to_value[key] = value
            normalized_rows.append((key, value))

    if not normalized_rows:
        raise ValueError(f"{field_name}.file resolved to no lookup rows.")

    normalized_rows.sort(key=lambda item: (item[0], item[1]))
    return CsvLookupSegmentationSource(
        file=str(resolved_path),
        join_source_table=join_source_table,
        join_source_key_column=join_source_key_column,
        csv_key_column=csv_key_column,
        segment_value_column=segment_value_column,
        lookup_rows=tuple(normalized_rows),
    )


def normalize_segmentation(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> SegmentationSettings:
    if raw_value is None:
        return SegmentationSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    enabled = raw_value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"{field_name}.enabled must be true or false.")
    if not enabled:
        return SegmentationSettings(enabled=False)

    dashboard_raw = raw_value.get("dashboard", {})
    if dashboard_raw is None:
        dashboard_raw = {}
    if not isinstance(dashboard_raw, dict):
        raise ValueError(f"{field_name}.dashboard must be a mapping when provided.")
    dashboard_segmentation_type = dashboard_raw.get("segmentation_type")
    if dashboard_segmentation_type is not None:
        dashboard_segmentation_type = str(dashboard_segmentation_type).strip().lower()
        if not dashboard_segmentation_type:
            dashboard_segmentation_type = None
    dashboard_visibility = str(
        dashboard_raw.get("visibility", "full_and_segments")
    ).strip().lower()
    if dashboard_visibility not in {"full_only", "segments_only", "full_and_segments"}:
        raise ValueError(
            f"{field_name}.dashboard.visibility must be one of full_only, segments_only, or full_and_segments."
        )

    definitions_raw = raw_value.get("definitions")
    if not isinstance(definitions_raw, dict) or not definitions_raw:
        raise ValueError(f"{field_name}.definitions must be a non-empty mapping when enabled.")

    normalized_definitions: list[SegmentationDefinition] = []
    seen_definition_names: set[str] = set()
    for raw_name, raw_definition in definitions_raw.items():
        definition_name = str(raw_name).strip().lower()
        entry_name = f"{field_name}.definitions.{raw_name}"
        if not definition_name:
            raise ValueError(f"{field_name}.definitions contains a blank name.")
        if definition_name != str(raw_name).strip():
            raise ValueError(f"{entry_name} name must already be normalized and lowercase.")
        if (
            re.sub(r"[^A-Za-z0-9._-]+", "-", definition_name)
            .strip("-_.")
            .lower()
            != definition_name
        ):
            raise ValueError(f"{entry_name} name must be path-safe.")
        if definition_name in seen_definition_names:
            raise ValueError(f"{entry_name} name must be unique.")
        seen_definition_names.add(definition_name)
        if not isinstance(raw_definition, dict):
            raise ValueError(f"{entry_name} must be a mapping.")

        include_full = raw_definition.get("include_full", True)
        if not isinstance(include_full, bool):
            raise ValueError(f"{entry_name}.include_full must be true or false.")
        persist_segmented_prepared_tables = raw_definition.get(
            "persist_segmented_prepared_tables", False
        )
        if not isinstance(persist_segmented_prepared_tables, bool):
            raise ValueError(
                f"{entry_name}.persist_segmented_prepared_tables must be true or false."
            )
        allow_overlapping = raw_definition.get("allow_overlapping", False)
        if not isinstance(allow_overlapping, bool):
            raise ValueError(f"{entry_name}.allow_overlapping must be true or false.")

        on_empty_segment = str(raw_definition.get("on_empty_segment", "warn")).strip().lower()
        if on_empty_segment not in {"error", "warn", "skip"}:
            raise ValueError(
                f"{entry_name}.on_empty_segment must be one of error, warn, or skip."
            )

        source = normalize_segmentation_source(
            raw_definition.get("source"),
            field_name=f"{entry_name}.source",
            config_dir=config_dir,
        )

        segments_raw = raw_definition.get("segments")
        if not isinstance(segments_raw, list) or not segments_raw:
            raise ValueError(f"{entry_name}.segments must be a non-empty list.")

        normalized_segments: list[SegmentSpec] = []
        seen_segment_ids: set[str] = set()
        seen_values: dict[str, str] = {}
        for idx, raw_segment in enumerate(segments_raw):
            segment_name = f"{entry_name}.segments[{idx}]"
            if not isinstance(raw_segment, dict):
                raise ValueError(f"{segment_name} must be a mapping.")
            raw_segment_id = str(raw_segment.get("id", "")).strip()
            if not raw_segment_id:
                raise ValueError(f"{segment_name}.id is required.")
            normalized_id = raw_segment_id.lower()
            if normalized_id != raw_segment_id:
                raise ValueError(f"{segment_name}.id must already be normalized and lowercase.")
            if (
                re.sub(r"[^A-Za-z0-9._-]+", "-", normalized_id)
                .strip("-_.")
                .lower()
                != normalized_id
            ):
                raise ValueError(f"{segment_name}.id must be path-safe.")
            if normalized_id in seen_segment_ids:
                raise ValueError(f"{segment_name}.id must be unique.")
            seen_segment_ids.add(normalized_id)
            label = str(raw_segment.get("label", "")).strip()
            if not label:
                raise ValueError(f"{segment_name}.label is required.")
            values = normalize_segment_values(
                raw_segment.get("values"),
                field_name=f"{segment_name}.values",
            )
            if not allow_overlapping:
                for raw_value_token in values:
                    overlap_key = json.dumps(raw_value_token, sort_keys=True, default=str)
                    prior_segment = seen_values.get(overlap_key)
                    if prior_segment is not None:
                        raise ValueError(
                            f"{segment_name}.values overlaps with segment {prior_segment!r} while allow_overlapping is false."
                        )
                    seen_values[overlap_key] = normalized_id
            normalized_segments.append(
                SegmentSpec(id=normalized_id, label=label, values=values)
            )

        normalized_definitions.append(
            SegmentationDefinition(
                name=definition_name,
                include_full=include_full,
                persist_segmented_prepared_tables=persist_segmented_prepared_tables,
                allow_overlapping=allow_overlapping,
                on_empty_segment=on_empty_segment,
                source=source,
                segments=tuple(normalized_segments),
            )
        )

    normalized_definitions.sort(key=lambda definition: definition.name)
    available_definition_names = {definition.name for definition in normalized_definitions}
    if dashboard_segmentation_type is None:
        dashboard_segmentation_type = normalized_definitions[0].name
    if dashboard_segmentation_type not in available_definition_names:
        raise ValueError(
            f"{field_name}.dashboard.segmentation_type must name one configured definition."
        )

    return SegmentationSettings(
        enabled=enabled,
        dashboard=DashboardSegmentationSettings(
            segmentation_type=dashboard_segmentation_type,
            visibility=dashboard_visibility,
        ),
        definitions=tuple(normalized_definitions),
    )
