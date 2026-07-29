"""Prepare-step and run-entry normalization."""

from __future__ import annotations

import hashlib
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
from .models import (
    Config,
    PrepareNonMotorizedDistanceSkimSettings,
    PrepareTimePeriodsSettings,
    PrepareVotBinsSettings,
)
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


def normalize_prepare_time_periods(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> PrepareTimePeriodsSettings:
    if raw_value in (None, {}):
        return PrepareTimePeriodsSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    network_los_raw = raw_value.get("network_los_file")
    if not isinstance(network_los_raw, str) or not network_los_raw.strip():
        raise ValueError(f"{field_name}.network_los_file must be a non-empty path string.")
    network_los_path = Path(network_los_raw.strip()).expanduser()
    if not network_los_path.is_absolute():
        network_los_path = (config_dir / network_los_path).resolve()
    else:
        network_los_path = network_los_path.resolve()
    if not network_los_path.exists():
        raise ValueError(
            f"{field_name}.network_los_file does not exist: {network_los_path}"
        )
    if not network_los_path.is_file():
        raise ValueError(
            f"{field_name}.network_los_file must point to a file: {network_los_path}"
        )

    def _column(name: str, default: str) -> str:
        raw_column = raw_value.get(name, default)
        if not isinstance(raw_column, str) or not raw_column.strip():
            raise ValueError(f"{field_name}.{name} must be a non-empty string.")
        return raw_column.strip()

    return PrepareTimePeriodsSettings(
        enabled=True,
        network_los_file=str(network_los_path),
        network_los_digest=hashlib.sha256(network_los_path.read_bytes()).hexdigest(),
        trip_period_number_column=_column("trip_period_number_column", "depart"),
        tour_start_period_number_column=_column(
            "tour_start_period_number_column", "start"
        ),
        tour_end_period_number_column=_column("tour_end_period_number_column", "end"),
    )


def normalize_prepare_non_motorized_distance_skim(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> PrepareNonMotorizedDistanceSkimSettings:
    if raw_value in (None, {}):
        return PrepareNonMotorizedDistanceSkimSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    file_raw = raw_value.get("file")
    if not isinstance(file_raw, str) or not file_raw.strip():
        raise ValueError(f"{field_name}.file must be a non-empty path string.")
    path = Path(file_raw.strip()).expanduser()
    if not path.is_absolute():
        path = (config_dir / path).resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise ValueError(f"{field_name}.file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"{field_name}.file must point to a file: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        source_type = "csv"
    elif suffix in {".omx", ".h5", ".hdf5"}:
        source_type = "omx"
    else:
        raise ValueError(
            f"{field_name}.file must end with '.csv', '.omx', '.h5', or '.hdf5'."
        )

    matrix_raw = raw_value.get("matrix")
    matrix = None if matrix_raw is None else str(matrix_raw).strip()
    if matrix == "":
        matrix = None

    if source_type == "omx" and matrix is None:
        raise ValueError(f"{field_name}.matrix is required for OMX/HDF5 files.")

    value_column = "DISTWALK"
    if source_type == "csv" and matrix is not None:
        prefix = f"{path.stem}__"
        value_column = matrix[len(prefix) :] if matrix.startswith(prefix) else matrix

    return PrepareNonMotorizedDistanceSkimSettings(
        enabled=True,
        file=str(path),
        file_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        matrix=matrix,
        source_type=source_type,
        value_column=value_column,
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


def normalize_summary_table_map(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> dict[str, str]:
    if raw_value is None:
        raw_value = {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    normalized: dict[str, str] = {}
    for raw_key, raw_path in raw_value.items():
        key = str(raw_key)
        if not key.strip():
            raise ValueError(f"{field_name} contains an empty summary id.")
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
        if "summary_table_map" in raw_entry:
            normalized_entry["summary_table_map"] = normalize_summary_table_map(
                raw_entry.get("summary_table_map"),
                field_name=f"{field_name}[{index}].summary_table_map",
                config_dir=config_dir,
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
