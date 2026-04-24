"""Prepared-table cache layout, manifest handling, and load/write helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path

import polars as pl

from processor.models import RunData
from processor.prepare.availability import (
    attach_table_availability,
    table_availability,
    table_unavailable_reasons,
)
from processor.prepare.writer import write_all
from runtime.config import Config

SCHEMA_VERSION = 2
SUPPORTED_FILE_FORMATS = ("parquet", "csv")
PREPARED_TABLE_ATTRS: tuple[tuple[str, str, str], ...] = (
    ("hh", "households", "households"),
    ("per", "persons", "persons"),
    ("tours", "tours", "tours"),
    ("trips", "trips", "trips"),
    ("joint_participants", "joint_tour_participants", "joint_tour_participants"),
    ("land_use", "land_use", "land_use"),
)


class PreparedCacheError(RuntimeError):
    """Raised when a prepared cache directory is invalid or incomplete."""


@dataclass(frozen=True)
class PreparedRunCacheEntry:
    """Metadata for one written prepared-run cache directory."""

    label: str
    run_key: str
    cache_dir: Path
    manifest: dict[str, object]


def prepared_root(config: Config) -> Path:
    """Return the default prepared-table root next to the summary cache root."""
    summary_root = Path(config.summary_root)
    return summary_root.parent / "prepared_cache"


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-_.").lower()
    return slug or "run"


def build_run_keys(labels: list[str]) -> list[str]:
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
    """Return the run inputs that determine whether a prepared cache is reusable."""
    return {
        "label": label,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "skim_file": str(skim_file) if skim_file is not None else None,
        "hh_weight_col": hh_weight_col,
        "person_weight_col": person_weight_col,
        "trip_weight_col": trip_weight_col,
    }


def build_prepared_manifest_identity(
    *,
    run_key: str,
    config: Config,
    run_fingerprint: dict[str, object],
) -> dict[str, object]:
    """Return the portable prepared-cache identity used by downstream summaries."""
    return {
        "run_key": run_key,
        "prepare_config_digest": config.prepare_config_digest,
        "run_fingerprint": dict(run_fingerprint),
    }


def _table_file_map(file_format: str) -> dict[str, str]:
    return {
        table_id: f"{stem}.{file_format}"
        for _, table_id, stem in PREPARED_TABLE_ATTRS
    }


def _manifest_table_map(manifest: dict[str, object]) -> dict[str, str]:
    return {
        str(table_id): str(filename)
        for table_id, filename in dict(manifest.get("table_files", {})).items()
    }


def _read_manifest(cache_dir: Path) -> dict[str, object]:
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        raise PreparedCacheError(f"Missing manifest: {manifest_path}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PreparedCacheError(
            f"Invalid manifest JSON in {manifest_path}: {exc}"
        ) from exc


def write_prepared_run_cache(
    rd: RunData,
    config: Config,
    *,
    run_key: str,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    file_format: str = "parquet",
) -> PreparedRunCacheEntry:
    """Write one prepared run's canonical tables and manifest."""
    if file_format not in SUPPORTED_FILE_FORMATS:
        raise ValueError(
            f"Unsupported prepared table file format {file_format!r}. "
            f"Supported formats: {SUPPORTED_FILE_FORMATS}"
        )

    output_root = (
        Path(output_root) if output_root is not None else prepared_root(config)
    )
    output_root.mkdir(parents=True, exist_ok=True)

    cache_dir = output_root / run_key
    cache_dir.mkdir(parents=True, exist_ok=True)

    tables_to_write: dict[str, pl.DataFrame] = {}
    table_states = table_availability(rd)
    unavailable_reasons = table_unavailable_reasons(rd)
    for attr_name, table_id, stem in PREPARED_TABLE_ATTRS:
        table = getattr(rd, attr_name)
        state = table_states.get(table_id)
        if state is None:
            state = "empty" if table.width == 0 else "available"
        if state in {"empty", "unavailable"}:
            tables_to_write[stem] = pl.DataFrame({"__empty__": []})
        else:
            tables_to_write[stem] = table

    write_all(tables_to_write, cache_dir, file_format=file_format)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "activitysim-visualizer-prepared-cache",
        "label": rd.label,
        "run_key": run_key,
        "source_run_dir": rd.run_dir,
        "config_path": config.config_path,
        "prepare_config_digest": config.prepare_config_digest,
        "table_format": file_format,
        "table_files": _table_file_map(file_format),
        "table_states": {
            table_id: table_states.get(
                table_id,
                "empty" if getattr(rd, attr_name).width == 0 else "available",
            )
            for attr_name, table_id, _ in PREPARED_TABLE_ATTRS
        },
        "unavailable_tables": {
            table_id: unavailable_reasons[table_id]
            for _, table_id, _ in PREPARED_TABLE_ATTRS
            if table_states.get(table_id) == "unavailable"
            and table_id in unavailable_reasons
        },
        "skim_file": rd.skim_file,
        "hh_weight_col": rd.hh_weight_col,
        "person_weight_col": rd.person_weight_col,
        "trip_weight_col": rd.trip_weight_col,
        "run_fingerprint": run_fingerprint or {},
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return PreparedRunCacheEntry(
        label=rd.label,
        run_key=run_key,
        cache_dir=cache_dir,
        manifest=manifest,
    )


