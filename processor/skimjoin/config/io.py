from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def resolve_config_paths(config_data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(config_data)
    if "skim_files" in resolved:
        resolved["skim_files"] = [
            _resolve_path(base_dir, raw_path)
            for raw_path in resolved.get("skim_files", [])
        ]

    project = dict(resolved.get("project") or {})
    if "skim_files" in project and project["skim_files"] is not None:
        project["skim_files"] = [
            _resolve_path(base_dir, raw_path) for raw_path in project["skim_files"]
        ]
    for key in ["trips_table", "tours_table", "network_los_file", "output_dir"]:
        if key in project and project[key] is not None:
            project[key] = _resolve_path(base_dir, project[key])
    if project:
        resolved["project"] = project

    activitysim = dict(resolved.get("activitysim") or {})
    for key in ["trips_table", "tours_table"]:
        if key in activitysim and activitysim[key] is not None:
            activitysim[key] = _resolve_path(base_dir, activitysim[key])
    resolved["activitysim"] = activitysim
    return resolved


def load_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_data, dict):
        raise ValueError("skimjoin config file must parse to a mapping.")
    return resolve_config_paths(raw_data, config_path.parent)


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)
