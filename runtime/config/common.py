"""Shared normalization helpers used across config domains."""

from __future__ import annotations

from pathlib import Path
import re


def normalize_run_selector_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or str(value).strip().lower()


def normalize_optional_bool(raw_value, *, field_name: str) -> bool | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    raise ValueError(f"{field_name} must be true or false when provided.")


def normalize_string_list(raw_value, *, field_name: str) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip()
        if token and token not in normalized:
            normalized.append(token)
    return normalized


def normalize_optional_path_string(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    resolved_path = Path(raw_value).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = (config_dir / resolved_path).resolve()
    return str(resolved_path)


def normalize_column_aliases(
    raw_value,
    *,
    field_name: str,
    default: list[str],
    allow_none: bool = False,
) -> list[str] | None:
    if raw_value is None:
        return None if allow_none else list(default)

    if isinstance(raw_value, str):
        candidates = [raw_value]
    elif isinstance(raw_value, list):
        candidates = raw_value
    else:
        raise ValueError(f"{field_name} must be a string or list of strings.")

    normalized: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip()
        if not token or token in normalized:
            continue
        normalized.append(token)

    if not normalized:
        if allow_none:
            return None
        raise ValueError(f"{field_name} resolved to no values.")
    return normalized


def normalize_label_mapping(
    raw_value,
    *,
    field_name: str,
) -> dict[str, str] | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")
    normalized = {str(key): str(value) for key, value in raw_value.items()}
    return normalized or None
