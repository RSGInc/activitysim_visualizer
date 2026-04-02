"""Compatibility wrappers around the summary cache registry."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from summarize.cache import (
    build_mode_summaries,
    build_run_keys,
    build_summaries,
    create_summary_run,
    normalize_weighting_modes,
    strip_weights,
    write_summary_run_cache,
)
from summarize.reader import Config, RunData


def write_summary_bundle(
    runs: list[tuple[str, RunData]],
    config: Config,
    output_dir: str | Path,
    *,
    include_unweighted: bool = True,
    config_path: str | None = None,
) -> Path:
    """Write a multi-run summary bundle under ``output_dir``.

    This helper now writes the same per-run cache layout used by the main CLI,
    plus a lightweight root manifest for bundle-style workflows.
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    weighting_modes = normalize_weighting_modes(
        ["weighted"] + (["unweighted"] if include_unweighted else [])
    )
    run_keys = build_run_keys([label for label, _ in runs])
    run_entries: list[dict[str, object]] = []

    for (label, rd), run_key in zip(runs, run_keys):
        summary_run = create_summary_run(
            label=label,
            run_key=run_key,
            summaries_by_mode=build_mode_summaries(
                rd,
                config,
                weighting_modes=weighting_modes,
            ),
            source_run_dir=str(rd.run_dir),
            raw_run=rd,
        )
        write_summary_run_cache(summary_run, config, output_root=root)
        run_entries.append(
            {
                "label": label,
                "run_key": run_key,
                "run_dir": rd.run_dir,
                "skim_file": rd.skim_file,
            }
        )

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "activitysim-visualizer-summary-bundle",
        "config_name": config.name,
        "dashboard_title": config.dashboard_title,
        "config_path": config_path,
        "run_count": len(runs),
        "weighting_modes": weighting_modes,
        "runs": run_entries,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return root


__all__ = [
    "build_summaries",
    "strip_weights",
    "write_summary_bundle",
]
