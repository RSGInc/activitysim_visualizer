"""Prepared-table cache layout, manifest handling, and load/write helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from processor.cache_infra import (
    discover_manifest_cache_dirs,
    empty_sentinel_frame,
    is_empty_sentinel_frame,
    read_manifest,
    validate_schema_version,
    write_manifest,
)
from processor.cache_identity import (
    build_run_fingerprint,
    build_run_keys,
    file_identity,
    slugify,
)
from processor.models import RunData
from processor.prepare.availability import (
    attach_table_availability,
    table_availability,
    table_diagnostics,
    table_unavailable_reasons,
)
from processor.prepare.writer import write_all
from runtime.config import Config

SCHEMA_VERSION = 9
SUPPORTED_SCHEMA_VERSIONS = {2, 3, 4, 5, 6, 7, 8, 9}
SUPPORTED_FILE_FORMATS = ("parquet", "csv")
PREPARED_TABLE_ATTRS: tuple[tuple[str, str, str], ...] = (
    ("hh", "households", "households"),
    ("per", "persons", "persons"),
    ("day", "day", "day"),
    ("tours", "tours", "tours"),
    ("trips", "trips", "trips"),
    ("vehicles", "vehicles", "vehicles"),
    ("joint_participants", "joint_tour_participants", "joint_tour_participants"),
    ("land_use", "land_use", "land_use"),
)
PREPARED_TABLE_ATTR_BY_ID: dict[str, tuple[str, str]] = {
    table_id: (attr_name, stem)
    for attr_name, table_id, stem in PREPARED_TABLE_ATTRS
}
SIDECAR_TABLE_ATTRS: tuple[tuple[str, str], ...] = (
    ("trip_hypothetical_skims", "trip_hypothetical_skims"),
    ("tour_hypothetical_skims", "tour_hypothetical_skims"),
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
    """Return the shared cache root used for both prepared and summary outputs."""
    return Path(config.summary_root)


def build_prepared_manifest_identity(
    *,
    run_key: str,
    config: Config,
    run_fingerprint: dict[str, object],
    source_type: str = "prepared_cache",
    prepared_table_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return the portable prepared-cache identity used by downstream summaries."""
    identity = {
        "run_key": run_key,
        "prepare_config_digest": config.prepare_config_digest,
        "source_type": source_type,
    }
    if source_type == "custom_prepared_table_map":
        normalized_table_map = dict(sorted((prepared_table_map or {}).items()))
        identity["prepared_table_map"] = normalized_table_map
        identity["prepared_table_fingerprints"] = {
            table_id: file_identity(path)
            for table_id, path in normalized_table_map.items()
        }
    else:
        identity["run_fingerprint"] = dict(run_fingerprint)
    return identity


def _table_file_map(file_format: str) -> dict[str, str]:
    return {
        table_id: f"{stem}.{file_format}" for _, table_id, stem in PREPARED_TABLE_ATTRS
    }


def _sidecar_file_map(file_format: str) -> dict[str, str]:
    return {
        attr_name: f"{stem}.{file_format}" for attr_name, stem in SIDECAR_TABLE_ATTRS
    }


def _manifest_table_map(manifest: dict[str, object]) -> dict[str, str]:
    return {
        str(table_id): str(filename)
        for table_id, filename in dict(manifest.get("table_files", {})).items()
    }


def _skimjoin_resolved_network_los_file(
    rd: RunData | None = None,
    run_fingerprint: dict[str, object] | None = None,
) -> str | None:
    if rd is not None:
        value = rd.skimjoin_manifest.get("skimjoin_resolved_network_los_file")
        if value:
            return str(value)
    skimjoin = (run_fingerprint or {}).get("skimjoin")
    if isinstance(skimjoin, dict):
        value = skimjoin.get("resolved_network_los_file")
        if value:
            return str(value)
    return None


def _prepared_tables_dir(cache_dir: Path, manifest: dict[str, object] | None = None) -> Path:
    if manifest is not None:
        table_root = str(manifest.get("table_root", "")).strip()
        if table_root:
            if cache_dir.name == table_root:
                return cache_dir
            return cache_dir / table_root
    candidate = cache_dir / "prepared_tables"
    if candidate.exists():
        return candidate
    return cache_dir


