"""CSV export helpers for the marimo ActivitySim visualizer."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .models import Config, PreparedRuns, RunData
from .summaries import demographics, mandatory, stops, totals, tour_mode, tour_tod, tours, trips


def build_run_summaries(run_data: RunData, config: Config) -> dict[str, pl.DataFrame]:
    """Build the standard CSV summary outputs for a prepared run."""
    tlfd = mandatory.tlfd(run_data, config)
    return {
        "autoOwnership": demographics.auto_ownership(run_data),
        "pertypeDistbn": demographics.person_type(run_data, config),
        "hhSizeDist": demographics.hh_size(run_data),
        "workTLFD": tlfd.get("work", pl.DataFrame()),
        "univTLFD": tlfd.get("univ", pl.DataFrame()),
        "schlTLFD": tlfd.get("schl", pl.DataFrame()),
        "mandTourLengths": mandatory.mand_tour_lengths(run_data, config),
        "wfh_summary": mandatory.wfh(run_data, config),
        "telecommuteFrequency": mandatory.telecommute(run_data),
        "geoFlows": mandatory.geo_flows(run_data, config),
        "dapSummary_vis": tours.dap_summary(run_data, config),
        "mtfSummary_vis": tours.mandatory_tour_freq(run_data, config),
        "inmSummary_vis": tours.indiv_nm_summary(run_data, config),
        "nm_tour_rates": tours.nm_tour_rates(run_data, config),
        "jtf": tours.joint_tour_freq(run_data),
        "jointComp": tours.joint_composition(run_data),
        "jointPartySize": tours.joint_party_size(run_data),
        "jointToursHHSize": tours.joint_tours_hhsize(run_data),
        "tmodeProfile_vis": tour_mode.tour_mode_profile(run_data, config),
        "todProfile_vis": tour_tod.tod_profiles(run_data),
        "tripModeProfile_vis": trips.trip_mode_profile(run_data, config),
        "stopFreq": stops.stop_freq(run_data),
        "stopPurpose": stops.stop_purpose_by_tour_purpose(run_data),
        "stopLocation": stops.stop_location(run_data),
        "stopTiming": stops.stop_timing(run_data),
        "totals": totals.system_totals(run_data, config),
    }


def write_all(summaries: dict[str, pl.DataFrame], output_dir: str | Path) -> None:
    """Write summary DataFrames to CSV files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for name, df in summaries.items():
        path = output_path / f"{name}.csv"
        df.write_csv(path)
        print(f"  Written: {path}")


def write_prepared_run_summaries(
    prepared_runs: PreparedRuns,
    output_subdir: str = "summary_outputs",
) -> list[Path]:
    """Write standard summary CSVs for each weighted prepared run."""
    written_dirs: list[Path] = []
    for _, run_data in prepared_runs.weighted_runs:
        out_dir = Path(run_data.run_dir) / output_subdir
        summaries = build_run_summaries(run_data, prepared_runs.config)
        write_all(summaries, out_dir)
        written_dirs.append(out_dir)
    return written_dirs
