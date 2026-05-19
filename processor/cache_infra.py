"""Shared low-level cache infrastructure helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import polars as pl

MANIFEST_FILENAME = "manifest.json"
EMPTY_SENTINEL_COLUMN = "__empty__"


def empty_sentinel_frame() -> pl.DataFrame:
    """Return the conventional single-column empty sentinel frame."""
    return pl.DataFrame({EMPTY_SENTINEL_COLUMN: []})


def is_empty_sentinel_frame(table: pl.DataFrame) -> bool:
    """Return whether ``table`` is the conventional empty sentinel frame."""
    return table.columns == [EMPTY_SENTINEL_COLUMN]


def read_manifest(
    cache_dir: str | Path,
    *,
    error_cls: type[Exception],
) -> dict[str, object]:
    """Read one cache manifest, raising the provided domain error on failure."""
    cache_dir = Path(cache_dir)
    manifest_path = cache_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise error_cls(f"Missing manifest: {manifest_path}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise error_cls(f"Invalid manifest JSON in {manifest_path}: {exc}") from exc


def write_manifest(cache_dir: str | Path, manifest: dict[str, object]) -> None:
    """Write one cache manifest in the repo-standard JSON format."""
    cache_dir = Path(cache_dir)
    (cache_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def validate_schema_version(
    *,
    cache_dir: str | Path,
    manifest: dict[str, object],
    supported_versions: set[int],
    error_factory: Callable[[str], Exception],
) -> int:
    """Validate and return the cache schema version from a manifest."""
    cache_dir = Path(cache_dir)
    schema_version = int(manifest.get("schema_version", 0))
    if schema_version not in supported_versions:
        raise error_factory(
            f"Unsupported cache schema_version {schema_version} in {cache_dir}"
        )
    return schema_version


def discover_manifest_cache_dirs(root: str | Path) -> list[Path]:
    """Return child cache directories that contain a repo-standard manifest."""
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        [
            child
            for child in root.iterdir()
            if child.is_dir() and (child / MANIFEST_FILENAME).exists()
        ],
        key=lambda path: path.name,
    )


__all__ = [
    "EMPTY_SENTINEL_COLUMN",
    "MANIFEST_FILENAME",
    "discover_manifest_cache_dirs",
    "empty_sentinel_frame",
    "is_empty_sentinel_frame",
    "read_manifest",
    "validate_schema_version",
    "write_manifest",
]
