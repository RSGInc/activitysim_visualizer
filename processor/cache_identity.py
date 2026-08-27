"""Shared helpers for stable processor cache keys and run identities."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


def slugify(value: str) -> str:
    """Return a stable, filesystem-safe slug for a run label."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-_.").lower()
    return slug or "run"


def build_run_keys(labels: list[str]) -> list[str]:
    """Return stable run keys, adding numeric suffixes for collisions."""
    bases = [slugify(label) for label in labels]
    counts = Counter(bases)
    seen: dict[str, int] = {}
    keys: list[str] = []
    for base in bases:
        seen[base] = seen.get(base, 0) + 1
        if counts[base] == 1:
            keys.append(base)
        else:
            keys.append(f"{base}-{seen[base]}")
    return keys


def build_run_fingerprint(
    *,
    label: str,
    run_dir: str | None,
    skim_file: str | None,
    raw_file_identities: dict[str, dict[str, object] | None] | None = None,
    skim_file_identity: dict[str, object] | None = None,
    skimjoin: dict[str, object] | None = None,
    file_map: dict[str, str] | None = None,
    fallback_file_map: dict[str, str] | None = None,
    hh_weight_col: str | None,
    person_weight_col: str | None,
    trip_weight_col: str | None,
    day_weight_col: str | None = "day_weight",
) -> dict[str, object]:
    """Return the run inputs that determine whether cache data is reusable."""
    return {
        "label": label,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "skim_file": str(skim_file) if skim_file is not None else None,
        "skim_file_identity": skim_file_identity,
        "raw_file_identities": {
            key: value
            for key, value in sorted((raw_file_identities or {}).items())
        },
        "skimjoin": dict(sorted((skimjoin or {}).items())) if skimjoin else None,
        "file_map": dict(sorted((file_map or {}).items())),
        "fallback_file_map": dict(sorted((fallback_file_map or {}).items())),
        "hh_weight_col": hh_weight_col,
        "person_weight_col": person_weight_col,
        "trip_weight_col": trip_weight_col,
        "day_weight_col": day_weight_col,
    }


def file_identity(path: str | Path) -> dict[str, object]:
    """Return a portable identity for an external input file."""
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def optional_file_identity(path: str | Path | None) -> dict[str, object] | None:
    """Return a file identity when the configured input currently exists."""
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        return None
    return file_identity(resolved)


__all__ = [
    "build_run_fingerprint",
    "build_run_keys",
    "file_identity",
    "optional_file_identity",
    "slugify",
]
