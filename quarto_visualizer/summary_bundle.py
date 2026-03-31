"""UI-neutral summary bundles for the Quarto + Shiny migration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl

from summarize import demographics, mandatory, stops, totals, tour_mode, tour_tod, tours, trips
from summarize.reader import Config, RunData

RunFrame = tuple[str, pl.DataFrame]
RunFrameList = tuple[RunFrame, ...]
RunTLFD = tuple[str, dict[str, pl.DataFrame]]
RunTLFDList = tuple[RunTLFD, ...]
PreparedRuns = tuple[tuple[str, RunData], ...]
WeightMode = Literal["weighted", "unweighted"]


@dataclass(frozen=True)
class RunMetadata:
    label: str
    run_dir: str
    skim_file: str | None


@dataclass(frozen=True)
class OverviewSummaries:
    totals: RunFrameList
    person_type: RunFrameList
    hh_size: RunFrameList


@dataclass(frozen=True)
class LongTermSummaries:
    auto_ownership: RunFrameList
    tlfd: RunTLFDList
    wfh: RunFrameList
    telecommute: RunFrameList
    mandatory_tour_lengths: RunFrameList
    geo_flows: RunFrameList


@dataclass(frozen=True)
class TourSummarySummaries:
    dap: RunFrameList
    mandatory_tour_frequency: RunFrameList
    individual_nm: RunFrameList


@dataclass(frozen=True)
class JointToursSummaries:
    joint_tour_frequency: RunFrameList
    composition: RunFrameList
    party_size: RunFrameList
    household_size: RunFrameList


@dataclass(frozen=True)
class DestinationSummaries:
    purposes: tuple[str, ...]
    distance_by_purpose: dict[str, RunFrameList]
    average_distance_display: pl.DataFrame


@dataclass(frozen=True)
class TourTodSummaries:
    profiles: RunFrameList


@dataclass(frozen=True)
class TourModeSummaries:
    detail: RunFrameList
    grouped: RunFrameList


@dataclass(frozen=True)
class StopFrequencySummaries:
    stop_frequency: RunFrameList
    stop_purpose: RunFrameList


@dataclass(frozen=True)
class StopLocationSummaries:
    profiles: RunFrameList


@dataclass(frozen=True)
class StopTimingSummaries:
    profiles: RunFrameList


@dataclass(frozen=True)
class TripModeSummaries:
    profiles: RunFrameList


@dataclass(frozen=True)
class SummaryBundle:
    mode: WeightMode
    runs: tuple[RunMetadata, ...]
    overview: OverviewSummaries
    long_term: LongTermSummaries
    tour_summary: TourSummarySummaries
    joint_tours: JointToursSummaries
    destination: DestinationSummaries
    tour_tod: TourTodSummaries
    tour_mode: TourModeSummaries
    stop_freq: StopFrequencySummaries
    stop_location: StopLocationSummaries
    stop_timing: StopTimingSummaries
    trip_mode: TripModeSummaries


@dataclass(frozen=True)
class SummaryBundlePair:
    weighted: SummaryBundle
    unweighted: SummaryBundle


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


def build_summary_bundle(
    runs: list[tuple[str, RunData]] | PreparedRuns,
    config: Config,
    *,
    mode: WeightMode = "weighted",
) -> SummaryBundle:
    """Build all page-level summaries for one weighting mode."""
    prepared_runs = _prepare_runs_for_mode(runs, mode)
    destination_purposes = _destination_purposes(prepared_runs)

    return SummaryBundle(
        mode=mode,
        runs=tuple(
            RunMetadata(label=label, run_dir=rd.run_dir, skim_file=rd.skim_file)
            for label, rd in prepared_runs
        ),
        overview=OverviewSummaries(
            totals=_frames((label, totals.system_totals(rd, config)) for label, rd in prepared_runs),
            person_type=_frames((label, demographics.person_type(rd, config)) for label, rd in prepared_runs),
            hh_size=_frames((label, demographics.hh_size(rd)) for label, rd in prepared_runs),
        ),
        long_term=LongTermSummaries(
            auto_ownership=_frames((label, demographics.auto_ownership(rd)) for label, rd in prepared_runs),
            tlfd=tuple((label, mandatory.tlfd(rd, config)) for label, rd in prepared_runs),
            wfh=_frames((label, mandatory.wfh(rd, config)) for label, rd in prepared_runs),
            telecommute=_frames((label, mandatory.telecommute(rd)) for label, rd in prepared_runs),
            mandatory_tour_lengths=_frames(
                (label, mandatory.mand_tour_lengths(rd, config)) for label, rd in prepared_runs
            ),
            geo_flows=_frames((label, mandatory.geo_flows(rd, config)) for label, rd in prepared_runs),
        ),
        tour_summary=TourSummarySummaries(
            dap=_frames((label, tours.dap_summary(rd, config)) for label, rd in prepared_runs),
            mandatory_tour_frequency=_frames(
                (label, tours.mandatory_tour_freq(rd, config)) for label, rd in prepared_runs
            ),
            individual_nm=_frames((label, tours.indiv_nm_summary(rd, config)) for label, rd in prepared_runs),
        ),
        joint_tours=JointToursSummaries(
            joint_tour_frequency=_frames((label, tours.joint_tour_freq(rd)) for label, rd in prepared_runs),
            composition=_frames((label, tours.joint_composition(rd)) for label, rd in prepared_runs),
            party_size=_frames((label, tours.joint_party_size(rd)) for label, rd in prepared_runs),
            household_size=_frames((label, tours.joint_tours_hhsize(rd)) for label, rd in prepared_runs),
        ),
        destination=DestinationSummaries(
            purposes=destination_purposes,
            distance_by_purpose={
                purpose: _frames(
                    (label, _nm_dist_by_purpose(rd, purpose if purpose != "All NM" else None))
                    for label, rd in prepared_runs
                )
                for purpose in destination_purposes
            },
            average_distance_display=_destination_average_table(prepared_runs, destination_purposes),
        ),
        tour_tod=TourTodSummaries(
            profiles=_frames((label, tour_tod.tod_profiles(rd)) for label, rd in prepared_runs),
        ),
        tour_mode=TourModeSummaries(
            detail=_frames((label, tour_mode.tour_mode_profile(rd, config)) for label, rd in prepared_runs),
            grouped=_frames((label, tour_mode.grouped_tour_mode_profile(rd, config)) for label, rd in prepared_runs),
        ),
        stop_freq=StopFrequencySummaries(
            stop_frequency=_frames((label, stops.stop_freq(rd)) for label, rd in prepared_runs),
            stop_purpose=_frames((label, stops.stop_purpose_by_tour_purpose(rd)) for label, rd in prepared_runs),
        ),
        stop_location=StopLocationSummaries(
            profiles=_frames((label, stops.stop_location(rd)) for label, rd in prepared_runs),
        ),
        stop_timing=StopTimingSummaries(
            profiles=_frames((label, stops.stop_timing(rd)) for label, rd in prepared_runs),
        ),
        trip_mode=TripModeSummaries(
            profiles=_frames((label, trips.trip_mode_profile(rd, config)) for label, rd in prepared_runs),
        ),
    )


def build_summary_bundle_pair(
    runs: list[tuple[str, RunData]] | PreparedRuns,
    config: Config,
) -> SummaryBundlePair:
    """Build weighted and unweighted bundles from the same prepared runs."""
    return SummaryBundlePair(
        weighted=build_summary_bundle(runs, config, mode="weighted"),
        unweighted=build_summary_bundle(runs, config, mode="unweighted"),
    )


def _prepare_runs_for_mode(
    runs: list[tuple[str, RunData]] | PreparedRuns,
    mode: WeightMode,
) -> PreparedRuns:
    if mode == "weighted":
        return tuple((label, rd) for label, rd in runs)
    return tuple((label, strip_weights(rd)) for label, rd in runs)


def _frames(items) -> RunFrameList:
    return tuple(items)


def _destination_purposes(runs: PreparedRuns) -> tuple[str, ...]:
    purposes: set[str] = set()
    if runs:
        _, rd = runs[0]
        tours_df = rd.tours
        if "tour_category" in tours_df.columns and "primary_purpose" in tours_df.columns:
            nm_tours = tours_df.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"]))
            purposes.update(str(p) for p in nm_tours["primary_purpose"].drop_nulls().unique().to_list())
    return ("All NM", *sorted(purposes))


def _nm_dist_by_purpose(rd: RunData, purpose: str | None) -> pl.DataFrame:
    """Mirror the current Panel destination-page chart logic in a UI-neutral function."""
    tours_df = rd.tours
    if "tour_category" not in tours_df.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    indiv = tours_df.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork"]))
    joint = tours_df.filter(pl.col("tour_category") == "joint").with_columns(
        (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
    )
    joint = (
        joint.rename({"wgt": "finalweight"})
        if "finalweight" not in joint.columns
        else joint.with_columns(pl.col("wgt").alias("finalweight"))
    )

    if purpose is None or purpose == "All NM":
        combined = pl.concat(
            [
                indiv.select(["SKIMDIST", "finalweight"]) if "SKIMDIST" in indiv.columns else pl.DataFrame(),
                joint.select(["SKIMDIST", "finalweight"]) if "SKIMDIST" in joint.columns else pl.DataFrame(),
            ]
        )
    else:
        if "primary_purpose" not in tours_df.columns:
            return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})
        combined = pl.concat(
            [
                indiv.filter(pl.col("primary_purpose") == purpose).select(["SKIMDIST", "finalweight"])
                if "SKIMDIST" in indiv.columns
                else pl.DataFrame(),
                joint.filter(pl.col("primary_purpose") == purpose).select(["SKIMDIST", "finalweight"])
                if "SKIMDIST" in joint.columns
                else pl.DataFrame(),
            ]
        )

    if len(combined) == 0 or "SKIMDIST" not in combined.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    combined = combined.with_columns(pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin"))
    return (
        combined.group_by("distbin")
        .agg(pl.col("finalweight").sum().alias("freq"))
        .join(pl.DataFrame({"distbin": list(range(41))}), on="distbin", how="right")
        .fill_null(0)
        .sort("distbin")
    )


def _destination_average_table(runs: PreparedRuns, purposes: tuple[str, ...]) -> pl.DataFrame:
    """Mirror the current Panel destination-page average-distance table logic.

    This intentionally matches the page's current displayed behavior, including
    the fact that it does not share the exact same filtering logic as the chart.
    """
    rows: list[dict[str, object]] = []
    table_purposes = [p for p in purposes if p != "All NM"]
    for purp in table_purposes:
        row: dict[str, object] = {"Purpose": purp}
        for run_label, rd in runs:
            if "SKIMDIST" in rd.tours.columns and "primary_purpose" in rd.tours.columns:
                sub = rd.tours.filter(pl.col("primary_purpose") == purp)
                if len(sub) > 0:
                    wgt = sub["finalweight"].to_numpy()
                    dist = sub["SKIMDIST"].to_numpy()
                    mask = dist == dist
                    if mask.sum() > 0 and wgt[mask].sum() > 0:
                        row[run_label] = round(float((dist[mask] * wgt[mask]).sum() / wgt[mask].sum()), 2)
                        continue
            row[run_label] = None
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()
