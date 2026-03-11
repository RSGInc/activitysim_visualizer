"""Weighting and derived-column preparation for loaded ActivitySim runs."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import polars as pl

from .config import load_config
from .io import load_runs
from .models import Config, PreparedRuns, RunData, RunSpec


def _skim_lookup(
    skim: np.ndarray,
    otaz: np.ndarray,
    dtaz: np.ndarray,
    zone_map: dict[int, int] | None = None,
) -> np.ndarray:
    """Vectorized skim lookup with support for OMX zone mappings."""
    origin = np.asarray(otaz, dtype=int)
    destination = np.asarray(dtaz, dtype=int)
    if zone_map:
        origin_idx = np.fromiter((zone_map.get(int(zone), -1) for zone in origin), dtype=int, count=len(origin))
        dest_idx = np.fromiter((zone_map.get(int(zone), -1) for zone in destination), dtype=int, count=len(destination))
    else:
        origin_min = int(np.min(origin)) if len(origin) else 0
        dest_min = int(np.min(destination)) if len(destination) else 0
        origin_max = int(np.max(origin)) if len(origin) else 0
        dest_max = int(np.max(destination)) if len(destination) else 0
        if (
            origin_min >= 0
            and dest_min >= 0
            and origin_max < skim.shape[0]
            and dest_max < skim.shape[1]
            and ((origin == 0).any() or (destination == 0).any())
        ):
            origin_idx = origin
            dest_idx = destination
        else:
            origin_idx = origin - 1
            dest_idx = destination - 1

    valid = (
        (origin_idx >= 0)
        & (dest_idx >= 0)
        & (origin_idx < skim.shape[0])
        & (dest_idx < skim.shape[1])
    )
    result = np.zeros(len(origin_idx), dtype=float)
    result[valid] = skim[origin_idx[valid], dest_idx[valid]]
    return result


def compute_weights(
    hh: pl.DataFrame,
    per: pl.DataFrame,
    tours: pl.DataFrame,
    trips: pl.DataFrame,
    config: Config,
    hh_weight_col: str | None = None,
    person_weight_col: str | None = None,
    trip_weight_col: str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Compute and attach `finalweight` to households, persons, tours, and trips."""
    explicit_weight_supplied = any([hh_weight_col, person_weight_col, trip_weight_col])
    sample_rate_col = config.col_sample_rate or ("sample_rate" if "sample_rate" in hh.columns else None)

    if hh_weight_col and hh_weight_col in hh.columns:
        hh = hh.with_columns(pl.col(hh_weight_col).cast(pl.Float64).alias("finalweight"))
    elif (not explicit_weight_supplied) and sample_rate_col and sample_rate_col in hh.columns:
        hh = hh.with_columns((pl.lit(1.0) / pl.col(sample_rate_col).cast(pl.Float64)).alias("finalweight"))
    else:
        hh = hh.with_columns(pl.lit(1.0).alias("finalweight"))

    if person_weight_col and person_weight_col in per.columns:
        per = per.with_columns(pl.col(person_weight_col).cast(pl.Float64).alias("finalweight"))
    else:
        per = (
            per.join(hh.select(["household_id", pl.col("finalweight").alias("_hw")]), on="household_id", how="left")
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    if trip_weight_col and trip_weight_col in trips.columns:
        trips = trips.with_columns(pl.col(trip_weight_col).cast(pl.Float64).alias("finalweight"))
    else:
        if "person_id" in trips.columns:
            trips = (
                trips.join(per.select(["person_id", pl.col("finalweight").alias("_pw")]), on="person_id", how="left")
                .with_columns(pl.col("_pw").fill_null(1.0).alias("finalweight"))
                .drop("_pw")
            )
        else:
            trips = (
                trips.join(hh.select(["household_id", pl.col("finalweight").alias("_hw")]), on="household_id", how="left")
                .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
                .drop("_hw")
            )

    if trip_weight_col and trip_weight_col in trips.columns and "tour_id" in trips.columns:
        tour_avg = trips.group_by("tour_id").agg(pl.col("finalweight").mean().alias("_tw"))
        tours = (
            tours.join(tour_avg, on="tour_id", how="left")
            .with_columns(pl.col("_tw").fill_null(1.0).alias("finalweight"))
            .drop("_tw")
        )
    elif "person_id" in tours.columns:
        tours = (
            tours.join(per.select(["person_id", pl.col("finalweight").alias("_pw")]), on="person_id", how="left")
            .with_columns(pl.col("_pw").fill_null(1.0).alias("finalweight"))
            .drop("_pw")
        )
    else:
        tours = (
            tours.join(hh.select(["household_id", pl.col("finalweight").alias("_hw")]), on="household_id", how="left")
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    return hh, per, tours, trips


def strip_weights(run_data: RunData) -> RunData:
    """Return a copy of RunData with all `finalweight` columns reset to 1.0."""

    def _reset(df: pl.DataFrame) -> pl.DataFrame:
        if "finalweight" in df.columns:
            return df.with_columns(pl.lit(1.0).alias("finalweight"))
        return df

    return RunData(
        label=run_data.label,
        run_dir=run_data.run_dir,
        skim_file=run_data.skim_file,
        hh=_reset(run_data.hh),
        per=_reset(run_data.per),
        tours=_reset(run_data.tours),
        trips=_reset(run_data.trips),
        joint_participants=run_data.joint_participants,
        land_use=run_data.land_use,
        skim_matrix=run_data.skim_matrix,
        skim_zone_map=run_data.skim_zone_map,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )


def prepare_run(run_data: RunData, config: Config) -> RunData:
    """Enrich a loaded run with final weights and derived columns."""
    skim = run_data.skim_matrix
    skim_map = run_data.skim_zone_map
    land_use = run_data.land_use

    hh, per, tours, trips = compute_weights(
        run_data.hh,
        run_data.per,
        run_data.tours,
        run_data.trips,
        config,
        hh_weight_col=run_data.hh_weight_col,
        person_weight_col=run_data.person_weight_col,
        trip_weight_col=run_data.trip_weight_col,
    )

    if config.use_maz:
        maz_taz = (
            land_use.select([config.maz_col, config.taz_col])
            .rename({config.maz_col: "_maz", config.taz_col: "_taz"})
            .unique("_maz")
        )
    else:
        maz_taz = None

    zone_geo: pl.DataFrame | None = None
    if config.geography_enabled and config.geography_landuse_col:
        geo_col = config.geography_landuse_col
        zone_col = config.taz_col if config.use_maz else config.maz_col
        zone_geo = land_use.select([zone_col, geo_col]).rename({zone_col: "_taz"}).unique("_taz")
        if config.geography_mapping:
            zone_geo = zone_geo.with_columns(config.apply_geo_mapping(pl.col(geo_col)).alias(geo_col))

    def _to_taz(df: pl.DataFrame, zone_col: str, out_col: str) -> pl.DataFrame:
        if not config.use_maz:
            if zone_col in df.columns:
                return df.with_columns(pl.col(zone_col).alias(out_col))
            return df
        if maz_taz is None or zone_col not in df.columns:
            return df
        return (
            df.join(maz_taz.rename({"_maz": zone_col, "_taz": out_col}), on=zone_col, how="left")
            .with_columns(pl.coalesce([pl.col(out_col), pl.col(zone_col)]).alias(out_col))
        )

    def _add_geo(df: pl.DataFrame, taz_col: str, out_col: str) -> pl.DataFrame:
        if zone_geo is None or taz_col not in df.columns or config.geography_landuse_col is None:
            return df
        return df.join(
            zone_geo.rename({"_taz": taz_col, config.geography_landuse_col: out_col}),
            on=taz_col,
            how="left",
        )

    if config.col_auto_ownership in hh.columns:
        hh = hh.with_columns(pl.col(config.col_auto_ownership).clip(0, 4).alias("HHVEH"))
    if config.col_hhsize in hh.columns:
        hh = hh.with_columns(pl.col(config.col_hhsize).clip(1, 5).alias("HHSIZE"))
    if config.col_num_workers in hh.columns:
        hh = hh.with_columns(pl.col(config.col_num_workers).alias("WORKERS"))
    if config.col_num_adults in hh.columns:
        hh = hh.with_columns(pl.col(config.col_num_adults).alias("ADULTS"))

    hh = _to_taz(hh, "home_zone_id", "home_taz")
    hh = _add_geo(hh, "home_taz", "HGEO")

    per = _to_taz(per, "home_zone_id", "home_taz")
    per = _to_taz(per, "workplace_zone_id", "work_taz")
    per = _to_taz(per, "school_zone_id", "school_taz")
    per = _add_geo(per, "home_taz", "HGEO")
    per = _add_geo(per, "work_taz", "WGEO")

    if skim is not None:
        if "home_taz" in per.columns and "work_taz" in per.columns:
            origin = per["home_taz"].fill_null(0).to_numpy()
            destination = per["work_taz"].fill_null(0).to_numpy()
            per = per.with_columns(pl.Series("distance_to_work", _skim_lookup(skim, origin, destination, skim_map)))
        if "home_taz" in per.columns and "school_taz" in per.columns:
            origin = per["home_taz"].fill_null(0).to_numpy()
            destination = per["school_taz"].fill_null(0).to_numpy()
            per = per.with_columns(pl.Series("distance_to_school", _skim_lookup(skim, origin, destination, skim_map)))

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

    hh_for_tours = [col for col in ["household_id", "HHVEH", "WORKERS", "ADULTS"] if col in hh.columns]
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
        tours = (
            tours.with_columns(
                [
                    pl.col("stop_frequency").cast(pl.Utf8).str.split("out_").list.first().cast(pl.Int32).alias("num_ob_stops"),
                    pl.col("stop_frequency")
                    .cast(pl.Utf8)
                    .str.split("out_")
                    .list.last()
                    .str.replace("in", "", literal=True)
                    .cast(pl.Int32)
                    .alias("num_ib_stops"),
                ]
            )
            .with_columns((pl.col("num_ob_stops") + pl.col("num_ib_stops")).alias("num_tot_stops"))
        )

    tours = _to_taz(tours, "origin", "OTAZ")
    tours = _to_taz(tours, "destination", "DTAZ")

    if skim is not None and "OTAZ" in tours.columns and "DTAZ" in tours.columns:
        origin = tours["OTAZ"].fill_null(0).to_numpy()
        destination = tours["DTAZ"].fill_null(0).to_numpy()
        tours = tours.with_columns(pl.Series("SKIMDIST", _skim_lookup(skim, origin, destination, skim_map)))
    elif "SKIMDIST" not in tours.columns:
        tours = tours.with_columns(pl.lit(0.0).alias("SKIMDIST"))

    if "tour_id" in tours.columns and "person_id" in run_data.joint_participants.columns:
        party_size = run_data.joint_participants.group_by("tour_id").agg(pl.len().alias("NUMBER_HH"))
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
    elif "start_hour" in tours.columns and "end_hour" in tours.columns and "tourdur" not in tours.columns:
        tours = tours.with_columns((pl.col("end_hour") - pl.col("start_hour")).alias("tourdur"))

    tour_join_cols = [
        col for col in ["tour_id", "AUTOSUFF", "NUMBER_HH", "primary_purpose", "tour_mode", "tour_category"]
        if col in tours.columns
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
        available_hh_cols = [col for col in ["household_id", "HHVEH", "WORKERS"] if col in hh.columns]
        trips = trips.join(hh.select(available_hh_cols), on="household_id", how="left")
    if "AUTOSUFF" not in trips.columns and "HHVEH" in trips.columns and "WORKERS" in trips.columns:
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
        origin = trips["OTAZ"].fill_null(0).to_numpy()
        destination = trips["DTAZ"].fill_null(0).to_numpy()
        trips = trips.with_columns(pl.Series("od_dist", _skim_lookup(skim, origin, destination, skim_map)))
    elif "od_dist" not in trips.columns:
        trips = trips.with_columns(pl.lit(0.0).alias("od_dist"))

    if "depart" in trips.columns and "depart_hour" not in trips.columns:
        trips = trips.with_columns(pl.col("depart").alias("depart_hour"))
    elif "depart_hour" not in trips.columns:
        trips = trips.with_columns(pl.lit(1).alias("depart_hour"))

    if "outbound" in trips.columns and "inbound" not in trips.columns:
        trips = trips.with_columns(
            pl.when(pl.col("outbound").cast(pl.Utf8).str.to_lowercase().is_in(["false", "0"]))
            .then(1)
            .otherwise(0)
            .alias("inbound")
        )

    if "trip_num" in trips.columns and "outbound" in trips.columns:
        max_trip = trips.group_by(["tour_id", "outbound"]).agg(pl.col("trip_num").max().alias("max_trip_num"))
        trips = trips.join(max_trip, on=["tour_id", "outbound"], how="left")
        trips = trips.with_columns(
            pl.when(pl.col("trip_num") < pl.col("max_trip_num")).then(1).otherwise(0).alias("stops")
        )
    elif "stops" not in trips.columns:
        trips = trips.with_columns(pl.lit(0).alias("stops"))

    if "out_dir_dist" not in trips.columns:
        if skim is not None and "OTAZ" in trips.columns and "DTAZ" in trips.columns and "inbound" in trips.columns:
            tour_od = tours.select(["tour_id", "OTAZ", "DTAZ"]).rename({"OTAZ": "tour_OTAZ", "DTAZ": "tour_DTAZ"})
            trips = trips.join(tour_od, on="tour_id", how="left")
            final_destination = np.where(
                trips["inbound"].to_numpy() == 0,
                trips["tour_DTAZ"].fill_null(0).to_numpy(),
                trips["tour_OTAZ"].fill_null(0).to_numpy(),
            )
            origin = trips["OTAZ"].fill_null(0).to_numpy()
            destination = trips["DTAZ"].fill_null(0).to_numpy()
            od = _skim_lookup(skim, origin, destination, skim_map)
            os_dist = _skim_lookup(skim, origin, final_destination, skim_map)
            sd_dist = _skim_lookup(skim, destination, final_destination, skim_map)
            trips = trips.with_columns(pl.Series("out_dir_dist", (os_dist + sd_dist - od).clip(0)))
        else:
            trips = trips.with_columns(pl.lit(0.0).alias("out_dir_dist"))

    return RunData(
        label=run_data.label,
        run_dir=run_data.run_dir,
        skim_file=run_data.skim_file,
        hh=hh,
        per=per,
        tours=tours,
        trips=trips,
        joint_participants=run_data.joint_participants,
        land_use=land_use,
        skim_matrix=skim,
        skim_zone_map=skim_map,
        hh_weight_col=run_data.hh_weight_col,
        person_weight_col=run_data.person_weight_col,
        trip_weight_col=run_data.trip_weight_col,
    )


def prepare_runs(runs: Sequence[tuple[str, RunData]], config: Config) -> PreparedRuns:
    """Prepare weighted and unweighted run variants for the app."""
    weighted_runs = [(label, prepare_run(run_data, config)) for label, run_data in runs]
    unweighted_runs = [(label, strip_weights(run_data)) for label, run_data in weighted_runs]
    return PreparedRuns(config=config, weighted_runs=weighted_runs, unweighted_runs=unweighted_runs)


def load_and_prepare_runs(config_path: str | Path, run_specs: Sequence[RunSpec] | None = None) -> PreparedRuns:
    """Load the app config, read all runs, and prepare weighted and unweighted variants."""
    config = load_config(config_path)
    runs = load_runs(config, run_specs=run_specs)
    return prepare_runs(runs, config)
