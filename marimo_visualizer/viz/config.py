"""Configuration loading and normalization helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Config, DEFAULT_FILE_STEMS, DEFAULT_RUN_COLORS, RunSpec


def load_config(path: str | Path) -> Config:
    """Load a visualizer configuration file from YAML."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return config_from_mapping(raw)


def config_from_mapping(raw: dict[str, Any]) -> Config:
    """Normalize a raw YAML mapping into a Config dataclass."""
    files = dict(raw.get("files", {}))
    for key, value in DEFAULT_FILE_STEMS.items():
        files.setdefault(key, value)

    cols = raw.get("columns", {})
    zones = raw.get("zones", {})
    geo = raw.get("geography", {})
    skim_cfg = raw.get("skim", {})
    modes_cfg = raw.get("modes", {})

    geo_enabled = bool(geo.get("enabled", False))
    geo_mapping = None
    if geo_enabled and "mapping" in geo:
        geo_mapping = {str(key): str(value) for key, value in geo["mapping"].items()}

    run_specs = [RunSpec.from_mapping(entry) for entry in raw.get("runs", [])]

    return Config(
        name=raw.get("name", ""),
        dashboard_title=raw.get("dashboard_title", "ActivitySim Visualizer"),
        run_colors=list(raw.get("run_colors", DEFAULT_RUN_COLORS)),
        files=files,
        col_ptype=cols.get("ptype", "ptype"),
        col_hhsize=cols.get("hhsize", "hhsize"),
        col_auto_ownership=cols.get("auto_ownership", "auto_ownership"),
        col_num_workers=cols.get("num_workers", "num_workers"),
        col_num_adults=cols.get("num_adults", "num_adults"),
        col_sample_rate=cols.get("sample_rate") or None,
        person_type_labels={str(key): str(value) for key, value in raw.get("person_types", {}).items()} or None,
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
        runs=run_specs,
    )
