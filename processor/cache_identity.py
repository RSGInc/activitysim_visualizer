"""Shared helpers for stable processor cache keys and run identities."""

from __future__ import annotations

from collections import Counter
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
    hh_weight_col: str | None,
    person_weight_col: str | None,
    trip_weight_col: str | None,
) -> dict[str, object]:
    """Return the run inputs that determine whether cache data is reusable."""
    return {
        "label": label,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "skim_file": str(skim_file) if skim_file is not None else None,
        "hh_weight_col": hh_weight_col,
        "person_weight_col": person_weight_col,
        "trip_weight_col": trip_weight_col,
    }


__all__ = ["build_run_fingerprint", "build_run_keys", "slugify"]