def load_prepared_run_cache(
    cache_dir: str | Path,
    config: Config,
    *,
    expected_prepare_config_digest: str | None = None,
    expected_run_fingerprint: dict[str, object] | None = None,
    expected_label: str | None = None,
    expected_run_key: str | None = None,
) -> RunData:
    """Load and validate one prepared-run cache directory."""
    cache_dir = Path(cache_dir)
    manifest = _read_manifest(cache_dir)
    schema_version = int(manifest.get("schema_version", 0))
    if schema_version != SCHEMA_VERSION:
        raise PreparedCacheError(
            f"Unsupported prepared cache schema_version {schema_version} in {cache_dir}"
        )

    if expected_label is not None and manifest.get("label") != expected_label:
        raise PreparedCacheError(
            f"Prepared cache label mismatch in {cache_dir}: expected {expected_label!r}, found {manifest.get('label')!r}"
        )
    if expected_run_key is not None and manifest.get("run_key") != expected_run_key:
        raise PreparedCacheError(
            f"Prepared cache run key mismatch in {cache_dir}: expected {expected_run_key!r}, found {manifest.get('run_key')!r}"
        )
    if (
        expected_prepare_config_digest is not None
        and manifest.get("prepare_config_digest") != expected_prepare_config_digest
    ):
        raise PreparedCacheError(
            f"Prepared cache config digest mismatch in {cache_dir}; tables were built from a different preparation configuration."
        )
    if (
        expected_run_fingerprint is not None
        and manifest.get("run_fingerprint") != expected_run_fingerprint
    ):
        raise PreparedCacheError(
            f"Prepared cache run fingerprint mismatch in {cache_dir}; tables were built from different run inputs."
        )

    file_format = str(manifest.get("table_format", ""))
    if file_format not in SUPPORTED_FILE_FORMATS:
        raise PreparedCacheError(
            f"Unsupported prepared cache table_format {file_format!r} in {cache_dir}"
        )

    table_files = _manifest_table_map(manifest)
    manifest_table_states = {
        str(table_id): str(state)
        for table_id, state in dict(manifest.get("table_states", {})).items()
    }
    unavailable_table_reasons = {
        str(table_id): str(reason)
        for table_id, reason in dict(manifest.get("unavailable_tables", {})).items()
    }
    loaded_tables: dict[str, pl.DataFrame] = {}
    for attr_name, table_id, stem in PREPARED_TABLE_ATTRS:
        filename = table_files.get(table_id, f"{stem}.{file_format}")
        path = cache_dir / filename
        if not path.exists():
            raise PreparedCacheError(f"Missing prepared table file: {path}")
        if file_format == "parquet":
            table = pl.read_parquet(path)
        else:
            table = pl.read_csv(path, infer_schema_length=10000)
        if (
            manifest_table_states.get(table_id) in {"empty", "unavailable"}
            and table.columns == ["__empty__"]
        ):
            table = pl.DataFrame()
        loaded_tables[attr_name] = table

    return attach_table_availability(
        RunData(
            label=str(manifest.get("label", cache_dir.name)),
            run_dir=str(manifest.get("source_run_dir", "")),
            skim_file=manifest.get("skim_file"),
            hh=loaded_tables["hh"],
            per=loaded_tables["per"],
            tours=loaded_tables["tours"],
            trips=loaded_tables["trips"],
            joint_participants=loaded_tables["joint_participants"],
            land_use=loaded_tables["land_use"],
            skim_matrix=None,
            skim_zone_map=None,
            hh_weight_col=manifest.get("hh_weight_col"),
            person_weight_col=manifest.get("person_weight_col"),
            trip_weight_col=manifest.get("trip_weight_col"),
        ),
        table_states=manifest_table_states,
        table_reasons=unavailable_table_reasons,
    )


def discover_cache_dirs(root: str | Path) -> list[Path]:
    """Return child prepared-cache directories that contain a manifest."""
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        [
            child
            for child in root.iterdir()
            if child.is_dir() and (child / "manifest.json").exists()
        ],
        key=lambda path: path.name,
    )
