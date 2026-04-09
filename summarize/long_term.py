"""Long Term summaries."""

import polars as pl

from .reader import RunData, Config


def license_holding_status(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def bicycle_comfort_level(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def av_ownership(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def auto_ownership(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: household_vehicle_count (0-4), household_count."""
    return (
        rd.hh.group_by("HHVEH")
        .agg(household_count=pl.col("finalweight").sum())
        .rename({"HHVEH": "household_vehicle_count"})
        .sort("household_vehicle_count")
    )


def wfh(rd: RunData, config: Config) -> pl.DataFrame:
    """Work-from-home summary by geography group + all_geographies.
    Returns DataFrame: geography, worker_count, work_from_home_worker_count.
    If geography disabled, returns a single all_geographies row."""
    if "is_worker" not in rd.per.columns:
        return pl.DataFrame(
            {
                "geography": ["all_geographies"],
                "worker_count": [0.0],
                "work_from_home_worker_count": [0.0],
            }
        )

    wfh_col = "work_from_home"

    workers = rd.per.filter(
        pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"])
    )

    if wfh_col in workers.columns:
        workers = workers.with_columns(
            pl.col(wfh_col)
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1"])
            .alias("_is_wfh")
        )
    else:
        workers = workers.with_columns(pl.lit(False).alias("_is_wfh"))

    if config.geography_enabled and "HGEO" in workers.columns:
        by_geo = (
            workers.group_by("HGEO")
            .agg(
                worker_count=pl.col("finalweight").sum(),
                work_from_home_worker_count=(
                    pl.col("finalweight") * pl.col("_is_wfh").cast(pl.Float64)
                ).sum(),
            )
            .rename({"HGEO": "geography"})
            .with_columns(pl.col("geography").cast(pl.Utf8))
        )
    else:
        by_geo = pl.DataFrame(
            {
                "geography": [],
                "worker_count": [],
                "work_from_home_worker_count": [],
            }
        )

    total = workers.select(
        geography=pl.lit("all_geographies"),
        worker_count=pl.col("finalweight").sum(),
        work_from_home_worker_count=(
            pl.col("finalweight") * pl.col("_is_wfh").cast(pl.Float64)
        ).sum(),
    )

    return pl.concat([by_geo, total]).sort("geography")


def internal_vs_external(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def external_workplace_loc(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def workplace_vs_land_use_employment(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def commuting_flows(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def school_loc_vs_land_use_enrollment(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def tlfd(rd: RunData, config: Config) -> dict[str, pl.DataFrame]:
    """Returns long-form distance distribution tables with columns:
    distance_bin, geography, person_count.
    distance_bin 1 = 0–1 miles, distance_bin 51 = 50+ miles.
    Fully dense: every geography has bins 1-51, plus all_geographies.
    """

    def _bin_dist(df: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        return df.with_columns(
            pl.col(dist_col).fill_null(0.0).clip(0, 9999)
        ).with_columns(
            (pl.col(dist_col).cast(pl.Int32) + 1).clip(1, 51).alias("distance_bin")
        )

    def _make_tlfd(persons: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        empty = pl.DataFrame(
            {
                "distance_bin": [],
                "geography": [],
                "person_count": [],
            }
        )

        if dist_col not in persons.columns:
            return empty

        df = _bin_dist(persons, dist_col)

        distance_bins = pl.DataFrame({"distance_bin": list(range(1, 52))})

        if config.geography_enabled and "HGEO" in df.columns:
            geographies = (
                df.select(pl.col("HGEO").cast(pl.Utf8).alias("geography"))
                .drop_nulls()
                .unique()
                .sort("geography")
            )

            by_geo = (
                df.with_columns(pl.col("HGEO").cast(pl.Utf8).alias("geography"))
                .group_by(["distance_bin", "geography"])
                .agg(person_count=pl.col("finalweight").sum())
            )

            dense_by_geo = (
                distance_bins.join(geographies, how="cross")
                .join(by_geo, on=["distance_bin", "geography"], how="left")
                .with_columns(pl.col("person_count").fill_null(0.0))
            )

            total = (
                df.group_by("distance_bin")
                .agg(person_count=pl.col("finalweight").sum())
                .with_columns(pl.lit("all_geographies").alias("geography"))
                .select("distance_bin", "geography", "person_count")
            )

            dense_total = (
                distance_bins.with_columns(pl.lit("all_geographies").alias("geography"))
                .join(total, on=["distance_bin", "geography"], how="left")
                .with_columns(pl.col("person_count").fill_null(0.0))
            )

            result = pl.concat([dense_by_geo, dense_total], how="vertical")
        else:
            total = (
                df.group_by("distance_bin")
                .agg(person_count=pl.col("finalweight").sum())
                .with_columns(pl.lit("all_geographies").alias("geography"))
                .select("distance_bin", "geography", "person_count")
            )

            result = (
                distance_bins.with_columns(pl.lit("all_geographies").alias("geography"))
                .join(total, on=["distance_bin", "geography"], how="left")
                .with_columns(pl.col("person_count").fill_null(0.0))
            )

        return result.sort(["distance_bin", "geography"]).select(
            "distance_bin", "geography", "person_count"
        )

    ptype_col = config.col_ptype

    workers = (
        rd.per.filter(
            (pl.col("workplace_zone_id") > 0)
            & (
                pl.col("is_worker")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["true", "1"])
            )
        )
        if "is_worker" in rd.per.columns
        else rd.per.head(0)
    )

    if ptype_col in rd.per.columns:
        per_ptype = rd.per

        univ = (
            per_ptype.filter(
                (pl.col("school_zone_id") > 0)
                & (
                    pl.col("is_student")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .is_in(["true", "1"])
                )
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )

        schl = (
            per_ptype.filter(
                (pl.col("school_zone_id") > 0)
                & (
                    pl.col("is_student")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .is_in(["true", "1"])
                )
                & (pl.col(ptype_col).cast(pl.Utf8).cast(pl.Int32, strict=False) >= 6)
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
    else:
        univ = rd.per.head(0)
        schl = rd.per.head(0)

    return {
        "work": _make_tlfd(workers, "distance_to_work"),
        "univ": _make_tlfd(univ, "distance_to_school"),
        "schl": _make_tlfd(schl, "distance_to_school"),
    }


def vehicle_char_age(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def vehicle_char_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def vehicle_char_body(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def transit_pass(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def transit_subsidy(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def free_parking(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def telecommute(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Telecommute frequency distribution. Columns: telecommute_frequency, person_count."""
    if "telecommute_frequency" not in rd.per.columns:
        return pl.DataFrame(
            {
                "telecommute_frequency": [],
                "person_count": [],
            }
        )

    return (
        rd.per.filter(
            pl.col("telecommute_frequency").is_not_null()
            & (pl.col("telecommute_frequency") != "")
        )
        .group_by("telecommute_frequency")
        .agg(person_count=pl.col("finalweight").sum())
        .sort("telecommute_frequency")
    )
