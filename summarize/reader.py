"""ActivitySim output file reader and data preparation.

Key design principles:
- No numeric code mappings for purpose/mode/category — raw strings are used directly.
- Geography grouping is optional (controlled by config.geography_enabled).
- MAZ→TAZ conversion is optional (config.use_maz). TAZ-only models work without it.
- Multiple runs are supported; each run can specify its own skim file.
- File format auto-detection: if no extension given, tries .parquet first, then .csv.
- Weighting: computed once by compute_weights() and stored as "finalweight" on each table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Optional

import numpy as np
import polars as pl
import yaml

@dataclass(frozen=True)
class ExportSelectorRequest:
    """Requested export state selection for one page-level selector."""

    mode: str = "default"
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportDashboardSettings:
    """Resolved dashboard-level export controls."""

    weighting: list[str] = field(default_factory=lambda: ["weighted"])
    values: list[str] = field(default_factory=lambda: ["percent"])

    def panel_weighting_values(self) -> list[str]:
        return [mode.title() for mode in self.weighting]

    def panel_value_values(self) -> list[str]:
        labels = {"percent": "Percent", "count": "Count"}
        return [labels[value] for value in self.values]


@dataclass(frozen=True)
class ExportHTMLSettings:
    """Resolved export HTML settings for dashboard and page-level controls."""

    dashboard: ExportDashboardSettings = field(default_factory=ExportDashboardSettings)
    pages: dict[str, dict[str, ExportSelectorRequest]] = field(default_factory=dict)

    @property
    def weighting(self) -> list[str]:
        return self.dashboard.weighting

    @property
    def values(self) -> list[str]:
        return self.dashboard.values

    def panel_weighting_values(self) -> list[str]:
        return self.dashboard.panel_weighting_values()

    def panel_value_values(self) -> list[str]:
        return self.dashboard.panel_value_values()

    def selector_request(
        self,
        page_id: str,
        selector_id: str,
    ) -> ExportSelectorRequest:
        return self.pages.get(page_id, {}).get(selector_id, ExportSelectorRequest())


def _normalize_export_html_selection(
    raw_value,
    *,
    field_name: str,
    default: list[str],
    allowed: list[str],
) -> list[str]:
    """Resolve an export HTML config selection to validated lowercase values."""
    if raw_value is None:
        raw_value = "default"

    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        if token == "default":
            result = list(default)
        elif token == "all":
            result = list(allowed)
        else:
            result = [token]
    elif isinstance(raw_value, list):
        result = []
        for item in raw_value:
            if not isinstance(item, str):
                raise ValueError(
                    f"outputs.export_html.{field_name} entries must be strings."
                )
            token = item.strip().lower()
            if not token:
                continue
            result.append(token)
    else:
        raise ValueError(
            f"outputs.export_html.{field_name} must be 'default', 'all', or a list of strings."
        )

    deduped: list[str] = []
    invalid: list[str] = []
    for token in result:
        if token not in allowed:
            invalid.append(token)
            continue
        if token not in deduped:
            deduped.append(token)

    if invalid:
        raise ValueError(
            f"Unsupported outputs.export_html.{field_name} values: "
            + ", ".join(repr(token) for token in invalid)
        )
    if not deduped:
        raise ValueError(
            f"outputs.export_html.{field_name} resolved to no values."
        )
    return deduped


def _normalize_export_selector_request(
    raw_value,
    *,
    field_name: str,
) -> ExportSelectorRequest:
    """Normalize a page-level selector request."""
    if raw_value is None:
        return ExportSelectorRequest()

    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        if not token or token == "default":
            return ExportSelectorRequest(mode="default")
        if token == "all":
            return ExportSelectorRequest(mode="all")
        return ExportSelectorRequest(mode="explicit", values=(token,))

    if not isinstance(raw_value, list):
        raise ValueError(
            f"{field_name} must be 'default', 'all', or a list of strings."
        )

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip().lower()
        if not token:
            continue
        if token not in normalized:
            normalized.append(token)
    if not normalized:
        raise ValueError(f"{field_name} resolved to no values.")
    return ExportSelectorRequest(mode="explicit", values=tuple(normalized))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """All configuration for the visualizer, loaded from config.yaml."""

    config_path: str
    config_digest: str
    name: str
    dashboard_title: str
    run_colors: list[str]
    summary_root: str
    weighting_modes: list[str]
    export_html: ExportHTMLSettings

    # File name overrides (stems or full names with .csv/.parquet)
    files: dict[str, str]

    # Column name overrides
    col_ptype: str
    col_hhsize: str
    col_auto_ownership: str
    col_num_workers: str
    col_num_adults: str
    col_sample_rate: Optional[str]  # column in HH table; weight = 1/sample_rate
    person_type_labels: Optional[dict[str, str]]  # raw ptype value -> label

    # Zone system
    use_maz: bool
    maz_col: str
    taz_col: str

    # Geography (optional)
    geography_enabled: bool
    geography_landuse_col: Optional[str]
    geography_mapping: Optional[
        dict
    ]  # raw_value -> display_name (str keys after yaml load)

    # Skim (global default)
    skim_file: Optional[str]
    skim_matrix: str

    # Mode display
    mode_order: Optional[list[str]]
    mode_groups: Optional[dict[str, list[str]]]  # group_name -> [mode_names]

    # Runs defined in config (can be overridden/extended via CLI)
    # Each entry: {dir, label, skim_file?, hh_weight_col?, person_weight_col?, trip_weight_col?}
    runs: list[dict]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        config_path = Path(path).resolve()
        config_bytes = config_path.read_bytes()
        raw = yaml.safe_load(config_bytes.decode("utf-8"))

        files = raw.get("files", {})
        # Defaults use stems (no extension) so auto-detection picks parquet-first.
        # Configs that explicitly set ".csv" or ".parquet" are respected as-is.
        _file_defaults = {
            "households": "final_households",
            "persons": "final_persons",
            "tours": "final_tours",
            "trips": "final_trips",
            "joint_tour_participants": "final_joint_tour_participants",
            "land_use": "final_land_use",
        }
        for k, v in _file_defaults.items():
            files.setdefault(k, v)

        cols = raw.get("columns", {})
        zones = raw.get("zones", {})

        geo = raw.get("geography", {})
        geo_enabled = bool(geo.get("enabled", False))
        geo_mapping = None
        if geo_enabled and "mapping" in geo:
            # YAML may load int keys as ints; normalise to str for consistent lookup
            geo_mapping = {str(k): str(v) for k, v in geo["mapping"].items()}

        skim_cfg = raw.get("skim", {})
        modes_cfg = raw.get("modes", {})
        outputs_cfg = raw.get("outputs", {})
        if outputs_cfg is None:
            outputs_cfg = {}
        if not isinstance(outputs_cfg, dict):
            raise ValueError("outputs must be a mapping when provided.")

        summary_root = Path(outputs_cfg.get("summary_root", "artifacts/summary_cache"))
        if not summary_root.is_absolute():
            summary_root = (config_path.parent / summary_root).resolve()

        raw_weighting_modes = [
            str(mode).strip().lower()
            for mode in outputs_cfg.get("weighting_modes", ["weighted", "unweighted"])
        ]
        supported_weighting_modes = {"weighted", "unweighted"}
        invalid_weighting_modes = [
            mode
            for mode in raw_weighting_modes
            if mode and mode not in supported_weighting_modes
        ]
        if invalid_weighting_modes:
            raise ValueError(
                "Unsupported outputs.weighting_modes values: "
                + ", ".join(repr(mode) for mode in invalid_weighting_modes)
            )
        weighting_modes: list[str] = []
        for mode in raw_weighting_modes:
            if mode and mode not in weighting_modes:
                weighting_modes.append(mode)
        if not weighting_modes:
            weighting_modes = ["weighted", "unweighted"]

        export_html_cfg = outputs_cfg.get("export_html") or {}
        if not isinstance(export_html_cfg, dict):
            raise ValueError("outputs.export_html must be a mapping when provided.")

        dashboard_cfg = export_html_cfg.get("dashboard")
        if dashboard_cfg is None:
            dashboard_cfg = {}
        elif not isinstance(dashboard_cfg, dict):
            raise ValueError("outputs.export_html.dashboard must be a mapping.")

        # Legacy fallback: accept flat weighting/values keys during migration.
        legacy_dashboard_cfg = {}
        for key in ("weighting", "values"):
            if key in export_html_cfg:
                legacy_dashboard_cfg[key] = export_html_cfg.get(key)
        dashboard_cfg = {**legacy_dashboard_cfg, **dashboard_cfg}

        pages_cfg = export_html_cfg.get("pages")
        if pages_cfg is None:
            pages_cfg = {}
        elif not isinstance(pages_cfg, dict):
            raise ValueError("outputs.export_html.pages must be a mapping.")
        normalized_pages: dict[str, dict[str, ExportSelectorRequest]] = {}
        for raw_page_id, raw_page_cfg in pages_cfg.items():
            page_id = str(raw_page_id).strip().lower()
            if not page_id:
                raise ValueError("outputs.export_html.pages contains an empty page id.")
            if not isinstance(raw_page_cfg, dict):
                raise ValueError(
                    f"outputs.export_html.pages.{page_id} must be a mapping."
                )
            normalized_selector_cfg: dict[str, ExportSelectorRequest] = {}
            for raw_selector_id, raw_selector_cfg in raw_page_cfg.items():
                selector_id = str(raw_selector_id).strip().lower()
                if not selector_id:
                    raise ValueError(
                        f"outputs.export_html.pages.{page_id} contains an empty selector id."
                    )
                normalized_selector_cfg[selector_id] = _normalize_export_selector_request(
                    raw_selector_cfg,
                    field_name=f"outputs.export_html.pages.{page_id}.{selector_id}",
                )
            normalized_pages[page_id] = normalized_selector_cfg

        export_html = ExportHTMLSettings(
            dashboard=ExportDashboardSettings(
                weighting=_normalize_export_html_selection(
                    dashboard_cfg.get("weighting"),
                    field_name="dashboard.weighting",
                    default=[weighting_modes[0]],
                    allowed=weighting_modes,
                ),
                values=_normalize_export_html_selection(
                    dashboard_cfg.get("values"),
                    field_name="dashboard.values",
                    default=["percent"],
                    allowed=["percent", "count"],
                ),
            ),
            pages=normalized_pages,
        )

        return cls(
            config_path=str(config_path),
            config_digest=hashlib.sha256(config_bytes).hexdigest(),
            name=raw.get("name", ""),
            dashboard_title=raw.get("dashboard_title", "ActivitySim Visualizer"),
            run_colors=raw.get(
                "run_colors",
                [
                    "#1f77b4",
                    "#ff7f0e",
                    "#2ca02c",
                    "#d62728",
                    "#9467bd",
                    "#8c564b",
                    "#e377c2",
                    "#7f7f7f",
                ],
            ),
            summary_root=str(summary_root),
            weighting_modes=weighting_modes,
            export_html=export_html,
            files=files,
            col_ptype=cols.get("ptype", "ptype"),
            col_hhsize=cols.get("hhsize", "hhsize"),
            col_auto_ownership=cols.get("auto_ownership", "auto_ownership"),
            col_num_workers=cols.get("num_workers", "num_workers"),
            col_num_adults=cols.get("num_adults", "num_adults"),
            col_sample_rate=cols.get("sample_rate") or None,
            person_type_labels={
                str(k): str(v) for k, v in raw.get("person_types", {}).items()
            }
            or None,
            use_maz=bool(zones.get("use_maz", True)),
            maz_col=zones.get("maz_col", "zone_id"),
            taz_col=zones.get("taz_col", "TAZ"),
            geography_enabled=geo_enabled,
            geography_landuse_col=geo.get("landuse_col") if geo_enabled else None,
            geography_mapping=geo_mapping,
            skim_file=skim_cfg.get("file"),
            skim_matrix=skim_cfg.get("matrix", "SOV_DIST__MD"),
            mode_order=modes_cfg.get("order"),
            mode_groups=modes_cfg.get("groups"),
            runs=raw.get("runs", []),
        )

    def run_color(self, idx: int) -> str:
        return self.run_colors[idx % len(self.run_colors)]

    def ordered_modes(self, modes_in_data: list[str]) -> list[str]:
        """Return modes in display order. Unknown modes appended at end."""
        if not self.mode_order:
            return modes_in_data
        ordered = [m for m in self.mode_order if m in modes_in_data]
        remaining = [m for m in modes_in_data if m not in ordered]
        return ordered + remaining

    def apply_geo_mapping(self, series: pl.Series) -> pl.Series:
        """Apply geography mapping (value→name) to a string series. No-op if no mapping."""
        if not self.geography_mapping:
            return series.cast(pl.Utf8)
        mapping = self.geography_mapping
        return series.cast(pl.Utf8).map_elements(
            lambda v: mapping.get(str(v), str(v)) if v is not None else None,
            return_dtype=pl.Utf8,
        )

    def ptype_label(self, value) -> str:
        v = str(value)
        if self.person_type_labels and v in self.person_type_labels:
            return self.person_type_labels[v]
        return v


# ---------------------------------------------------------------------------
# RunData
# ---------------------------------------------------------------------------


@dataclass
class RunData:
    """Holds all data for one ActivitySim run, enriched by prepare_data()."""

    label: str
    run_dir: str
    skim_file: Optional[str]  # actual skim file path used for this run (may be None)
    hh: pl.DataFrame
    per: pl.DataFrame
    tours: pl.DataFrame
    trips: pl.DataFrame
    joint_participants: pl.DataFrame
    land_use: pl.DataFrame
    skim_matrix: Optional[np.ndarray]  # None if no skim configured
    skim_zone_map: Optional[dict[int, int]] = None  # OMX zone-id -> matrix index
    # Per-run weight column overrides (None = use default weighting rules)
    hh_weight_col: Optional[str] = None
    person_weight_col: Optional[str] = None
    trip_weight_col: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skim_lookup(
    skim: np.ndarray,
    otaz: np.ndarray,
    dtaz: np.ndarray,
    zone_map: Optional[dict[int, int]] = None,
) -> np.ndarray:
    """Vectorized skim lookup; supports OMX mappings and 1-based fallback."""
    o_arr = np.asarray(otaz, dtype=int)
    d_arr = np.asarray(dtaz, dtype=int)
    if zone_map:
        o_idx = np.fromiter(
            (zone_map.get(int(z), -1) for z in o_arr), dtype=int, count=len(o_arr)
        )
        d_idx = np.fromiter(
            (zone_map.get(int(z), -1) for z in d_arr), dtype=int, count=len(d_arr)
        )
    else:
        # Fallback for OMX files without explicit mapping:
        # - If zones appear 0-indexed, use values directly
        # - Otherwise assume 1-indexed and subtract 1
        o_min = int(np.min(o_arr)) if len(o_arr) else 0
        d_min = int(np.min(d_arr)) if len(d_arr) else 0
        o_max = int(np.max(o_arr)) if len(o_arr) else 0
        d_max = int(np.max(d_arr)) if len(d_arr) else 0
        if (
            (o_min >= 0 and d_min >= 0)
            and (o_max < skim.shape[0] and d_max < skim.shape[1])
            and ((o_arr == 0).any() or (d_arr == 0).any())
        ):
            o_idx = o_arr
            d_idx = d_arr
        else:
            o_idx = o_arr - 1
            d_idx = d_arr - 1
    valid = (
        (o_idx >= 0) & (d_idx >= 0) & (o_idx < skim.shape[0]) & (d_idx < skim.shape[1])
    )
    dist = np.zeros(len(o_idx), dtype=float)
    dist[valid] = skim[o_idx[valid], d_idx[valid]]
    return dist


def _resolve_skim(
    run_skim: Optional[str], global_skim: Optional[str], run_dir: Path
) -> Optional[str]:
    """Pick the skim file for a run: per-run > global > None."""
    candidate = run_skim or global_skim
    if not candidate:
        return None
    p = Path(candidate).expanduser()
    if not p.is_absolute():
        p = run_dir / p
    return str(p)


def resolve_skim_path(
    run_skim: Optional[str],
    global_skim: Optional[str],
    run_dir: str | Path,
) -> Optional[str]:
    """Public wrapper used by the cache layer to fingerprint run inputs."""
    return _resolve_skim(run_skim, global_skim, Path(run_dir))


def _find_and_read(run_dir: Path, configured: str) -> pl.DataFrame:
    """Read a table from run_dir, resolving file format.

    Priority:
    - If configured name ends with .parquet → read parquet only.
    - If configured name ends with .csv → read csv only.
    - If no extension (or unrecognised extension) → try .parquet first, then .csv.
    """
    p = Path(configured)
    run_dir = run_dir.expanduser()
    suffix = p.suffix.lower()
    stem = p.stem if suffix in (".csv", ".parquet") else p.name

    if suffix == ".parquet":
        print(f"[read_run] Reading parquet: {run_dir / p}")
        return pl.read_parquet(run_dir / p)
    elif suffix == ".csv":
        print(f"[read_run] Reading csv: {run_dir / p}")
        return pl.read_csv(run_dir / p, infer_schema_length=None)
    else:
        # Auto-detect: parquet first, then csv
        parquet_path = run_dir / f"{stem}.parquet"
        csv_path = run_dir / f"{stem}.csv"
        if parquet_path.exists():
            # print(f"[read_run] Reading parquet (auto): {parquet_path}")
            return pl.read_parquet(parquet_path)
        elif csv_path.exists():
            # print(f"[read_run] Reading csv (auto): {csv_path}")
            return pl.read_csv(csv_path, infer_schema_length=None)
        raise FileNotFoundError(
            f"Cannot find '{stem}.parquet' or '{stem}.csv' in {run_dir}"
        )


# ---------------------------------------------------------------------------
# compute_weights
# ---------------------------------------------------------------------------


def compute_weights(
    hh: pl.DataFrame,
    per: pl.DataFrame,
    tours: pl.DataFrame,
    trips: pl.DataFrame,
    config: Config,
    hh_weight_col: Optional[str] = None,
    person_weight_col: Optional[str] = None,
    trip_weight_col: Optional[str] = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Compute and attach 'finalweight' to HH, persons, tours, and trips.

    Weight derivation rules (in priority order):
      HH:     explicit hh_weight_col  >  1/sample_rate  >  1.0
      Person: explicit person_weight_col  >  inherit HH weight
      Trip:   explicit trip_weight_col    >  inherit person weight
      Tour:   avg(trip finalweight) per tour_id [if trip_weight_col set]
              else inherit person weight (via person_id or household_id)
    """
    explicit_weight_supplied = any([hh_weight_col, person_weight_col, trip_weight_col])
    sample_rate_col = config.col_sample_rate or (
        "sample_rate" if "sample_rate" in hh.columns else None
    )
    if sample_rate_col == "sample_rate" and config.col_sample_rate is None:
        print("[compute_weights] Auto-detected sample_rate column in households.")

    # --- HH finalweight ---
    if hh_weight_col and hh_weight_col in hh.columns:
        print(f"[compute_weights] Using household weight column: {hh_weight_col}")
        hh = hh.with_columns(
            pl.col(hh_weight_col).cast(pl.Float64).alias("finalweight")
        )
    elif (
        (not explicit_weight_supplied)
        and sample_rate_col
        and sample_rate_col in hh.columns
    ):
        print(
            f"[compute_weights] Using sample-rate expansion from column: {sample_rate_col}"
        )
        hh = hh.with_columns(
            (pl.lit(1.0) / pl.col(sample_rate_col).cast(pl.Float64)).alias(
                "finalweight"
            )
        )
    else:
        if (
            explicit_weight_supplied
            and sample_rate_col
            and sample_rate_col in hh.columns
        ):
            print(
                "[compute_weights] Explicit run weight columns supplied; skipping sample_rate expansion."
            )
        else:
            print("[compute_weights] No weight column found; defaulting finalweight=1.")
        hh = hh.with_columns(pl.lit(1.0).alias("finalweight"))

    # --- Person finalweight ---
    if person_weight_col and person_weight_col in per.columns:
        print(f"[compute_weights] Using person weight column: {person_weight_col}")
        per = per.with_columns(
            pl.col(person_weight_col).cast(pl.Float64).alias("finalweight")
        )
    else:
        per = (
            per.join(
                hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                on="household_id",
                how="left",
            )
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    # --- Trip finalweight ---
    if trip_weight_col and trip_weight_col in trips.columns:
        print(f"[compute_weights] Using trip weight column: {trip_weight_col}")
        trips = trips.with_columns(
            pl.col(trip_weight_col).cast(pl.Float64).alias("finalweight")
        )
    else:
        if "person_id" in trips.columns:
            trips = (
                trips.join(
                    per.select(["person_id", pl.col("finalweight").alias("_pw")]),
                    on="person_id",
                    how="left",
                )
                .with_columns(pl.col("_pw").fill_null(1.0).alias("finalweight"))
                .drop("_pw")
            )
        else:
            trips = (
                trips.join(
                    hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                    on="household_id",
                    how="left",
                )
                .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
                .drop("_hw")
            )

    # --- Tour finalweight ---
    if (
        trip_weight_col
        and trip_weight_col in trips.columns
        and "tour_id" in trips.columns
    ):
        # Average of trip weights across all trips in each tour
        tour_avg = trips.group_by("tour_id").agg(
            pl.col("finalweight").mean().alias("_tw")
        )
        tours = (
            tours.join(tour_avg, on="tour_id", how="left")
            .with_columns(pl.col("_tw").fill_null(1.0).alias("finalweight"))
            .drop("_tw")
        )
    elif "person_id" in tours.columns:
        # Inherit person weight (tour lead person for joint tours)
        tours = (
            tours.join(
                per.select(["person_id", pl.col("finalweight").alias("_pw")]),
                on="person_id",
                how="left",
            )
            .with_columns(pl.col("_pw").fill_null(1.0).alias("finalweight"))
            .drop("_pw")
        )
    else:
        # Fall back to HH weight
        tours = (
            tours.join(
                hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                on="household_id",
                how="left",
            )
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    return hh, per, tours, trips


# ---------------------------------------------------------------------------
# read_run
# ---------------------------------------------------------------------------


def read_run(
    run_dir: str | Path,
    config: Config,
    label: Optional[str] = None,
    skim_file: Optional[str] = None,
    hh_weight_col: Optional[str] = None,
    person_weight_col: Optional[str] = None,
    trip_weight_col: Optional[str] = None,
) -> RunData:
    """Read ActivitySim outputs (CSV or Parquet) and optionally the OMX skim for one run.

    File format resolution (per table):
      - If configured name ends with .parquet → read parquet.
      - If configured name ends with .csv     → read csv.
      - If no extension (default)              → try .parquet first, then .csv.

    Args:
        run_dir:           Directory containing final_* files.
        config:            Global Config object.
        label:             Display label; defaults to the directory name.
        skim_file:         Per-run skim override (None → use config.skim_file).
        hh_weight_col:     Column in HH table to use as explicit household weight.
        person_weight_col: Column in persons table to use as explicit person weight.
        trip_weight_col:   Column in trips table to use as explicit trip weight.
    """
    run_dir = Path(run_dir)
    if label is None:
        label = run_dir.name

    def _read(key: str) -> pl.DataFrame:
        return _find_and_read(run_dir, config.files[key])

    hh = _read("households")
    per = _read("persons")
    tours = _read("tours")
    trips = _read("trips")
    joint_parts = _read("joint_tour_participants")
    land_use = _read("land_use")

    # Resolve and load skim
    resolved_skim = _resolve_skim(skim_file, config.skim_file, run_dir)
    skim_matrix: Optional[np.ndarray] = None
    skim_zone_map: Optional[dict[int, int]] = None
    if resolved_skim:
        try:
            import openmatrix as omx

            f = omx.open_file(resolved_skim)
            skim_matrix = np.array(f[config.skim_matrix])
            mappings = f.list_mappings()
            if mappings:
                mapping_name = mappings[0]
                raw_map = f.mapping(mapping_name)
                norm_map: dict[int, int] = {}
                for k, v in raw_map.items():
                    key = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else k
                    try:
                        norm_map[int(key)] = int(v)
                    except Exception:
                        continue
                skim_zone_map = norm_map if norm_map else None
                print(
                    f"[read_run] Loaded skim mapping '{mapping_name}' with {len(norm_map)} zones."
                )
            f.close()
            print(
                f"[read_run] Loaded skim matrix '{config.skim_matrix}' from {resolved_skim}"
            )
        except Exception as e:
            print(f"Warning: could not read skim '{resolved_skim}': {e}")
    else:
        print(f"[read_run] No skim configured for run '{label}'.")

    return RunData(
        label=label,
        run_dir=str(run_dir),
        skim_file=resolved_skim,
        hh=hh,
        per=per,
        tours=tours,
        trips=trips,
        joint_participants=joint_parts,
        land_use=land_use,
        skim_matrix=skim_matrix,
        skim_zone_map=skim_zone_map,
        hh_weight_col=hh_weight_col or None,
        person_weight_col=person_weight_col or None,
        trip_weight_col=trip_weight_col or None,
    )


# ---------------------------------------------------------------------------
# prepare_data
# ---------------------------------------------------------------------------


def prepare_data(rd: RunData, config: Config) -> RunData:
    """Enrich RunData with derived columns needed by summary functions.

    Weight computation (via compute_weights()):
    - HH: explicit hh_weight_col > 1/sample_rate > 1.0
    - Person: explicit person_weight_col > inherit HH weight
    - Trip: explicit trip_weight_col > inherit person weight
    - Tour: avg(trip weight) if trip_weight_col set, else inherit person weight

    Other enrichment:
    - HH: HHVEH (capped), HHSIZE (capped), WORKERS, ADULTS
    - Persons: HGEO/WGEO (if geography enabled), distance_to_work/school (if skim)
    - Tours: HHVEH/WORKERS/AUTOSUFF, stop_frequency parsed, NUMBER_HH,
             OTAZ/DTAZ (if use_maz), SKIMDIST (if skim), start_hour/end_hour/tourdur
    - Trips: tour join, OTAZ/DTAZ, od_dist, depart_hour, stops, out_dir_dist

    What this does NOT do (by design):
    - No numeric code mappings for purpose/mode/category — raw strings used as-is
    - No zone crosswalk file — geography comes directly from the land_use column
    """
    skim = rd.skim_matrix
    skim_map = rd.skim_zone_map
    land_use = rd.land_use
    print(f"[prepare_data] Starting: {rd.label}")

    # ------------------------------------------------------------------
    # Step 0: Compute all finalweights before enrichment
    # ------------------------------------------------------------------
    hh, per, tours, trips = compute_weights(
        rd.hh,
        rd.per,
        rd.tours,
        rd.trips,
        config,
        hh_weight_col=rd.hh_weight_col,
        person_weight_col=rd.person_weight_col,
        trip_weight_col=rd.trip_weight_col,
    )
    print(f"[prepare_data] Weights ready for '{rd.label}'")

    # ------------------------------------------------------------------
    # Build MAZ→TAZ lookup from land_use (if use_maz)
    # ------------------------------------------------------------------
    if config.use_maz:
        print(f"[prepare_data] Building MAZ->TAZ lookup for '{rd.label}'")
        maz_taz = (
            land_use.select([config.maz_col, config.taz_col])
            .rename({config.maz_col: "_maz", config.taz_col: "_taz"})
            .unique("_maz")
        )
    else:
        maz_taz = None  # zone IDs in outputs are already TAZs

    # ------------------------------------------------------------------
    # Build zone→geography lookup from land_use (if geography enabled)
    # ------------------------------------------------------------------
    zone_geo: Optional[pl.DataFrame] = None
    if config.geography_enabled and config.geography_landuse_col:
        print(
            f"[prepare_data] Applying geography labels from '{config.geography_landuse_col}'"
        )
        geo_col = config.geography_landuse_col
        zone_col = config.taz_col if config.use_maz else config.maz_col
        geo_lu = (
            land_use.select([zone_col, geo_col])
            .rename({zone_col: "_taz"})
            .unique("_taz")
        )
        if config.geography_mapping:
            geo_lu = geo_lu.with_columns(
                config.apply_geo_mapping(pl.col(geo_col)).alias(geo_col)
            )
        zone_geo = geo_lu  # columns: _taz, <geo_col>

    def _to_taz(df: pl.DataFrame, zone_col: str, out_col: str) -> pl.DataFrame:
        """Convert a MAZ zone column to TAZ (or just alias if use_maz=False)."""
        if not config.use_maz:
            if zone_col in df.columns:
                return df.with_columns(pl.col(zone_col).alias(out_col))
            return df
        if maz_taz is None or zone_col not in df.columns:
            return df
        return df.join(
            maz_taz.rename({"_maz": zone_col, "_taz": out_col}), on=zone_col, how="left"
        ).with_columns(pl.coalesce([pl.col(out_col), pl.col(zone_col)]).alias(out_col))

    def _add_geo(df: pl.DataFrame, taz_col: str, out_col: str) -> pl.DataFrame:
        """Add a geography label column by joining on TAZ."""
        if zone_geo is None or taz_col not in df.columns:
            return df
        geo_col = config.geography_landuse_col
        return df.join(
            zone_geo.rename({"_taz": taz_col, geo_col: out_col}), on=taz_col, how="left"
        )

    # ------------------------------------------------------------------
    # Households  (finalweight already set by compute_weights)
    # ------------------------------------------------------------------
    ao_col = config.col_auto_ownership
    if ao_col in hh.columns:
        hh = hh.with_columns(pl.col(ao_col).clip(0, 4).alias("HHVEH"))

    sz_col = config.col_hhsize
    if sz_col in hh.columns:
        hh = hh.with_columns(pl.col(sz_col).clip(1, 5).alias("HHSIZE"))

    if config.col_num_workers in hh.columns:
        hh = hh.with_columns(pl.col(config.col_num_workers).alias("WORKERS"))
    if config.col_num_adults in hh.columns:
        hh = hh.with_columns(pl.col(config.col_num_adults).alias("ADULTS"))

    hh = _to_taz(hh, "home_zone_id", "home_taz")
    hh = _add_geo(hh, "home_taz", "HGEO")

    # ------------------------------------------------------------------
    # Persons  (finalweight already set by compute_weights)
    # ------------------------------------------------------------------
    if "home_zone_id" not in per.columns:
        print(
            f"Warning: 'home_zone_id' column not found in persons for run '{rd.label}'. Merging from household_id."
        )
        per = per.join(
            hh.select(["household_id", "home_zone_id"]), on="household_id", how="left"
        )

    per = _to_taz(per, "home_zone_id", "home_taz")
    per = _to_taz(per, "workplace_zone_id", "work_taz")
    per = _to_taz(per, "school_zone_id", "school_taz")
    per = _add_geo(per, "home_taz", "HGEO")
    per = _add_geo(per, "work_taz", "WGEO")

    if skim is not None:
        print(f"[prepare_data] Computing person skim distances for '{rd.label}'")
        if "home_taz" in per.columns and "work_taz" in per.columns:
            o = per["home_taz"].fill_null(0).to_numpy()
            d = per["work_taz"].fill_null(0).to_numpy()
            per = per.with_columns(
                pl.Series("distance_to_work", _skim_lookup(skim, o, d, skim_map))
            )
        if "home_taz" in per.columns and "school_taz" in per.columns:
            o = per["home_taz"].fill_null(0).to_numpy()
            d = per["school_taz"].fill_null(0).to_numpy()
            per = per.with_columns(
                pl.Series("distance_to_school", _skim_lookup(skim, o, d, skim_map))
            )

    if "mandatory_tour_frequency" in per.columns and "imf_choice" not in per.columns:
        per = per.with_columns(
            pl.when(pl.col("mandatory_tour_frequency") == "work1")
            .then(1)
            .when(pl.col("mandatory_tour_frequency") == "work2")
            .then(2)
            .when(pl.col("mandatory_tour_frequency") == "school1")
            .then(3)
            .when(pl.col("mandatory_tour_frequency") == "school2")
            .then(4)
            .when(pl.col("mandatory_tour_frequency") == "work_and_school")
            .then(5)
            .otherwise(0)
            .alias("imf_choice")
        )

    # ------------------------------------------------------------------
    # Tours  (finalweight already set by compute_weights)
    # Join HH cols for AUTOSUFF computation — NOT finalweight
    # ------------------------------------------------------------------
    hh_for_tours = [
        c for c in ["household_id", "HHVEH", "WORKERS", "ADULTS"] if c in hh.columns
    ]
    tours = tours.join(hh.select(hh_for_tours), on="household_id", how="left")

    if "HHVEH" in tours.columns and "WORKERS" in tours.columns:
        tours = tours.with_columns(
            pl.when(pl.col("HHVEH") == 0)
            .then(0)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") < pl.col("WORKERS")))
            .then(1)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") >= pl.col("WORKERS")))
            .then(2)
            .otherwise(0)
            .alias("AUTOSUFF")
        )

    if "stop_frequency" in tours.columns:
        tours = tours.with_columns(
            [
                pl.col("stop_frequency")
                .cast(pl.Utf8)
                .str.split("out_")
                .list.first()
                .cast(pl.Int32)
                .alias("num_ob_stops"),
                pl.col("stop_frequency")
                .cast(pl.Utf8)
                .str.split("out_")
                .list.last()
                .str.replace("in", "", literal=True)
                .cast(pl.Int32)
                .alias("num_ib_stops"),
            ]
        ).with_columns(
            (pl.col("num_ob_stops") + pl.col("num_ib_stops")).alias("num_tot_stops")
        )

    tours = _to_taz(tours, "origin", "OTAZ")
    tours = _to_taz(tours, "destination", "DTAZ")

    # if "primary_purpose" in tours.columns and tours["primary_purpose"].is_numeric():

    if skim is not None and "OTAZ" in tours.columns and "DTAZ" in tours.columns:
        print(f"[prepare_data] Computing tour skim distances for '{rd.label}'")
        o = tours["OTAZ"].fill_null(0).to_numpy()
        d = tours["DTAZ"].fill_null(0).to_numpy()
        tours = tours.with_columns(
            pl.Series("SKIMDIST", _skim_lookup(skim, o, d, skim_map))
        )
    elif "SKIMDIST" not in tours.columns:
        tours = tours.with_columns(pl.lit(0.0).alias("SKIMDIST"))

    if "tour_id" in tours.columns and "person_id" in rd.joint_participants.columns:
        party_size = rd.joint_participants.group_by("tour_id").agg(
            pl.len().alias("NUMBER_HH")
        )
        tours = tours.join(party_size, on="tour_id", how="left")
    if "NUMBER_HH" not in tours.columns:
        tours = tours.with_columns(pl.lit(1).alias("NUMBER_HH"))
    tours = tours.with_columns(pl.col("NUMBER_HH").fill_null(1))

    if "start" in tours.columns and "start_hour" not in tours.columns:
        tours = tours.with_columns(pl.col("start").alias("start_hour"))
    if "end" in tours.columns and "end_hour" not in tours.columns:
        tours = tours.with_columns(pl.col("end").alias("end_hour"))
    if "duration" in tours.columns and "tourdur" not in tours.columns:
        tours = tours.with_columns(pl.col("duration").alias("tourdur"))
    elif (
        "start_hour" in tours.columns
        and "end_hour" in tours.columns
        and "tourdur" not in tours.columns
    ):
        tours = tours.with_columns(
            (pl.col("end_hour") - pl.col("start_hour")).alias("tourdur")
        )

    # ------------------------------------------------------------------
    # Trips  (finalweight already set by compute_weights)
    # Join tour cols for purpose/mode context — NOT finalweight
    # ------------------------------------------------------------------
    tour_join_cols = [
        c
        for c in [
            "tour_id",
            "AUTOSUFF",
            "NUMBER_HH",
            "primary_purpose",
            "tour_mode",
            "tour_category",
        ]
        if c in tours.columns
    ]
    trips = trips.join(
        tours.select(tour_join_cols).rename({"NUMBER_HH": "num_participants"}),
        on="tour_id",
        how="left",
        suffix="_tour",
    )
    for col in ["primary_purpose", "tour_mode", "tour_category"]:
        tour_col = f"{col}_tour"
        if tour_col in trips.columns and col in trips.columns:
            trips = trips.drop(tour_col)
        elif tour_col in trips.columns:
            trips = trips.rename({tour_col: col})

    if "HHVEH" not in trips.columns:
        trips = trips.join(
            hh.select(["household_id", "HHVEH", "WORKERS"]),
            on="household_id",
            how="left",
        )
    if (
        "AUTOSUFF" not in trips.columns
        and "HHVEH" in trips.columns
        and "WORKERS" in trips.columns
    ):
        trips = trips.with_columns(
            pl.when(pl.col("HHVEH") == 0)
            .then(0)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") < pl.col("WORKERS")))
            .then(1)
            .when((pl.col("HHVEH") > 0) & (pl.col("HHVEH") >= pl.col("WORKERS")))
            .then(2)
            .otherwise(0)
            .alias("AUTOSUFF")
        )

    trips = _to_taz(trips, "origin", "OTAZ")
    trips = _to_taz(trips, "destination", "DTAZ")
    if skim is not None and "OTAZ" in trips.columns and "DTAZ" in trips.columns:
        print(f"[prepare_data] Computing trip skim distances for '{rd.label}'")
        o = trips["OTAZ"].fill_null(0).to_numpy()
        d = trips["DTAZ"].fill_null(0).to_numpy()
        trips = trips.with_columns(
            pl.Series("od_dist", _skim_lookup(skim, o, d, skim_map))
        )
    elif "od_dist" not in trips.columns:
        trips = trips.with_columns(pl.lit(0.0).alias("od_dist"))

    if "depart" in trips.columns and "depart_hour" not in trips.columns:
        trips = trips.with_columns(pl.col("depart").alias("depart_hour"))
    elif "depart_hour" not in trips.columns:
        trips = trips.with_columns(pl.lit(1).alias("depart_hour"))

    if "outbound" in trips.columns and "inbound" not in trips.columns:
        trips = trips.with_columns(
            pl.when(
                pl.col("outbound")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["false", "0"])
            )
            .then(1)
            .otherwise(0)
            .alias("inbound")
        )

    if "trip_num" in trips.columns and "outbound" in trips.columns:
        max_trip = trips.group_by(["tour_id", "outbound"]).agg(
            pl.col("trip_num").max().alias("max_trip_num")
        )
        trips = trips.join(max_trip, on=["tour_id", "outbound"], how="left")
        trips = trips.with_columns(
            pl.when(pl.col("trip_num") < pl.col("max_trip_num"))
            .then(1)
            .otherwise(0)
            .alias("stops")
        )
    elif "stops" not in trips.columns:
        trips = trips.with_columns(pl.lit(0).alias("stops"))

    if "out_dir_dist" not in trips.columns:
        if (
            skim is not None
            and "OTAZ" in trips.columns
            and "DTAZ" in trips.columns
            and "inbound" in trips.columns
        ):
            tour_od = tours.select(["tour_id", "OTAZ", "DTAZ"]).rename(
                {"OTAZ": "tour_OTAZ", "DTAZ": "tour_DTAZ"}
            )
            trips = trips.join(tour_od, on="tour_id", how="left")
            finaldest = np.where(
                trips["inbound"].to_numpy() == 0,
                trips["tour_DTAZ"].fill_null(0).to_numpy(),
                trips["tour_OTAZ"].fill_null(0).to_numpy(),
            )
            o = trips["OTAZ"].fill_null(0).to_numpy()
            d = trips["DTAZ"].fill_null(0).to_numpy()
            od = _skim_lookup(skim, o, d, skim_map)
            os_ = _skim_lookup(skim, o, finaldest, skim_map)
            sd = _skim_lookup(skim, d, finaldest, skim_map)
            trips = trips.with_columns(
                pl.Series("out_dir_dist", (os_ + sd - od).clip(0))
            )
        else:
            trips = trips.with_columns(pl.lit(0.0).alias("out_dir_dist"))

    print(f"[prepare_data] Complete: {rd.label}")
    return RunData(
        label=rd.label,
        run_dir=rd.run_dir,
        skim_file=rd.skim_file,
        hh=hh,
        per=per,
        tours=tours,
        trips=trips,
        joint_participants=rd.joint_participants,
        land_use=land_use,
        skim_matrix=skim,
        skim_zone_map=skim_map,
        hh_weight_col=rd.hh_weight_col,
        person_weight_col=rd.person_weight_col,
        trip_weight_col=rd.trip_weight_col,
    )
