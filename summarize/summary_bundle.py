"""Reference outputs for freezing current Panel dashboard behavior.

This module intentionally reuses the existing summarize layer and writes its
outputs in a UI-neutral form. The Quarto migration can compare against these
artifacts before replacing the Panel UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path

import polars as pl

from summarize import (
    demographics,
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


def build_summaries(rd: RunData, config: Config) -> dict[str, pl.DataFrame]:
    """Build the same summary set currently written by ``run.py --write-csvs``."""
    tlfd = mandatory.tlfd(rd, config)
    return {
        "autoOwnership": demographics.auto_ownership(rd),
        "pertypeDistbn": demographics.person_type(rd, config),
        "hhSizeDist": demographics.hh_size(rd),
        "workTLFD": tlfd["work"],
        "univTLFD": tlfd["univ"],
        "schlTLFD": tlfd["schl"],
        "mandTourLengths": mandatory.mand_tour_lengths(rd, config),
        "wfh_summary": mandatory.wfh(rd, config),
        "telecommuteFrequency": mandatory.telecommute(rd),
        "geoFlows": mandatory.geo_flows(rd, config),
        "dapSummary_vis": tours.dap_summary(rd, config),
        "mtfSummary_vis": tours.mandatory_tour_freq(rd, config),
        "inmSummary_vis": tours.indiv_nm_summary(rd, config),
        "nm_tour_rates": tours.nm_tour_rates(rd, config),
        "jtf": tours.joint_tour_freq(rd),
        "jointComp": tours.joint_composition(rd),
        "jointPartySize": tours.joint_party_size(rd),
        "jointToursHHSize": tours.joint_tours_hhsize(rd),
        "tmodeProfile_vis": tour_mode.tour_mode_profile(rd, config),
        "todProfile_vis": tour_tod.tod_profiles(rd),
        "tripModeProfile_vis": trips.trip_mode_profile(rd, config),
        "stopFreq": stops.stop_freq(rd),
        "stopPurpose": stops.stop_purpose_by_tour_purpose(rd),
        "stopLocation": stops.stop_location(rd),
        "stopTiming": stops.stop_timing(rd),
        "totals": totals.system_totals(rd, config),
    }


def write_summary_bundle(
    runs: list[tuple[str, RunData]],
    config: Config,
    output_dir: str | Path,
    *,
    include_unweighted: bool = True,
    config_path: str | None = None,
) -> Path:
    """Write weighted and optional unweighted reference summaries plus a manifest."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    run_entries: list[dict[str, object]] = []
    summary_names: list[str] | None = None
    modes = ["weighted"] + (["unweighted"] if include_unweighted else [])

    for idx, (label, rd) in enumerate(runs, start=1):
        run_dir_name = f"{idx:02d}-{_slug(label)}"
        mode_items: list[tuple[str, RunData]] = [("weighted", rd)]
        if include_unweighted:
            mode_items.append(("unweighted", strip_weights(rd)))

        for mode_name, mode_rd in mode_items:
            summaries = build_summaries(mode_rd, config)
            write_all(summaries, root / run_dir_name / mode_name)
            if summary_names is None:
                summary_names = list(summaries.keys())

        run_entries.append(
            {
                "label": label,
                "artifact_dir": run_dir_name,
                "run_dir": rd.run_dir,
                "skim_file": rd.skim_file,
            }
        )

    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "panel-dashboard-reference",
        "config_name": config.name,
        "dashboard_title": config.dashboard_title,
        "config_path": config_path,
        "run_count": len(runs),
        "modes": modes,
        "summary_names": summary_names or [],
        "docs": {
            "behavior_spec": "quarto_visualizer/migration/panel-behavior-spec.md",
            "parity_checklist": "quarto_visualizer/migration/parity-checklist.md",
        },
        "runs": run_entries,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return root


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-_.")
    return slug or "run"


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
