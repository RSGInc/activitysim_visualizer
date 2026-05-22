"""Prepare-step and run-entry normalization."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .common import (
    normalize_column_aliases,
    normalize_optional_path_string,
    normalize_run_selector_key,
    normalize_string_list,
)
from .constants import (
    FILE_MAPPING_DEFAULTS,
    OPTIONAL_PREPARED_TABLE_IDS,
    PREPARED_TABLE_MAP_KEYS,
)
from .models import Config, PrepareVotBinsSettings
from .normalize_skimjoin import normalize_run_skimjoin_overrides, resolve_run_skimjoin_settings


def normalize_prepare_vot_bins(
    raw_value,
    *,
    field_name: str,
) -> PrepareVotBinsSettings:
    if raw_value in (None, {}):
        return PrepareVotBinsSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    output_column = str(raw_value.get("output_column", "vot_bin")).strip()
    source_column = str(raw_value.get("source_column", "income_segment")).strip()
    if not output_column:
        raise ValueError(f"{field_name}.output_column must be a non-empty string.")
    if not source_column:
        raise ValueError(f"{field_name}.source_column must be a non-empty string.")

    fallback_raw = raw_value.get("fallback_value")
    fallback_value = None if fallback_raw is None else str(fallback_raw)

    mappings_raw = raw_value.get("mappings", {})
    if mappings_raw in (None, {}):
        return PrepareVotBinsSettings(
            enabled=False,
            source_column=source_column,
            output_column=output_column,
            fallback_value=fallback_value,
        )
    if not isinstance(mappings_raw, dict):
        raise ValueError(f"{field_name}.mappings must be a mapping.")

    mappings: dict[str, dict[str, str]] = {}
    for run_name, raw_mapping in mappings_raw.items():
        if not isinstance(raw_mapping, dict):
            raise ValueError(f"{field_name}.mappings.{run_name} must be a mapping.")
        normalized_run_name = normalize_run_selector_key(str(run_name))
        if normalized_run_name in mappings:
            raise ValueError(
                f"{field_name}.mappings contains duplicate run key {run_name!r} after normalization."
            )
        mappings[normalized_run_name] = {
            str(source_value): str(mapped_value)
            for source_value, mapped_value in raw_mapping.items()
        }

    return PrepareVotBinsSettings(
        enabled=bool(mappings),
        source_column=source_column,
        output_column=output_column,
        fallback_value=fallback_value,
        mappings=mappings,
    )


def normalize_file_mapping(
    raw_value,
    *,
    field_name: str,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    if raw_value is None:
        raw_value = {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    allowed_keys = set(FILE_MAPPING_DEFAULTS)
    invalid_keys = sorted(str(key) for key in raw_value if str(key) not in allowed_keys)
    if invalid_keys:
        raise ValueError(
            f"{field_name} contains unsupported table ids: "
            + ", ".join(repr(key) for key in invalid_keys)
        )

    normalized = dict(defaults or {})
    for raw_key, raw_path in raw_value.items():
        key = str(raw_key)
        if not isinstance(raw_path, str):
            raise ValueError(f"{field_name}.{key} must be a non-empty string.")
        token = raw_path.strip()
        if not token:
            raise ValueError(f"{field_name}.{key} must be a non-empty string.")
        normalized[key] = token
    return normalized


def normalize_fallback_file_mapping(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> dict[str, str]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    invalid_keys = sorted(
        str(key) for key in raw_value if str(key) not in OPTIONAL_PREPARED_TABLE_IDS
    )
    if invalid_keys:
        raise ValueError(
            f"{field_name} contains unsupported table ids: "
            + ", ".join(repr(key) for key in invalid_keys)
        )

    normalized: dict[str, str] = {}
    for raw_key, raw_path in raw_value.items():
        key = str(raw_key)
        if not isinstance(raw_path, str):
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        token = raw_path.strip()
        if not token:
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        suffix = Path(token).suffix.lower()
        if suffix not in {".parquet", ".csv"}:
            raise ValueError(f"{field_name}.{key} must end with '.parquet' or '.csv'.")
        resolved = Path(token).expanduser()
        if not resolved.is_absolute():
            resolved = (config_dir / resolved).resolve()
        normalized[key] = str(resolved)
    return normalized


def normalize_prepared_output_file_format(
    raw_value,
    *,
    field_name: str,
) -> str:
    if raw_value is None:
        return "parquet"
    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} must be 'parquet' or 'csv'.")
    token = raw_value.strip().lower()
    if token not in {"parquet", "csv"}:
        raise ValueError(f"{field_name} must be 'parquet' or 'csv'.")
    return token


def normalize_prepare_relationship_checks(
    raw_value,
    *,
    field_name: str,
) -> str:
    if raw_value is None:
        return "warn"
    if raw_value is False:
        return "off"
    if raw_value is True:
        raise ValueError(f"{field_name} must be 'off', 'warn', or 'error'.")
    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} must be 'off', 'warn', or 'error'.")
    token = raw_value.strip().lower()
    if token not in {"off", "warn", "error"}:
        raise ValueError(f"{field_name} must be 'off', 'warn', or 'error'.")
    return token


def normalize_prepared_table_map(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> dict[str, str]:
    if raw_value is None:
        raw_value = {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    invalid_keys = sorted(
        str(key) for key in raw_value if str(key) not in PREPARED_TABLE_MAP_KEYS
    )
    if invalid_keys:
        raise ValueError(
            f"{field_name} contains unsupported table ids: "
            + ", ".join(repr(key) for key in invalid_keys)
        )

    normalized: dict[str, str] = {}
    for raw_key, raw_path in raw_value.items():
        key = str(raw_key)
        if not isinstance(raw_path, str):
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        token = raw_path.strip()
        if not token:
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        suffix = Path(token).suffix.lower()
        if suffix not in {".parquet", ".csv"}:
            raise ValueError(f"{field_name}.{key} must end with '.parquet' or '.csv'.")
        resolved = Path(token).expanduser()
        if not resolved.is_absolute():
            resolved = (config_dir / resolved).resolve()
        normalized[key] = str(resolved)
    return normalized


def normalize_runs(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> list[dict[str, Any]]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    normalized_runs: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_value):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{field_name}[{index}] must be a mapping.")
        normalized_entry = dict(raw_entry)
        if "file_map" in raw_entry:
            normalized_entry["file_map"] = normalize_file_mapping(
                raw_entry.get("file_map"),
                field_name=f"{field_name}[{index}].file_map",
            )
        if "prepared_table_map" in raw_entry:
            normalized_entry["prepared_table_map"] = normalize_prepared_table_map(
                raw_entry.get("prepared_table_map"),
                field_name=f"{field_name}[{index}].prepared_table_map",
                config_dir=config_dir,
            )
            if "file_map" in raw_entry:
                raise ValueError(
                    f"{field_name}[{index}] cannot define both file_map and prepared_table_map."
                )
        if "skimjoin" in raw_entry:
            normalized_entry["skimjoin"] = normalize_run_skimjoin_overrides(
                raw_entry.get("skimjoin"),
                field_name=f"{field_name}[{index}].skimjoin",
                config_dir=config_dir,
            )
        normalized_runs.append(normalized_entry)
    return normalized_runs


def config_for_run(config: Config, run_entry: dict[str, Any]) -> Config:
    resolved_skimjoin = resolve_run_skimjoin_settings(config, run_entry)
    if resolved_skimjoin == config.skimjoin:
        return config
    return replace(config, skimjoin=resolved_skimjoin)
