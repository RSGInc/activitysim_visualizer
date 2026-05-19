"""Geography and land-use long-term summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.long_term_shared import (
    _student_filter_expr,
    _worker_filter_expr,
)
from runtime.config import Config


def _aggregate_internal_external_counts(
    df: pl.DataFrame,
    geography_type: str,
    geography_id_col: str,
) -> pl.DataFrame:
    return (
        df.group_by(geography_id_col)
        .agg(
            internal_worker_count=pl.when(~pl.col("is_external_worker"))
            .then(pl.col("finalweight"))
            .otherwise(0.0)
            .sum(),
            external_worker_count=pl.when(pl.col("is_external_worker"))
            .then(pl.col("finalweight"))
            .otherwise(0.0)
            .sum(),
        )
        .rename({geography_id_col: "geography_id"})
        .with_columns(
            pl.lit(geography_type).alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("internal_worker_count").cast(pl.Float64),
            pl.col("external_worker_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "internal_worker_count",
            "external_worker_count",
        )
    )


def _aggregate_external_worker_counts(
    df: pl.DataFrame,
    geography_type: str,
    geography_id_col: str,
) -> pl.DataFrame:
    return (
        df.group_by(geography_id_col)
        .agg(external_worker_count=pl.col("finalweight").sum())
        .rename({geography_id_col: "geography_id"})
        .with_columns(
            pl.lit(geography_type).alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("external_worker_count").cast(pl.Float64),
        )
        .select("geography_type", "geography_id", "external_worker_count")
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "worker_count": pl.Float64,
        "work_from_home_worker_count": pl.Float64,
    },
    required_columns={"per": ("is_worker", "home_zone_id", "finalweight")},
)
def wfh(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"is_worker", "home_zone_id", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return empty_summary_frame(wfh)

    workers = rd.per.filter(
        _worker_filter_expr() & pl.col("home_zone_id").is_not_null()
    )
    if workers.is_empty():
        return empty_summary_frame(wfh)

    if "work_from_home" in workers.columns:
        workers = workers.with_columns(
            pl.col("work_from_home")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1"])
            .alias("_is_wfh")
        )
    else:
        workers = workers.with_columns(pl.lit(False).alias("_is_wfh"))

    base = workers.select("home_zone_id", "_is_wfh", "finalweight")

    def _aggregate_wfh_counts(
        df: pl.DataFrame,
        geography_type: str,
        geography_id_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by(geography_id_col)
            .agg(
                worker_count=pl.col("finalweight").sum(),
                work_from_home_worker_count=(
                    pl.col("finalweight") * pl.col("_is_wfh").cast(pl.Float64)
                ).sum(),
            )
            .rename({geography_id_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("worker_count").cast(pl.Float64),
                pl.col("work_from_home_worker_count").cast(pl.Float64),
            )
            .select(
                "geography_type",
                "geography_id",
                "worker_count",
                "work_from_home_worker_count",
            )
        )

    outputs = [_aggregate_wfh_counts(base, geography_type="maz", geography_id_col="home_zone_id")]
    all_geographies = base.select(
        pl.lit("all_geographies").alias("geography_type"),
        pl.lit("all_geographies").alias("geography_id"),
        pl.col("finalweight").sum().cast(pl.Float64).alias("worker_count"),
        (pl.col("finalweight") * pl.col("_is_wfh").cast(pl.Float64))
        .sum()
        .cast(pl.Float64)
        .alias("work_from_home_worker_count"),
    )

    return (
        pl.concat([*outputs, all_geographies], how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("worker_count").cast(pl.Float64),
            pl.col("work_from_home_worker_count").cast(pl.Float64),
        )
        .sort(["geography_type", "geography_id"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "internal_worker_count": pl.Float64,
        "external_worker_count": pl.Float64,
    },
    required_columns={
        "per": ("is_worker", "is_external_worker", "home_zone_id", "finalweight")
    },
)
def internal_vs_external(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"is_worker", "is_external_worker", "home_zone_id", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return empty_summary_frame(internal_vs_external)

    base = (
        rd.per.filter(
            _worker_filter_expr()
            & pl.col("is_external_worker").is_not_null()
            & pl.col("home_zone_id").is_not_null()
        )
        .with_columns(
            pl.col("is_external_worker")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes", "external"])
            .alias("is_external_worker")
        )
        .select("home_zone_id", "is_external_worker", "finalweight")
    )
    if base.is_empty():
        return empty_summary_frame(internal_vs_external)

    outputs = [
        _aggregate_internal_external_counts(base, geography_type="maz", geography_id_col="home_zone_id"),
        _aggregate_internal_external_counts(
            base.with_columns(pl.lit("all_geographies").alias("_all_geographies")),
            geography_type="all_geographies",
            geography_id_col="_all_geographies",
        ),
    ]
    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("internal_worker_count").cast(pl.Float64),
            pl.col("external_worker_count").cast(pl.Float64),
        )
        .sort(["geography_type", "geography_id"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "external_worker_count": pl.Float64,
    },
    required_columns={
        "per": ("is_external_worker", "external_workplace_zone_id", "finalweight")
    },
)
def external_workplace_loc(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"is_external_worker", "external_workplace_zone_id", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return empty_summary_frame(external_workplace_loc)

    base = rd.per.filter(
        (pl.col("is_external_worker") == True)
        & pl.col("external_workplace_zone_id").is_not_null()
    ).select("external_workplace_zone_id", "finalweight")
    if base.is_empty():
        return empty_summary_frame(external_workplace_loc)

    return (
        _aggregate_external_worker_counts(
            base,
            geography_type="maz",
            geography_id_col="external_workplace_zone_id",
        )
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("external_worker_count").cast(pl.Float64),
        )
        .sort(["geography_type", "geography_id"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "employment_count": pl.Float64,
        "worker_count": pl.Float64,
    },
    required_columns={
        "land_use": ("MAZ", "employment_count"),
        "per": ("workplace_zone_id", "is_worker", "finalweight"),
    },
)
def workplace_vs_land_use_employment(rd: RunData, config: Config) -> pl.DataFrame:
    land_use_required = {"MAZ", "employment_count"}
    person_required = {"workplace_zone_id", "is_worker", "finalweight"}
    if not land_use_required.issubset(set(rd.land_use.columns)) or not person_required.issubset(set(rd.per.columns)):
        return empty_summary_frame(workplace_vs_land_use_employment)

    land_use_maz = (
        rd.land_use.filter(pl.col("MAZ").is_not_null() & pl.col("employment_count").is_not_null())
        .group_by("MAZ")
        .agg(employment_count=pl.col("employment_count").sum())
        .rename({"MAZ": "geography_id"})
        .with_columns(
            pl.lit("maz").alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("employment_count").cast(pl.Float64),
        )
    )
    worker_maz = (
        rd.per.filter(_worker_filter_expr() & pl.col("workplace_zone_id").is_not_null())
        .group_by("workplace_zone_id")
        .agg(worker_count=pl.col("finalweight").sum())
        .rename({"workplace_zone_id": "geography_id"})
        .with_columns(
            pl.lit("maz").alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("worker_count").cast(pl.Float64),
        )
    )

    return (
        land_use_maz.join(
            worker_maz,
            on=["geography_type", "geography_id"],
            how="full",
            coalesce=True,
        )
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("employment_count").fill_null(0.0).cast(pl.Float64),
            pl.col("worker_count").fill_null(0.0).cast(pl.Float64),
        )
        .select("geography_type", "geography_id", "employment_count", "worker_count")
        .sort(["geography_type", "geography_id"])
    )


@summary_contract(
    schema={
        "origin_geography_type": pl.Utf8,
        "origin_geography_id": pl.Utf8,
        "destination_geography_type": pl.Utf8,
        "destination_geography_id": pl.Utf8,
        "commuter_count": pl.Float64,
    },
    required_columns={
        "per": ("home_zone_id", "workplace_zone_id", "is_worker", "finalweight")
    },
)
def commuting_flows(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"home_zone_id", "workplace_zone_id", "is_worker", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return empty_summary_frame(commuting_flows)

    def aggregate_flows(
        df: pl.DataFrame,
        origin_type: str,
        origin_col: str,
        destination_type: str,
        destination_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by([origin_col, destination_col])
            .agg(commuter_count=pl.col("finalweight").sum())
            .rename(
                {
                    origin_col: "origin_geography_id",
                    destination_col: "destination_geography_id",
                }
            )
            .with_columns(
                pl.lit(origin_type).alias("origin_geography_type"),
                pl.lit(destination_type).alias("destination_geography_type"),
                pl.col("origin_geography_id").cast(pl.Utf8),
                pl.col("destination_geography_id").cast(pl.Utf8),
                pl.col("commuter_count").cast(pl.Float64),
            )
            .select(
                "origin_geography_type",
                "origin_geography_id",
                "destination_geography_type",
                "destination_geography_id",
                "commuter_count",
            )
        )

    base = rd.per.filter(
        _worker_filter_expr()
        & pl.col("home_zone_id").is_not_null()
        & pl.col("workplace_zone_id").is_not_null()
    ).select("home_zone_id", "workplace_zone_id", "finalweight")
    if base.is_empty():
        return empty_summary_frame(commuting_flows)

    outputs = [
        aggregate_flows(
            base,
            origin_type="maz",
            origin_col="home_zone_id",
            destination_type="maz",
            destination_col="workplace_zone_id",
        ),
        base.select(
            pl.lit("all_geographies").alias("origin_geography_type"),
            pl.lit("all_geographies").alias("origin_geography_id"),
            pl.lit("all_geographies").alias("destination_geography_type"),
            pl.lit("all_geographies").alias("destination_geography_id"),
            pl.col("finalweight").sum().cast(pl.Float64).alias("commuter_count"),
        ),
    ]

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("origin_geography_type").cast(pl.Utf8),
            pl.col("origin_geography_id").cast(pl.Utf8),
            pl.col("destination_geography_type").cast(pl.Utf8),
            pl.col("destination_geography_id").cast(pl.Utf8),
            pl.col("commuter_count").cast(pl.Float64),
        )
        .select(
            "origin_geography_type",
            "origin_geography_id",
            "destination_geography_type",
            "destination_geography_id",
            "commuter_count",
        )
        .sort(
            [
                "origin_geography_type",
                "origin_geography_id",
                "destination_geography_type",
                "destination_geography_id",
            ]
        )
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "student_type": pl.Utf8,
        "enrollment_count": pl.Float64,
        "student_count": pl.Float64,
    },
    required_columns={
        "land_use": ("MAZ", "enrollment_count", "student_type"),
        "per": ("school_zone_id", "is_student", "finalweight"),
    },
)
def school_loc_vs_land_use_enrollment(rd: RunData, config: Config) -> pl.DataFrame:
    land_use_required = {"MAZ", "enrollment_count", "student_type"}
    person_required = {"school_zone_id", "is_student", "finalweight"}
    if not land_use_required.issubset(set(rd.land_use.columns)) or not person_required.issubset(set(rd.per.columns)):
        return empty_summary_frame(school_loc_vs_land_use_enrollment)

    if "student_type" in rd.per.columns:
        student_type_expr = pl.col("student_type").cast(pl.Utf8)
    else:
        return empty_summary_frame(school_loc_vs_land_use_enrollment)

    land_use_maz = (
        rd.land_use.filter(
            pl.col("MAZ").is_not_null()
            & pl.col("student_type").is_not_null()
            & pl.col("enrollment_count").is_not_null()
        )
        .group_by(["MAZ", "student_type"])
        .agg(enrollment_count=pl.col("enrollment_count").sum())
        .rename({"MAZ": "geography_id"})
        .with_columns(
            pl.lit("maz").alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("student_type").cast(pl.Utf8),
            pl.col("enrollment_count").cast(pl.Float64),
        )
    )
    student_maz = (
        rd.per.filter(_student_filter_expr() & pl.col("school_zone_id").is_not_null())
        .with_columns(student_type=student_type_expr.alias("student_type"))
        .filter(pl.col("student_type").is_not_null())
        .group_by(["school_zone_id", "student_type"])
        .agg(student_count=pl.col("finalweight").sum())
        .rename({"school_zone_id": "geography_id"})
        .with_columns(
            pl.lit("maz").alias("geography_type"),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("student_type").cast(pl.Utf8),
            pl.col("student_count").cast(pl.Float64),
        )
    )

    return (
        land_use_maz.join(
            student_maz,
            on=["geography_type", "geography_id", "student_type"],
            how="full",
            coalesce=True,
        )
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("student_type").cast(pl.Utf8),
            pl.col("enrollment_count").fill_null(0.0).cast(pl.Float64),
            pl.col("student_count").fill_null(0.0).cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "student_type",
            "enrollment_count",
            "student_count",
        )
        .sort(["geography_type", "geography_id", "student_type"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "workers_without_free_parking_count": pl.Float64,
        "workers_with_free_parking_count": pl.Float64,
    },
    required_columns={
        "per": (
            "is_worker",
            "free_parking_at_work",
            "workplace_zone_id",
            "finalweight",
        )
    },
)
def free_parking(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"is_worker", "free_parking_at_work", "workplace_zone_id", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return empty_summary_frame(free_parking)

    def aggregate_counts(
        df: pl.DataFrame,
        geography_type: str,
        geography_id_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by(geography_id_col)
            .agg(
                workers_without_free_parking_count=pl.when(~pl.col("free_parking_at_work"))
                .then(pl.col("finalweight"))
                .otherwise(0.0)
                .sum(),
                workers_with_free_parking_count=pl.when(pl.col("free_parking_at_work"))
                .then(pl.col("finalweight"))
                .otherwise(0.0)
                .sum(),
            )
            .rename({geography_id_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("workers_without_free_parking_count").cast(pl.Float64),
                pl.col("workers_with_free_parking_count").cast(pl.Float64),
            )
            .select(
                "geography_type",
                "geography_id",
                "workers_without_free_parking_count",
                "workers_with_free_parking_count",
            )
        )

    base = rd.per.filter(
        _worker_filter_expr()
        & pl.col("workplace_zone_id").is_not_null()
        & pl.col("free_parking_at_work").is_not_null()
    ).select("workplace_zone_id", "free_parking_at_work", "finalweight")
    if base.is_empty():
        return empty_summary_frame(free_parking)

    return (
        aggregate_counts(
            base,
            geography_type="maz",
            geography_id_col="workplace_zone_id",
        )
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("workers_without_free_parking_count").cast(pl.Float64),
            pl.col("workers_with_free_parking_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "workers_without_free_parking_count",
            "workers_with_free_parking_count",
        )
        .sort(["geography_type", "geography_id"])
    )
