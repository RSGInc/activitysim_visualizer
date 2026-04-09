"""Summary cache layout, manifest handling, and CSV load/write helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Callable

import polars as pl

from summarize import (
    demographics,
    destination,
    long_term,
    mandatory,
    stops,
    totals,
    tour_mode,
    tour_tod,
    tours,
    trips,
)
from summarize.reader import Config, RunData
from summarize.writer import write_all

SCHEMA_VERSION = 2
SUPPORTED_WEIGHTING_MODES = ("weighted", "unweighted")


class SummaryCacheError(RuntimeError):
    """Raised when a summary cache directory is invalid or incomplete."""


@dataclass(frozen=True)
class SummarySpec:
    summary_id: str
    filename: str
    builder: Callable[[RunData, Config], pl.DataFrame]


@dataclass
class SummaryRun:
    label: str
    run_key: str
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]]
    source_run_dir: str | None = None
    raw_run: RunData | None = None
    manifest: dict[str, object] | None = None


def _build_tlfd_work(rd: RunData, config: Config) -> pl.DataFrame:
    return mandatory.tlfd(rd, config)["work"]


def _build_tlfd_univ(rd: RunData, config: Config) -> pl.DataFrame:
    return mandatory.tlfd(rd, config)["univ"]


def _build_tlfd_schl(rd: RunData, config: Config) -> pl.DataFrame:
    return mandatory.tlfd(rd, config)["schl"]


SUMMARY_SPECS: tuple[SummarySpec, ...] = (
    ### DEMOGRAPHIC SUMMARIES
    SummarySpec(
        "household_size_distribution",
        "household_size_distribution",
        demographics.hh_size,
    ),
    SummarySpec(
        "person_type_distribution", "person_type_distribution", demographics.person_type
    ),
    SummarySpec(
        "population_totals", "population_totals", demographics.population_totals
    ),
    ### LONG TERM SUMMARIES
    # license holding
    # bicycle comfort
    # AV Ownership
    SummarySpec(
        "auto_ownership_distribution",
        "auto_ownership_distribution",
        long_term.auto_ownership,
    ),
    SummarySpec(
        "work_from_home_rate_by_geography",
        "work_from_home_rate_by_geography",
        long_term.wfh,
    ),
    # Internal vs external workers.
    # External worker workplace location
    # Workplace location vs land use employment
    # commuting flows
    # school location vs land use
    SummarySpec(
        "work_location_distance_distribution_by_geography",
        "work_location_distance_distribution_by_geography",
        _build_tlfd_work,
    ),
    SummarySpec(
        "university_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        _build_tlfd_univ,
    ),
    SummarySpec(
        "school_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        _build_tlfd_schl,
    ),
    # vehicle age
    # vehicle fuel type
    # vehicle body type
    # transit pass ownership
    # transit subsidy
    # free parking
    SummarySpec(
        "telecommute_frequency_distribution",
        "telecommute_frequency_distribution",
        long_term.telecommute,
    ),
    ### DAILY TRAVEL SUMMARIES
    SummarySpec("dap_summary", "dapSummary_vis", tours.dap_summary),
    SummarySpec("mand_tour_lengths", "mandTourLengths", mandatory.mand_tour_lengths),
    SummarySpec("geo_flows", "geoFlows", mandatory.geo_flows),
    SummarySpec("mandatory_tour_freq", "mtfSummary_vis", tours.mandatory_tour_freq),
    SummarySpec("indiv_nm_summary", "inmSummary_vis", tours.indiv_nm_summary),
    SummarySpec("nm_tour_rates", "nm_tour_rates", tours.nm_tour_rates),
    SummarySpec("joint_tour_freq", "jtf", lambda rd, config: tours.joint_tour_freq(rd)),
    SummarySpec(
        "joint_composition", "jointComp", lambda rd, config: tours.joint_composition(rd)
    ),
    SummarySpec(
        "joint_party_size",
        "jointPartySize",
        lambda rd, config: tours.joint_party_size(rd),
    ),
    SummarySpec(
        "joint_tours_hhsize",
        "jointToursHHSize",
        lambda rd, config: tours.joint_tours_hhsize(rd),
    ),
    SummarySpec("tour_mode_profile", "tmodeProfile_vis", tour_mode.tour_mode_profile),
    SummarySpec(
        "grouped_tour_mode_profile",
        "groupedTmodeProfile_vis",
        tour_mode.grouped_tour_mode_profile,
    ),
    SummarySpec(
        "tour_tod_profiles",
        "todProfile_vis",
        lambda rd, config: tour_tod.tod_profiles(rd),
    ),
    SummarySpec("trip_mode_profile", "tripModeProfile_vis", trips.trip_mode_profile),
    SummarySpec("stop_freq", "stopFreq", lambda rd, config: stops.stop_freq(rd)),
    SummarySpec(
        "stop_purpose_by_tour_purpose",
        "stopPurpose",
        lambda rd, config: stops.stop_purpose_by_tour_purpose(rd),
    ),
    SummarySpec(
        "stop_location", "stopLocation", lambda rd, config: stops.stop_location(rd)
    ),
    SummarySpec("stop_timing", "stopTiming", lambda rd, config: stops.stop_timing(rd)),
    SummarySpec(
        "destination_distance",
        "destinationDistByPurpose",
        lambda rd, config: destination.distance_distribution(rd),
    ),
    SummarySpec(
        "destination_average_distance",
        "destinationAvgDistance",
        lambda rd, config: destination.average_distance(rd),
    ),
)

SUMMARY_SPEC_BY_ID = {spec.summary_id: spec for spec in SUMMARY_SPECS}
SUMMARY_FILENAME_BY_ID = {
    spec.summary_id: f"{spec.filename}.csv" for spec in SUMMARY_SPECS
}
DEFAULT_SUMMARY_IDS = [spec.summary_id for spec in SUMMARY_SPECS]


def normalize_weighting_modes(modes: list[str] | None) -> list[str]:
    if not modes:
        modes = list(SUPPORTED_WEIGHTING_MODES)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_mode in modes:
        mode = str(raw_mode).strip().lower()
        if mode not in SUPPORTED_WEIGHTING_MODES:
            raise ValueError(
                f"Unsupported weighting mode {raw_mode!r}. Supported modes: {SUPPORTED_WEIGHTING_MODES}"
            )
        if mode not in seen:
            normalized.append(mode)
            seen.add(mode)
    return normalized


def strip_weights(rd: RunData) -> RunData:
    """Return a copy of ``RunData`` with all ``finalweight`` values reset to 1.0."""

    def _reset(df: pl.DataFrame) -> pl.DataFrame:
        if "finalweight" in df.columns:
            return df.with_columns(pl.lit(1.0).alias("finalweight"))
        return df

    return RunData(
        label=rd.label,
        run_dir=rd.run_dir,
        skim_file=rd.skim_file,
        hh=_reset(rd.hh),
        per=_reset(rd.per),
        tours=_reset(rd.tours),
        trips=_reset(rd.trips),
        joint_participants=rd.joint_participants,
        land_use=rd.land_use,
        skim_matrix=rd.skim_matrix,
        skim_zone_map=rd.skim_zone_map,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )


def build_summaries(
    rd: RunData,
    config: Config,
    summary_ids: list[str] | None = None,
) -> dict[str, pl.DataFrame]:
    """Build the configured summary tables for a run."""
    summary_ids = summary_ids or DEFAULT_SUMMARY_IDS
    tables: dict[str, pl.DataFrame] = {}
    for summary_id in summary_ids:
        spec = SUMMARY_SPEC_BY_ID.get(summary_id)
        if spec is None:
            raise KeyError(f"Unknown summary id: {summary_id}")
        tables[summary_id] = spec.builder(rd, config)
    return tables


def build_mode_summaries(
    rd: RunData,
    config: Config,
    weighting_modes: list[str] | None = None,
    summary_ids: list[str] | None = None,
) -> dict[str, dict[str, pl.DataFrame]]:
    """Build all requested summary tables for each weighting mode."""
    weighting_modes = normalize_weighting_modes(
        weighting_modes or config.weighting_modes
    )
    mode_runs: dict[str, RunData] = {"weighted": rd}
    if "unweighted" in weighting_modes:
        mode_runs["unweighted"] = strip_weights(rd)

    summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    for mode in weighting_modes:
        mode_rd = mode_runs["weighted"] if mode == "weighted" else mode_runs[mode]
        summaries_by_mode[mode] = build_summaries(
            mode_rd, config, summary_ids=summary_ids
        )
    return summaries_by_mode


def summary_root(config: Config) -> Path:
    return Path(config.summary_root)


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


def summary_file_map(summary_ids: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for summary_id in summary_ids:
        mapping[summary_id] = SUMMARY_FILENAME_BY_ID.get(
            summary_id, f"{summary_id}.csv"
        )
    return mapping


def build_run_fingerprint(
    *,
    label: str,
    run_dir: str | None,
    skim_file: str | None,
    hh_weight_col: str | None,
    person_weight_col: str | None,
    trip_weight_col: str | None,
) -> dict[str, object]:
    return {
        "label": label,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "skim_file": str(skim_file) if skim_file is not None else None,
        "hh_weight_col": hh_weight_col,
        "person_weight_col": person_weight_col,
        "trip_weight_col": trip_weight_col,
    }


def create_summary_run(
    *,
    label: str,
    run_key: str,
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]],
    source_run_dir: str | None = None,
    raw_run: RunData | None = None,
    manifest: dict[str, object] | None = None,
) -> SummaryRun:
    return SummaryRun(
        label=label,
        run_key=run_key,
        summaries_by_mode=summaries_by_mode,
        source_run_dir=source_run_dir,
        raw_run=raw_run,
        manifest=manifest,
    )


def write_summary_run_cache(
    summary_run: SummaryRun,
    config: Config,
    *,
    output_root: str | Path | None = None,
    run_fingerprint: dict[str, object] | None = None,
) -> Path:
    output_root = Path(output_root) if output_root is not None else summary_root(config)
    output_root.mkdir(parents=True, exist_ok=True)

    run_dir = output_root / summary_run.run_key
    run_dir.mkdir(parents=True, exist_ok=True)

    weighting_modes = list(summary_run.summaries_by_mode.keys())
    summary_ids: list[str] = []
    empty_summaries: dict[str, list[str]] = {}
    for mode in weighting_modes:
        mode_tables = summary_run.summaries_by_mode[mode]
        summary_ids = list(mode_tables.keys())
        file_tables = {}
        empty_summaries[mode] = []
        for summary_id, table in mode_tables.items():
            filename = Path(summary_file_map([summary_id])[summary_id]).stem
            if table.width == 0:
                file_tables[filename] = pl.DataFrame({"__empty__": []})
                empty_summaries[mode].append(summary_id)
            else:
                file_tables[filename] = table
        write_all(file_tables, run_dir / mode)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "activitysim-visualizer-summary-cache",
        "label": summary_run.label,
        "run_key": summary_run.run_key,
        "source_run_dir": summary_run.source_run_dir,
        "config_path": config.config_path,
        "config_digest": config.config_digest,
        "weighting_modes": weighting_modes,
        "summary_ids": summary_ids,
        "summary_files": summary_file_map(summary_ids),
        "empty_summaries": empty_summaries,
        "run_fingerprint": run_fingerprint or {},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    summary_run.manifest = manifest
    return run_dir


def _read_manifest(cache_dir: Path) -> dict[str, object]:
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        raise SummaryCacheError(f"Missing manifest: {manifest_path}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SummaryCacheError(
            f"Invalid manifest JSON in {manifest_path}: {exc}"
        ) from exc


def load_summary_run_cache(
    cache_dir: str | Path,
    config: Config,
    *,
    expected_modes: list[str] | None = None,
    expected_summary_ids: list[str] | None = None,
    expected_config_digest: str | None = None,
    expected_run_fingerprint: dict[str, object] | None = None,
    expected_label: str | None = None,
    expected_run_key: str | None = None,
) -> SummaryRun:
    cache_dir = Path(cache_dir)
    manifest = _read_manifest(cache_dir)
    schema_version = int(manifest.get("schema_version", 0))
    if schema_version != SCHEMA_VERSION:
        raise SummaryCacheError(
            f"Unsupported cache schema_version {schema_version} in {cache_dir}"
        )

    if expected_label is not None and manifest.get("label") != expected_label:
        raise SummaryCacheError(
            f"Cache label mismatch in {cache_dir}: expected {expected_label!r}, found {manifest.get('label')!r}"
        )
    if expected_run_key is not None and manifest.get("run_key") != expected_run_key:
        raise SummaryCacheError(
            f"Cache run key mismatch in {cache_dir}: expected {expected_run_key!r}, found {manifest.get('run_key')!r}"
        )
    if (
        expected_config_digest is not None
        and manifest.get("config_digest") != expected_config_digest
    ):
        raise SummaryCacheError(
            f"Cache config digest mismatch in {cache_dir}; summaries were built from a different config."
        )
    if (
        expected_run_fingerprint is not None
        and manifest.get("run_fingerprint") != expected_run_fingerprint
    ):
        raise SummaryCacheError(
            f"Cache run fingerprint mismatch in {cache_dir}; summaries were built from different run inputs."
        )

    expected_modes = normalize_weighting_modes(expected_modes or config.weighting_modes)
    manifest_modes = normalize_weighting_modes(
        [str(mode) for mode in manifest.get("weighting_modes", [])]
    )
    missing_modes = [mode for mode in expected_modes if mode not in manifest_modes]
    if missing_modes:
        raise SummaryCacheError(
            f"Cache {cache_dir} is missing weighting modes: {missing_modes}"
        )

    manifest_summary_ids = [str(item) for item in manifest.get("summary_ids", [])]
    expected_summary_ids = expected_summary_ids or manifest_summary_ids
    missing_summary_ids = [
        summary_id
        for summary_id in expected_summary_ids
        if summary_id not in manifest_summary_ids
    ]
    if missing_summary_ids:
        raise SummaryCacheError(
            f"Cache {cache_dir} is missing summary tables: {missing_summary_ids}"
        )

    summary_files = {
        str(summary_id): str(filename)
        for summary_id, filename in dict(manifest.get("summary_files", {})).items()
    }
    empty_summaries = {
        str(mode): [str(summary_id) for summary_id in summary_ids]
        for mode, summary_ids in dict(manifest.get("empty_summaries", {})).items()
    }
    summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
    for mode in expected_modes:
        mode_dir = cache_dir / mode
        if not mode_dir.exists():
            raise SummaryCacheError(f"Missing mode directory: {mode_dir}")
        mode_tables: dict[str, pl.DataFrame] = {}
        for summary_id in expected_summary_ids:
            filename = summary_files.get(summary_id, f"{summary_id}.csv")
            path = mode_dir / filename
            if not path.exists():
                raise SummaryCacheError(f"Missing summary CSV: {path}")
            table = pl.read_csv(path, infer_schema_length=10000)
            if summary_id in empty_summaries.get(mode, []) and table.columns == [
                "__empty__"
            ]:
                table = pl.DataFrame()
            mode_tables[summary_id] = table
        summaries_by_mode[mode] = mode_tables

    return SummaryRun(
        label=str(manifest.get("label", cache_dir.name)),
        run_key=str(manifest.get("run_key", cache_dir.name)),
        summaries_by_mode=summaries_by_mode,
        source_run_dir=manifest.get("source_run_dir"),
        manifest=manifest,
    )


def discover_cache_dirs(root: str | Path) -> list[Path]:
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