def _sidecar_tables_dir(cache_dir: Path, manifest: dict[str, object] | None = None) -> Path:
    if manifest is not None:
        sidecar_root = str(manifest.get("sidecar_root", "")).strip()
        if sidecar_root:
            if cache_dir.name == sidecar_root:
                return cache_dir
            return cache_dir / sidecar_root
    return _prepared_tables_dir(cache_dir, manifest)


def _read_table_file(path: Path) -> pl.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix == ".csv":
        try:
            return pl.read_csv(path, infer_schema_length=10000)
        except pl.exceptions.ComputeError as exc:
            try:
                return pl.read_csv(path, infer_schema_length=None)
            except pl.exceptions.ComputeError:
                raise PreparedCacheError(
                    "Failed to parse prepared CSV table "
                    f"{path}. Retried with full-file schema inference after: {exc}"
                ) from exc
    raise PreparedCacheError(
        f"Unsupported prepared table file format {suffix!r} for {path}"
    )


def _write_skimjoin_outputs(cache_dir: Path, rd: RunData, config: Config) -> None:
    if not rd.skimjoin_manifest:
        return

    skimjoin_dir = cache_dir / "skimjoin"
    skimjoin_dir.mkdir(parents=True, exist_ok=True)

    normalized = config.skimjoin.normalized_config
    if normalized is not None:
        from processor.skimjoin.reports.qa import write_normalized_config, write_table

        write_normalized_config(
            skimjoin_dir / "config_normalized.yaml",
            normalized,
        )
        report_filenames = {
            "skim_lookup_summary": "skim_lookup_summary.csv",
            "missing_lookup_report": "missing_lookup_report.csv",
            "fallback_lookup_report": "fallback_lookup_report.csv",
            "skipped_rule_report": "skipped_rule_report.csv",
            "tour_aggregation_summary": "tour_aggregation_summary.csv",
            "failure_report": "failure_report.csv",
        }
        for report_name, filename in report_filenames.items():
            table = rd.skimjoin_reports.get(report_name)
            if table is not None:
                write_table(skimjoin_dir / filename, table)


def _write_sidecar_tables(
    cache_dir: Path,
    rd: RunData,
    *,
    file_format: str,
) -> dict[str, str]:
    sidecar_frames = {
        attr_name: getattr(rd, attr_name)
        for attr_name, _ in SIDECAR_TABLE_ATTRS
        if isinstance(getattr(rd, attr_name), pl.DataFrame)
        and not getattr(rd, attr_name).is_empty()
    }
    if not sidecar_frames:
        return {}

    sidecar_dir = cache_dir / "prepared_tables"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    filenames = _sidecar_file_map(file_format)
    for attr_name, frame in sidecar_frames.items():
        path = sidecar_dir / filenames[attr_name]
        if file_format == "parquet":
            frame.write_parquet(path)
        elif file_format == "csv":
            frame.write_csv(path)
        else:
            raise ValueError(f"Unsupported sidecar file format {file_format!r}.")
    return {attr_name: filenames[attr_name] for attr_name in sidecar_frames}


