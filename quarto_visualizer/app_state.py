"""Helpers for loading prepared runs and Quarto summary bundles."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from quarto_visualizer.summary_bundle import PreparedRuns, SummaryBundlePair, build_summary_bundle_pair
from summarize.reader import Config, RunData, prepare_data, read_run

RunEntry = dict[str, Any]


@dataclass(frozen=True)
class LoadedAppState:
    config: Config
    runs: PreparedRuns
    bundles: SummaryBundlePair


def find_config_path(
    start: str | Path | None = None,
    *,
    env_var: str = "ACTIVITYSIM_VIS_CONFIG",
) -> Path:
    """Find ``config.yaml`` from an explicit path, env var, or parent search."""
    if start is not None:
        candidate = Path(start)
        if candidate.is_dir():
            candidate = candidate / "config.yaml"
        if candidate.exists():
            return candidate.resolve()
        raise FileNotFoundError(f"Could not find config at {candidate}")

    env_value = os.environ.get(env_var)
    if env_value:
        candidate = Path(env_value)
        if candidate.is_dir():
            candidate = candidate / "config.yaml"
        if candidate.exists():
            return candidate.resolve()
        raise FileNotFoundError(f"Env var {env_var} pointed to missing config: {candidate}")

    for base in (Path.cwd(), *Path.cwd().parents):
        candidate = base / "config.yaml"
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError("Could not find config.yaml in the current directory or any parent directory.")


def resolve_run_entries(
    config: Config,
    *,
    cli_runs: list[tuple[str, str]] | None = None,
    cli_run_skims: list[str] | None = None,
) -> list[RunEntry]:
    """Resolve run entries using CLI overrides when provided."""
    if cli_runs:
        run_entries: list[RunEntry] = []
        skims = cli_run_skims or []
        for idx, (run_dir, label) in enumerate(cli_runs):
            skim = skims[idx] if idx < len(skims) else None
            if skim in ("", "null", "None"):
                skim = None
            run_entries.append({"dir": run_dir, "label": label, "skim_file": skim})
        return run_entries
    return list(config.runs)


def load_prepared_runs(config: Config, run_entries: list[RunEntry]) -> PreparedRuns:
    """Read and prepare all configured runs."""
    runs: list[tuple[str, RunData]] = []
    for entry in run_entries:
        run_dir = entry.get("dir", "")
        label = entry.get("label", Path(str(run_dir)).name)
        skim = entry.get("skim_file") or None

        print(f"[app-state] Reading run: {label!r} from {run_dir}")
        rd = read_run(
            run_dir,
            config,
            label=label,
            skim_file=skim,
            hh_weight_col=entry.get("hh_weight_col") or None,
            person_weight_col=entry.get("person_weight_col") or None,
            trip_weight_col=entry.get("trip_weight_col") or None,
        )
        rd = prepare_data(rd, config)
        print(f"[app-state] Prepared run: {label!r}")
        runs.append((label, rd))
    return tuple(runs)


def load_app_state(
    config_path: str | Path,
    *,
    cli_runs: list[tuple[str, str]] | None = None,
    cli_run_skims: list[str] | None = None,
) -> LoadedAppState:
    """Load config, prepared runs, and weighted/unweighted bundles together."""
    config = Config.from_yaml(config_path)
    run_entries = resolve_run_entries(config, cli_runs=cli_runs, cli_run_skims=cli_run_skims)
    runs = load_prepared_runs(config, run_entries)
    bundles = build_summary_bundle_pair(runs, config)
    return LoadedAppState(config=config, runs=runs, bundles=bundles)
