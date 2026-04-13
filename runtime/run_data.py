"""Shared raw-run loading and enrichment helpers.

This module owns the ActivitySim raw run loading and preparation used by both
summary generation and raw-data dashboard pages. It is deliberately outside of
``summarize`` and ``dashboard`` so neither subsystem owns the other's runtime
primitives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from activitysim_viz_logging import get_logger
import numpy as np
import polars as pl

from runtime.config import Config
from runtime.models import RunData

LOGGER = get_logger("runtime.run_data")


def _resolve_source_column(
    df: pl.DataFrame,
    preferred: str | list[str] | None,
    *,
    fallbacks: tuple[str, ...] = (),
    require_non_numeric: bool = False,
) -> str | None:
    """Return the first matching source column for one semantic concept.

    For purpose-like fields we prefer non-numeric columns to preserve the
    existing summary behavior of displaying readable labels when available.
    """

    candidates: list[str] = []
    if isinstance(preferred, list):
        preferred_candidates = preferred
    elif preferred is None:
        preferred_candidates = []
    else:
        preferred_candidates = [preferred]

    for candidate in [*preferred_candidates, *fallbacks]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        return None

    if require_non_numeric:
        for candidate in candidates:
            if candidate in df.columns and not df[candidate].dtype.is_numeric():
                return candidate

    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _materialize_column(
    df: pl.DataFrame,
    target: str,
    source: str | None,
) -> pl.DataFrame:
    """Alias a source column into a canonical target column when needed."""

    if target in df.columns or source is None or source not in df.columns:
        return df
    return df.with_columns(pl.col(source).alias(target))


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
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = run_dir / path
    return str(path)


def resolve_skim_path(
    run_skim: Optional[str],
    global_skim: Optional[str],
    run_dir: str | Path,
) -> Optional[str]:
    """Public wrapper used by the cache layer to fingerprint run inputs."""
    return _resolve_skim(run_skim, global_skim, Path(run_dir))


def _find_and_read(run_dir: Path, configured: str) -> pl.DataFrame:
    """Read a table from run_dir, resolving file format."""
    path = Path(configured)
    run_dir = run_dir.expanduser()
    suffix = path.suffix.lower()
    stem = path.stem if suffix in (".csv", ".parquet") else path.name

    if suffix == ".parquet":
        LOGGER.info("[read_run] Reading parquet: %s", run_dir / path)
        return pl.read_parquet(run_dir / path)
    if suffix == ".csv":
        LOGGER.info("[read_run] Reading csv: %s", run_dir / path)
        return pl.read_csv(run_dir / path, infer_schema_length=None)

    parquet_path = run_dir / f"{stem}.parquet"
    csv_path = run_dir / f"{stem}.csv"
    if parquet_path.exists():
        return pl.read_parquet(parquet_path)
    if csv_path.exists():
        return pl.read_csv(csv_path, infer_schema_length=None)
    raise FileNotFoundError(f"Cannot find '{stem}.parquet' or '{stem}.csv' in {run_dir}")


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
    """Compute and attach ``finalweight`` to HH, persons, tours, and trips."""
    explicit_weight_supplied = any([hh_weight_col, person_weight_col, trip_weight_col])
    sample_rate_col = config.col_sample_rate or (
        "sample_rate" if "sample_rate" in hh.columns else None
    )
    if sample_rate_col == "sample_rate" and config.col_sample_rate is None:
        LOGGER.info("[compute_weights] Auto-detected sample_rate column in households.")

    if hh_weight_col and hh_weight_col in hh.columns:
        LOGGER.info("[compute_weights] Using household weight column: %s", hh_weight_col)
        hh = hh.with_columns(pl.col(hh_weight_col).cast(pl.Float64).alias("finalweight"))
    elif (not explicit_weight_supplied) and sample_rate_col and sample_rate_col in hh.columns:
        LOGGER.info(
            "[compute_weights] Using sample-rate expansion from column: %s",
            sample_rate_col,
        )
        hh = hh.with_columns(
            (pl.lit(1.0) / pl.col(sample_rate_col).cast(pl.Float64)).alias("finalweight")
        )
    else:
        if explicit_weight_supplied and sample_rate_col and sample_rate_col in hh.columns:
            LOGGER.info(
                "[compute_weights] Explicit run weight columns supplied; skipping sample_rate expansion."
            )
        else:
            LOGGER.info("[compute_weights] No weight column found; defaulting finalweight=1.")
        hh = hh.with_columns(pl.lit(1.0).alias("finalweight"))

    if person_weight_col and person_weight_col in per.columns:
        LOGGER.info("[compute_weights] Using person weight column: %s", person_weight_col)
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

    if trip_weight_col and trip_weight_col in trips.columns:
        LOGGER.info("[compute_weights] Using trip weight column: %s", trip_weight_col)
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

    if trip_weight_col and trip_weight_col in trips.columns and "tour_id" in trips.columns:
        tour_avg = trips.group_by("tour_id").agg(pl.col("finalweight").mean().alias("_tw"))
        tours = (
            tours.join(tour_avg, on="tour_id", how="left")
            .with_columns(pl.col("_tw").fill_null(1.0).alias("finalweight"))
            .drop("_tw")
        )
    elif "person_id" in tours.columns:
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


def read_run(
    run_dir: str | Path,
    config: Config,
    label: Optional[str] = None,
    skim_file: Optional[str] = None,
    hh_weight_col: Optional[str] = None,
    person_weight_col: Optional[str] = None,
    trip_weight_col: Optional[str] = None,
) -> RunData:
    """Read ActivitySim outputs and optionally the OMX skim for one run."""
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

    resolved_skim = _resolve_skim(skim_file, config.skim_file, run_dir)
    skim_matrix: Optional[np.ndarray] = None
    skim_zone_map: Optional[dict[int, int]] = None
    if resolved_skim:
        try:
            import openmatrix as omx

            file = omx.open_file(resolved_skim)
            skim_matrix = np.array(file[config.skim_matrix])
            mappings = file.list_mappings()
            if mappings:
                mapping_name = mappings[0]
                raw_map = file.mapping(mapping_name)
                norm_map: dict[int, int] = {}
                for key, value in raw_map.items():
                    normalized_key = (
                        key.decode("utf-8") if isinstance(key, (bytes, bytearray)) else key
                    )
                    try:
                        norm_map[int(normalized_key)] = int(value)
                    except Exception:
                        continue
                skim_zone_map = norm_map if norm_map else None
                LOGGER.info(
                    "[read_run] Loaded skim mapping '%s' with %s zones.",
                    mapping_name,
                    len(norm_map),
                )
            file.close()
            LOGGER.info(
                "[read_run] Loaded skim matrix '%s' from %s",
                config.skim_matrix,
                resolved_skim,
            )
        except Exception as exc:
            LOGGER.warning("Warning: could not read skim '%s': %s", resolved_skim, exc)
    else:
        LOGGER.info("[read_run] No skim configured for run '%s'.", label)

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


def prepare_data(rd: RunData, config: Config) -> RunData:
    """Enrich ``RunData`` with derived columns needed by summaries and dashboard pages."""
    skim = rd.skim_matrix
    skim_map = rd.skim_zone_map
    LOGGER.info("[prepare_data] Starting: %s", rd.label)

    # Prepare canonical identifiers and summary-facing raw fields before any
    # weighting or joins. Summary modules should consume these prepared names.
    hh = rd.hh
    per = rd.per
    tours = rd.tours
    trips = rd.trips
    joint_participants = rd.joint_participants
    land_use = rd.land_use

    hh = _materialize_column(
        hh,
        "household_id",
        _resolve_source_column(hh, config.col_household_id),
    )

    per = _materialize_column(
        per,
        "household_id",
        _resolve_source_column(per, config.col_household_id),
    )
    per = _materialize_column(
        per,
        "person_id",
        _resolve_source_column(per, config.col_person_id),
    )

    tours = _materialize_column(
        tours,
        "household_id",
        _resolve_source_column(tours, config.col_household_id),
    )
    tours = _materialize_column(
        tours,
        "person_id",
        _resolve_source_column(tours, config.col_person_id),
    )
    tours = _materialize_column(
        tours,
        "tour_id",
        _resolve_source_column(tours, config.col_tour_id),
    )
    tours = _materialize_column(
        tours,
        "tour_category",
        _resolve_source_column(tours, config.col_tour_category),
    )
    tours = _materialize_column(
        tours,
        "tour_mode",
        _resolve_source_column(tours, config.col_tour_mode),
    )
    tours = _materialize_column(
        tours,
        "tour_purpose",
        _resolve_source_column(
            tours,
            config.col_tour_purpose,
            require_non_numeric=True,
        ),
    )
    tours = _materialize_column(
        tours,
        "start_hour",
        _resolve_source_column(tours, config.col_tour_start),
    )
    tours = _materialize_column(
        tours,
        "end_hour",
        _resolve_source_column(tours, config.col_tour_end),
    )
    tours = _materialize_column(
        tours,
        "tourdur",
        _resolve_source_column(tours, config.col_tour_duration),
    )

    trips = _materialize_column(
        trips,
        "household_id",
        _resolve_source_column(trips, config.col_household_id),
    )
    trips = _materialize_column(
        trips,
        "person_id",
        _resolve_source_column(trips, config.col_person_id),
    )
    trips = _materialize_column(
        trips,
        "tour_id",
        _resolve_source_column(trips, config.col_tour_id),
    )
    trips = _materialize_column(
        trips,
        "trip_id",
        _resolve_source_column(trips, config.col_trip_id),
    )
    trips = _materialize_column(
        trips,
        "trip_mode",
        _resolve_source_column(trips, config.col_trip_mode),
    )
    trips = _materialize_column(
        trips,
        "trip_purpose",
        _resolve_source_column(
            trips,
            config.col_trip_purpose,
            require_non_numeric=True,
        ),
    )
    trips = _materialize_column(
        trips,
        "depart_hour",
        _resolve_source_column(trips, config.col_trip_depart),
    )
    trips = _materialize_column(
        trips,
        "tour_mode",
        _resolve_source_column(trips, config.col_tour_mode),
    )
    trips = _materialize_column(
        trips,
        "tour_category",
        _resolve_source_column(trips, config.col_tour_category),
    )
    trips = _materialize_column(
        trips,
        "tour_purpose",
        _resolve_source_column(
            trips,
            config.col_tour_purpose,
            require_non_numeric=True,
        ),
    )

    joint_participants = _materialize_column(
        joint_participants,
        "person_id",
        _resolve_source_column(joint_participants, config.col_person_id),
    )
    joint_participants = _materialize_column(
        joint_participants,
        "tour_id",
        _resolve_source_column(joint_participants, config.col_tour_id),
    )

    land_use = _materialize_column(
        land_use,
        "EMPLOYMENT",
        _resolve_source_column(land_use, config.col_total_employment),
    )

    hh, per, tours, trips = compute_weights(
        hh,
        per,
        tours,
        trips,
        config,
        hh_weight_col=rd.hh_weight_col,
        person_weight_col=rd.person_weight_col,
        trip_weight_col=rd.trip_weight_col,
    )
    LOGGER.info("[prepare_data] Weights ready for '%s'", rd.label)

    if config.use_maz:
        LOGGER.info("[prepare_data] Building MAZ->TAZ lookup for '%s'", rd.label)
        maz_taz = (
            land_use.select([config.maz_col, config.taz_col])
            .rename({config.maz_col: "_maz", config.taz_col: "_taz"})
            .unique("_maz")
        )
    else:
        maz_taz = None

    zone_geo: Optional[pl.DataFrame] = None
    if config.geography_enabled and config.geography_landuse_col:
        LOGGER.info(
            "[prepare_data] Applying geography labels from '%s'",
            config.geography_landuse_col,
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
        zone_geo = geo_lu

    def _to_taz(df: pl.DataFrame, zone_col: str, out_col: str) -> pl.DataFrame:
        if not config.use_maz:
            if zone_col in df.columns:
                return df.with_columns(pl.col(zone_col).alias(out_col))
            return df
        if maz_taz is None or zone_col not in df.columns:
            return df
        return df.join(
            maz_taz.rename({"_maz": zone_col, "_taz": out_col}),
            on=zone_col,
            how="left",
        ).with_columns(pl.coalesce([pl.col(out_col), pl.col(zone_col)]).alias(out_col))

    def _add_geo(df: pl.DataFrame, taz_col: str, out_col: str) -> pl.DataFrame:
        if zone_geo is None or taz_col not in df.columns:
            return df
        geo_col = config.geography_landuse_col
        return df.join(
            zone_geo.rename({"_taz": taz_col, geo_col: out_col}),
            on=taz_col,
            how="left",
        )

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

    if "home_zone_id" not in per.columns:
        LOGGER.warning(
            "Warning: 'home_zone_id' column not found in persons for run '%s'. Merging from household_id.",
            rd.label,
        )
        per = per.join(
            hh.select(["household_id", "home_zone_id"]),
            on="household_id",
            how="left",
        )

    per = _to_taz(per, "home_zone_id", "home_taz")
    per = _to_taz(per, "workplace_zone_id", "work_taz")
    per = _to_taz(per, "school_zone_id", "school_taz")
    per = _add_geo(per, "home_taz", "HGEO")
    per = _add_geo(per, "work_taz", "WGEO")

    if skim is not None:
        LOGGER.info("[prepare_data] Computing person skim distances for '%s'", rd.label)
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

    hh_for_tours = [
        column for column in ["household_id", "HHVEH", "WORKERS", "ADULTS"] if column in hh.columns
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

    if skim is not None and "OTAZ" in tours.columns and "DTAZ" in tours.columns:
        LOGGER.info("[prepare_data] Computing tour skim distances for '%s'", rd.label)
        o = tours["OTAZ"].fill_null(0).to_numpy()
        d = tours["DTAZ"].fill_null(0).to_numpy()
        tours = tours.with_columns(
            pl.Series("SKIMDIST", _skim_lookup(skim, o, d, skim_map))
        )
    elif "SKIMDIST" not in tours.columns:
        tours = tours.with_columns(pl.lit(0.0).alias("SKIMDIST"))

    if "tour_id" in tours.columns and "person_id" in joint_participants.columns:
        party_size = joint_participants.group_by("tour_id").agg(
            pl.len().alias("NUMBER_HH")
        )
        tours = tours.join(party_size, on="tour_id", how="left")
    if "NUMBER_HH" not in tours.columns:
        tours = tours.with_columns(pl.lit(1).alias("NUMBER_HH"))
    tours = tours.with_columns(pl.col("NUMBER_HH").fill_null(1))

    if (
        "start_hour" in tours.columns
        and "end_hour" in tours.columns
        and "tourdur" not in tours.columns
    ):
        tours = tours.with_columns(
            (pl.col("end_hour") - pl.col("start_hour")).alias("tourdur")
        )

    tour_join_cols = [
        column
        for column in [
            "tour_id",
            "AUTOSUFF",
            "NUMBER_HH",
            "tour_purpose",
            "tour_mode",
            "tour_category",
        ]
        if column in tours.columns
    ]
    trips = trips.join(
        tours.select(tour_join_cols).rename({"NUMBER_HH": "num_participants"}),
        on="tour_id",
        how="left",
        suffix="_tour",
    )
    for column in ["tour_purpose", "tour_mode", "tour_category"]:
        tour_col = f"{column}_tour"
        if tour_col in trips.columns and column in trips.columns:
            trips = trips.with_columns(
                pl.coalesce([pl.col(tour_col), pl.col(column)]).alias(column)
            ).drop(tour_col)
        elif tour_col in trips.columns:
            trips = trips.rename({tour_col: column})

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
        LOGGER.info("[prepare_data] Computing trip skim distances for '%s'", rd.label)
        o = trips["OTAZ"].fill_null(0).to_numpy()
        d = trips["DTAZ"].fill_null(0).to_numpy()
        trips = trips.with_columns(
            pl.Series("od_dist", _skim_lookup(skim, o, d, skim_map))
        )
    elif "od_dist" not in trips.columns:
        trips = trips.with_columns(pl.lit(0.0).alias("od_dist"))

    if "depart_hour" not in trips.columns:
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

    LOGGER.info("[prepare_data] Complete: %s", rd.label)
    return RunData(
        label=rd.label,
        run_dir=rd.run_dir,
        skim_file=rd.skim_file,
        hh=hh,
        per=per,
        tours=tours,
        trips=trips,
        joint_participants=joint_participants,
        land_use=land_use,
        skim_matrix=skim,
        skim_zone_map=skim_map,
        hh_weight_col=rd.hh_weight_col,
        person_weight_col=rd.person_weight_col,
        trip_weight_col=rd.trip_weight_col,
    )