def write_prepared_run_cache(
    rd: RunData,
    config: Config,
    *,
    run_key: str,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
    file_format: str | None = None,
) -> PreparedRunCacheEntry:
    """Write one prepared run's canonical tables and manifest."""
    if file_format is None:
        file_format = config.prepare_output_file_format
    if file_format not in SUPPORTED_FILE_FORMATS:
        raise ValueError(
            f"Unsupported prepared table file format {file_format!r}. "
            f"Supported formats: {SUPPORTED_FILE_FORMATS}"
        )

    output_root = (
        Path(output_root) if output_root is not None else prepared_root(config)
    )
    output_root.mkdir(parents=True, exist_ok=True)

    cache_dir = output_root / run_key / "prepared_tables"
    cache_dir.mkdir(parents=True, exist_ok=True)

    tables_to_write: dict[str, pl.DataFrame] = {}
    table_states = table_availability(rd)
    diagnostics = table_diagnostics(rd)
    unavailable_reasons = table_unavailable_reasons(rd)
    for attr_name, table_id, stem in PREPARED_TABLE_ATTRS:
        table = getattr(rd, attr_name)
        state = table_states.get(table_id)
        if state is None:
            state = "empty" if table.width == 0 else "available"
        if state in {"empty", "unavailable", "failed"}:
            tables_to_write[stem] = empty_sentinel_frame()
        else:
            tables_to_write[stem] = table

    write_all(tables_to_write, cache_dir, file_format=file_format)
    sidecar_files = _write_sidecar_tables(cache_dir.parent, rd, file_format=file_format)
    _write_skimjoin_outputs(cache_dir, rd, config)

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
        "table_root": "prepared_tables",
        "sidecar_root": "prepared_tables",
        "table_files": _table_file_map(file_format),
        "sidecar_files": sidecar_files,
        "table_states": {
            table_id: table_states.get(
                table_id,
                "empty" if getattr(rd, attr_name).width == 0 else "available",
            )
            for attr_name, table_id, _ in PREPARED_TABLE_ATTRS
        },
        "table_diagnostics": {
            table_id: diagnostics[table_id]
            for _, table_id, _ in PREPARED_TABLE_ATTRS
            if table_states.get(table_id) in {"unavailable", "failed"}
            and table_id in diagnostics
        },
        "unavailable_tables": {
            table_id: unavailable_reasons[table_id]
            for _, table_id, _ in PREPARED_TABLE_ATTRS
            if table_states.get(table_id) == "unavailable"
            and table_id in unavailable_reasons
        },
        "failed_tables": {
            table_id: diagnostics[table_id]
            for _, table_id, _ in PREPARED_TABLE_ATTRS
            if table_states.get(table_id) == "failed" and table_id in diagnostics
        },
        "skim_file": rd.skim_file,
        "source_file_map": dict(
            sorted(
                {
                    **config.files,
                    **(
                        dict(run_fingerprint.get("file_map", {}))
                        if isinstance(run_fingerprint, dict)
                        and isinstance(run_fingerprint.get("file_map"), dict)
                        else {}
                    ),
                }.items()
            )
        ),
        "hh_weight_col": rd.hh_weight_col,
        "person_weight_col": rd.person_weight_col,
        "trip_weight_col": rd.trip_weight_col,
        "run_fingerprint": run_fingerprint or {},
        "prepare_diagnostics": dict(rd.prepare_diagnostics),
        "skimjoin_enabled": bool(rd.skimjoin_manifest.get("skimjoin_enabled", False)),
        "skimjoin_config_digest": rd.skimjoin_manifest.get("skimjoin_config_digest"),
        "skimjoin_resolved_network_los_file": _skimjoin_resolved_network_los_file(
            rd,
            run_fingerprint,
        ),
        "skimjoin_status": rd.skimjoin_manifest.get("skimjoin_status"),
        "skimjoin_applied_outputs": list(
            rd.skimjoin_manifest.get("skimjoin_applied_outputs", [])
        ),
        "skimjoin_skipped_rules": list(
            rd.skimjoin_manifest.get("skimjoin_skipped_rules", [])
        ),
        "skimjoin_warning_count": int(
            rd.skimjoin_manifest.get("skimjoin_warning_count", 0)
        ),
        "skimjoin_fallback_count": int(
            rd.skimjoin_manifest.get("skimjoin_fallback_count", 0)
        ),
        "skimjoin_fallback_outputs": list(
            rd.skimjoin_manifest.get("skimjoin_fallback_outputs", [])
        ),
        "skimjoin_failure_detail": rd.skimjoin_manifest.get(
            "skimjoin_failure_detail"
        ),
        "skimjoin_hypothetical_sidecars_enabled": bool(
            config.skimjoin.create_hypothetical_skim_tables
        ),
        "skimjoin_trip_hypothetical_rows": int(rd.trip_hypothetical_skims.height),
        "skimjoin_tour_hypothetical_rows": int(rd.tour_hypothetical_skims.height),
    }
    write_manifest(cache_dir, manifest)
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
    manifest = read_manifest(cache_dir, error_cls=PreparedCacheError)
    validate_schema_version(
        cache_dir=cache_dir,
        manifest=manifest,
        supported_versions=SUPPORTED_SCHEMA_VERSIONS,
        error_factory=lambda message: PreparedCacheError(
            message.replace(
                "Unsupported cache schema_version",
                "Unsupported prepared cache schema_version",
            )
        ),
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
    manifest_table_diagnostics = {
        str(table_id): str(reason)
        for table_id, reason in dict(manifest.get("table_diagnostics", {})).items()
    }
    unavailable_table_reasons = {
        str(table_id): str(reason)
        for table_id, reason in dict(manifest.get("unavailable_tables", {})).items()
    }
    failed_table_reasons = {
        str(table_id): str(reason)
        for table_id, reason in dict(manifest.get("failed_tables", {})).items()
    }
    if not manifest_table_diagnostics:
        manifest_table_diagnostics = {
            **unavailable_table_reasons,
            **failed_table_reasons,
        }
    loaded_tables: dict[str, pl.DataFrame] = {}
    prepared_tables_dir = _prepared_tables_dir(cache_dir, manifest)
    for attr_name, table_id, stem in PREPARED_TABLE_ATTRS:
        filename = table_files.get(table_id, f"{stem}.{file_format}")
        path = prepared_tables_dir / filename
        if not path.exists():
            raise PreparedCacheError(f"Missing prepared table file: {path}")
        table = _read_table_file(path)
        if manifest_table_states.get(table_id) in {
            "empty",
            "unavailable",
            "failed",
        } and is_empty_sentinel_frame(table):
            table = pl.DataFrame()
        loaded_tables[attr_name] = table
    sidecar_tables: dict[str, pl.DataFrame] = {
        attr_name: pl.DataFrame() for attr_name, _ in SIDECAR_TABLE_ATTRS
    }
    sidecar_files = {
        str(attr_name): str(filename)
        for attr_name, filename in dict(manifest.get("sidecar_files", {})).items()
    }
    sidecar_dir = _sidecar_tables_dir(cache_dir, manifest)
    for attr_name, stem in SIDECAR_TABLE_ATTRS:
        filename = sidecar_files.get(attr_name)
        if not filename:
            continue
        path = sidecar_dir / filename
        if not path.exists():
            raise PreparedCacheError(f"Missing prepared sidecar file: {path}")
        sidecar_tables[attr_name] = _read_table_file(path)

    return attach_table_availability(
        RunData(
            label=str(manifest.get("label", cache_dir.name)),
            run_dir=str(manifest.get("source_run_dir", "")),
            skim_file=manifest.get("skim_file"),
            hh=loaded_tables["hh"],
            per=loaded_tables["per"],
            day=loaded_tables["day"],
            tours=loaded_tables["tours"],
            trips=loaded_tables["trips"],
            vehicles=loaded_tables["vehicles"],
            trip_hypothetical_skims=sidecar_tables["trip_hypothetical_skims"],
            tour_hypothetical_skims=sidecar_tables["tour_hypothetical_skims"],
            joint_participants=loaded_tables["joint_participants"],
            land_use=loaded_tables["land_use"],
            skim_matrix=None,
            skim_zone_map=None,
            hh_weight_col=manifest.get("hh_weight_col"),
            person_weight_col=manifest.get("person_weight_col"),
            trip_weight_col=manifest.get("trip_weight_col"),
            prepare_diagnostics=dict(manifest.get("prepare_diagnostics", {})),
            skimjoin_manifest={
                "skimjoin_enabled": bool(manifest.get("skimjoin_enabled", False)),
                "skimjoin_config_digest": manifest.get("skimjoin_config_digest"),
                "skimjoin_resolved_network_los_file": manifest.get(
                    "skimjoin_resolved_network_los_file"
                )
                or _skimjoin_resolved_network_los_file(
                    run_fingerprint=dict(manifest.get("run_fingerprint", {}))
                ),
                "skimjoin_status": manifest.get("skimjoin_status"),
                "skimjoin_applied_outputs": list(
                    manifest.get("skimjoin_applied_outputs", [])
                ),
                "skimjoin_skipped_rules": list(
                    manifest.get("skimjoin_skipped_rules", [])
                ),
                "skimjoin_warning_count": int(
                    manifest.get("skimjoin_warning_count", 0)
                ),
                "skimjoin_fallback_count": int(
                    manifest.get("skimjoin_fallback_count", 0)
                ),
                "skimjoin_fallback_outputs": list(
                    manifest.get("skimjoin_fallback_outputs", [])
                ),
                "skimjoin_hypothetical_sidecars_enabled": bool(
                    manifest.get("skimjoin_hypothetical_sidecars_enabled", False)
                ),
                "skimjoin_trip_hypothetical_rows": int(
                    manifest.get("skimjoin_trip_hypothetical_rows", 0)
                ),
                "skimjoin_tour_hypothetical_rows": int(
                    manifest.get("skimjoin_tour_hypothetical_rows", 0)
                ),
                "skimjoin_failure_detail": manifest.get("skimjoin_failure_detail"),
            },
        ),
        table_states=manifest_table_states,
        table_reasons=manifest_table_diagnostics,
    )


def discover_cache_dirs(root: str | Path) -> list[Path]:
    """Return child prepared-cache directories that contain a manifest."""
    root = Path(root)
    direct_dirs = discover_manifest_cache_dirs(root)
    if direct_dirs:
        return direct_dirs
    nested_dirs: list[Path] = []
    if root.exists():
        for run_dir in root.iterdir():
            candidate = run_dir / "prepared_tables"
            if candidate.is_dir() and (candidate / "manifest.json").exists():
                nested_dirs.append(candidate)
    return sorted(nested_dirs)


def load_custom_prepared_tables(
    *,
    prepared_table_map: dict[str, str],
    label: str,
    run_dir: str | None = None,
) -> RunData:
    """Load user-supplied canonical prepared tables without a manifest."""
    if not prepared_table_map:
        raise PreparedCacheError(
            f"Run {label!r} does not define any prepared_table_map entries."
        )

    loaded_tables: dict[str, pl.DataFrame] = {}
    table_states: dict[str, str] = {}
    table_reasons: dict[str, str] = {}
    for attr_name, table_id, _ in PREPARED_TABLE_ATTRS:
        configured_path = prepared_table_map.get(table_id)
        if configured_path is None:
            loaded_tables[attr_name] = pl.DataFrame()
            table_states[table_id] = (
                "unavailable"
                if table_id in {"day", "vehicles", "joint_tour_participants", "land_use"}
                else "empty"
            )
            if table_states[table_id] == "unavailable":
                table_reasons[table_id] = (
                    f"No prepared_table_map entry configured for optional table {table_id!r}."
                )
            continue

        path = Path(configured_path)
        if not path.exists():
            loaded_tables[attr_name] = pl.DataFrame()
            table_states[table_id] = "unavailable"
            table_reasons[table_id] = f"Missing prepared table file: {path}"
            continue
        try:
            table = _read_table_file(path)
        except Exception as exc:
            loaded_tables[attr_name] = pl.DataFrame()
            table_states[table_id] = "failed"
            table_reasons[table_id] = str(exc)
            continue
        loaded_tables[attr_name] = table
        table_states[table_id] = "empty" if table.width == 0 else "available"

    return attach_table_availability(
        RunData(
            label=label,
            run_dir=str(run_dir or ""),
            skim_file=None,
            hh=loaded_tables["hh"],
            per=loaded_tables["per"],
            day=loaded_tables["day"],
            tours=loaded_tables["tours"],
            trips=loaded_tables["trips"],
            vehicles=loaded_tables["vehicles"],
            joint_participants=loaded_tables["joint_participants"],
            land_use=loaded_tables["land_use"],
            skim_matrix=None,
            skim_zone_map=None,
        ),
        table_states=table_states,
        table_reasons=table_reasons,
    )
