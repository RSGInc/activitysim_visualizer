"""Geography and land-use long-term summaries."""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.long_term_shared import (
    _student_filter_expr,
    _worker_filter_expr,
)
from processor.summarize.summaries.summary_helpers import (
    _aggregate_counts_across_geographies,
    _configured_geography_columns,
    _configured_geography_dimensions,
    _configured_land_use_geography_dimensions,
)
from runtime.config import Config

_MAX_SHADOW_PRICING_HISTOGRAM_BINS = 200


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


def _all_geographies_external_worker_counts(df: pl.DataFrame) -> pl.DataFrame:
    return df.select(
        pl.lit("all_geographies").alias("geography_type"),
        pl.lit("all_geographies").alias("geography_id"),
        pl.col("finalweight").sum().cast(pl.Float64).alias("external_worker_count"),
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

    base = workers.select(
        "home_zone_id",
        "_is_wfh",
        "finalweight",
        *_configured_geography_columns(workers, config=config, role_prefix="home"),
    )

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

    outputs = [
        _aggregate_wfh_counts(base, geography_type=geography_type, geography_id_col=geography_col)
        for geography_type, geography_col in _configured_geography_dimensions(
            base,
            config=config,
            base_type="maz" if config.use_maz else "taz",
            base_col="home_zone_id",
            role_prefix="home",
        )
    ]
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
        .select(
            "home_zone_id",
            "is_external_worker",
            "finalweight",
            *_configured_geography_columns(rd.per, config=config, role_prefix="home"),
        )
    )
    if base.is_empty():
        return empty_summary_frame(internal_vs_external)

    outputs = [
        *[
            _aggregate_internal_external_counts(
                base,
                geography_type=geography_type,
                geography_id_col=geography_col,
            )
            for geography_type, geography_col in _configured_geography_dimensions(
                base,
                config=config,
                base_type="maz" if config.use_maz else "taz",
                base_col="home_zone_id",
                role_prefix="home",
            )
        ],
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
        "all_worker_count": pl.Float64,
    },
    required_columns={
        "per": (
            "is_worker",
            "is_external_worker",
            "external_workplace_zone_id",
            "finalweight",
        )
    },
)
def external_workplace_loc(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "is_worker",
        "is_external_worker",
        "external_workplace_zone_id",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return empty_summary_frame(external_workplace_loc)

    base = rd.per.filter(
        (pl.col("is_external_worker") == True)
        & pl.col("external_workplace_zone_id").is_not_null()
    ).select(
        "external_workplace_zone_id",
        "finalweight",
        *_configured_geography_columns(
            rd.per,
            config=config,
            role_prefix="work",
        ),
    )
    if base.is_empty():
        return empty_summary_frame(external_workplace_loc)

    all_worker_count = float(
        rd.per.filter(_worker_filter_expr())
        .select(pl.col("finalweight").sum().cast(pl.Float64).alias("all_worker_count"))[
            "all_worker_count"
        ][0]
        or 0.0
    )

    return (
        pl.concat(
            [
                _aggregate_counts_across_geographies(
                    base,
                    geography_dimensions=_configured_geography_dimensions(
                        base,
                        config=config,
                        base_type="maz" if config.use_maz else "taz",
                        base_col="external_workplace_zone_id",
                        role_prefix="work",
                    ),
                    value_col="external_worker_count",
                ),
                _all_geographies_external_worker_counts(base),
            ],
            how="vertical",
        )
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("external_worker_count").cast(pl.Float64),
            pl.lit(all_worker_count).cast(pl.Float64).alias("all_worker_count"),
        )
        .sort(["geography_type", "geography_id"])
    )


def _residual_metrics_columns(target_col: str, modeled_col: str) -> list[pl.Expr]:
    residual = pl.col(modeled_col) - pl.col(target_col)
    return [
        pl.col(target_col).cast(pl.Float64).alias("target_count"),
        pl.col(modeled_col).cast(pl.Float64).alias("modeled_count"),
        residual.cast(pl.Float64).alias("residual_count"),
        residual.abs().cast(pl.Float64).alias("absolute_residual_count"),
        pl.when(pl.col(target_col) > 0)
        .then((residual / pl.col(target_col)) * 100.0)
        .otherwise(None)
        .cast(pl.Float64)
        .alias("percent_error"),
    ]


def _finalize_residual_frame(
    df: pl.DataFrame,
    *,
    group_cols: list[str] | None = None,
) -> pl.DataFrame:
    ordered_cols = ["geography_type", "geography_id"]
    if group_cols:
        ordered_cols.extend(group_cols)
    ordered_cols.extend(
        [
            "target_count",
            "modeled_count",
            "residual_count",
            "absolute_residual_count",
            "percent_error",
        ]
    )
    cast_exprs = [
        pl.col("geography_type").cast(pl.Utf8),
        pl.col("geography_id").cast(pl.Utf8),
        pl.col("target_count").cast(pl.Float64),
        pl.col("modeled_count").cast(pl.Float64),
        pl.col("residual_count").cast(pl.Float64),
        pl.col("absolute_residual_count").cast(pl.Float64),
        pl.col("percent_error").cast(pl.Float64),
    ]
    if group_cols:
        cast_exprs.extend(pl.col(column).cast(pl.Utf8) for column in group_cols)
    return df.with_columns(cast_exprs).select(ordered_cols)


def _dynamic_count_bin_edges(values: list[float]) -> np.ndarray:
    finite = np.array([value for value in values if math.isfinite(value)], dtype=float)
    if finite.size == 0:
        return np.array([-1.0, 1.0], dtype=float)
    if finite.size == 1 or math.isclose(float(finite.min()), float(finite.max())):
        center = float(finite[0])
        width = max(1.0, abs(center) * 0.25)
        return np.array([center - width, center + width], dtype=float)
    edges = np.histogram_bin_edges(finite, bins="fd")
    if edges.size < 2 or np.allclose(edges[0], edges[-1]):
        lower = float(finite.min())
        upper = float(finite.max())
        if math.isclose(lower, upper):
            width = max(1.0, abs(lower) * 0.25)
            return np.array([lower - width, lower + width], dtype=float)
        return np.linspace(lower, upper, num=7, dtype=float)
    max_edges = _MAX_SHADOW_PRICING_HISTOGRAM_BINS + 1
    if edges.size > max_edges:
        return np.linspace(float(finite.min()), float(finite.max()), num=max_edges, dtype=float)
    return edges.astype(float)


def _residual_histogram_summary(
    df: pl.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
) -> pl.DataFrame:
    valid = df.select(
        *group_cols,
        pl.col(value_col).cast(pl.Float64).alias(value_col),
    ).filter(pl.col(value_col).is_not_null())
    if valid.is_empty():
        return pl.DataFrame(
            schema={
                **{column: pl.Utf8 for column in group_cols},
                "bin_start": pl.Float64,
                "bin_end": pl.Float64,
                "geography_count": pl.Float64,
            }
        )
    rows: list[dict[str, object]] = []
    for group_df in valid.partition_by(group_cols, as_dict=False, maintain_order=True):
        key = {column: group_df[column][0] for column in group_cols}
        values = np.array(group_df[value_col].to_list(), dtype=float)
        zero_mask = np.isclose(values, 0.0)
        zero_count = float(zero_mask.sum())
        nonzero_values = values[~zero_mask]
        if zero_count > 0:
            rows.append(
                {
                    **key,
                    "bin_start": 0.0,
                    "bin_end": 0.0,
                    "geography_count": zero_count,
                }
            )
        if nonzero_values.size == 0:
            continue
        edges = _dynamic_count_bin_edges(nonzero_values.tolist())
        counts, bin_edges = np.histogram(nonzero_values, bins=edges)
        for index, geography_count in enumerate(counts.tolist()):
            rows.append(
                {
                    **key,
                    "bin_start": float(bin_edges[index]),
                    "bin_end": float(bin_edges[index + 1]),
                    "geography_count": float(geography_count),
                }
            )
    return pl.DataFrame(rows).with_columns(
        *[pl.col(column).cast(pl.Utf8) for column in group_cols],
        pl.col("bin_start").cast(pl.Float64),
        pl.col("bin_end").cast(pl.Float64),
        pl.col("geography_count").cast(pl.Float64),
    )


def _workplace_land_use_and_modeled_counts(
    rd: RunData,
    config: Config,
) -> tuple[pl.DataFrame, pl.DataFrame] | None:
    land_use_required = {"MAZ", "employment_count"}
    person_required = {"workplace_zone_id", "is_worker", "finalweight"}
    if not land_use_required.issubset(set(rd.land_use.columns)) or not person_required.issubset(
        set(rd.per.columns)
    ):
        return None

    land_use_base = rd.land_use.select(
        *[
            column
            for _, column in _configured_land_use_geography_dimensions(
                rd.land_use,
                config=config,
            )
        ],
        "employment_count",
    ).filter(pl.col("employment_count").is_not_null())
    worker_base = rd.per.filter(
        _worker_filter_expr() & pl.col("workplace_zone_id").is_not_null()
    ).select(
        "workplace_zone_id",
        "finalweight",
        *_configured_geography_columns(rd.per, config=config, role_prefix="work"),
    )
    land_use_dimensions = _configured_land_use_geography_dimensions(rd.land_use, config=config)
    worker_dimensions = dict(
        _configured_geography_dimensions(
            worker_base,
            config=config,
            base_type="maz" if config.use_maz else "taz",
            base_col="workplace_zone_id",
            role_prefix="work",
        )
    )
    land_use_outputs = []
    worker_outputs = []
    for geography_type, geography_col in land_use_dimensions:
        worker_col = worker_dimensions.get(geography_type)
        if worker_col is None:
            continue
        land_use_outputs.append(
            land_use_base.filter(pl.col(geography_col).is_not_null())
            .group_by(geography_col)
            .agg(employment_count=pl.col("employment_count").sum())
            .rename({geography_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("employment_count").cast(pl.Float64),
            )
            .select("geography_type", "geography_id", "employment_count")
        )
        worker_outputs.append(
            worker_base.filter(pl.col(worker_col).is_not_null())
            .group_by(worker_col)
            .agg(worker_count=pl.col("finalweight").sum())
            .rename({worker_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("worker_count").cast(pl.Float64),
            )
            .select("geography_type", "geography_id", "worker_count")
        )
    if not land_use_outputs or not worker_outputs:
        return None
    land_use_counts = pl.concat(land_use_outputs, how="vertical")
    worker_counts = pl.concat(worker_outputs, how="vertical")
    land_use_all = pl.DataFrame(
        {
            "geography_type": ["all_geographies"],
            "geography_id": ["all_geographies"],
            "employment_count": [float(land_use_base["employment_count"].sum() or 0.0)],
        },
        schema={
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            "employment_count": pl.Float64,
        },
    )
    worker_all = pl.DataFrame(
        {
            "geography_type": ["all_geographies"],
            "geography_id": ["all_geographies"],
            "worker_count": [float(worker_base["finalweight"].sum() or 0.0)],
        },
        schema={
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            "worker_count": pl.Float64,
        },
    )
    return (
        pl.concat([land_use_counts, land_use_all], how="vertical"),
        pl.concat([worker_counts, worker_all], how="vertical"),
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
    aligned = _workplace_land_use_and_modeled_counts(rd, config)
    if aligned is None:
        return empty_summary_frame(workplace_vs_land_use_employment)
    land_use_counts, worker_counts = aligned
    return (
        land_use_counts.join(
            worker_counts,
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
    ).select(
        "home_zone_id",
        "workplace_zone_id",
        "finalweight",
        *_configured_geography_columns(rd.per, config=config, role_prefix="home"),
        *_configured_geography_columns(rd.per, config=config, role_prefix="work"),
    )
    if base.is_empty():
        return empty_summary_frame(commuting_flows)

    home_dimensions = _configured_geography_dimensions(
        base,
        config=config,
        base_type="maz" if config.use_maz else "taz",
        base_col="home_zone_id",
        role_prefix="home",
    )
    work_dimensions = dict(
        _configured_geography_dimensions(
            base,
            config=config,
            base_type="maz" if config.use_maz else "taz",
            base_col="workplace_zone_id",
            role_prefix="work",
        )
    )
    outputs = [
        aggregate_flows(
            base.filter(pl.col(origin_col).is_not_null() & pl.col(destination_col).is_not_null()),
            origin_type=origin_type,
            origin_col=origin_col,
            destination_type=origin_type,
            destination_col=destination_col,
        )
        for origin_type, origin_col in home_dimensions
        if (destination_col := work_dimensions.get(origin_type)) is not None
    ] + [
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


def _school_land_use_and_modeled_counts(
    rd: RunData,
    config: Config,
) -> tuple[pl.DataFrame, pl.DataFrame] | None:
    land_use_required = {"MAZ", "enrollment_count", "student_type"}
    person_required = {"school_zone_id", "is_student", "finalweight", "student_type"}
    if not land_use_required.issubset(set(rd.land_use.columns)) or not person_required.issubset(
        set(rd.per.columns)
    ):
        return None

    land_use_base = rd.land_use.filter(
        pl.col("student_type").is_not_null() & pl.col("enrollment_count").is_not_null()
    ).select(
        "student_type",
        "enrollment_count",
        *[
            column
            for _, column in _configured_land_use_geography_dimensions(
                rd.land_use,
                config=config,
            )
        ],
    )
    student_base = (
        rd.per.filter(_student_filter_expr() & pl.col("school_zone_id").is_not_null())
        .with_columns(student_type=pl.col("student_type").cast(pl.Utf8))
        .filter(pl.col("student_type").is_not_null())
        .select(
            "school_zone_id",
            "student_type",
            "finalweight",
            *_configured_geography_columns(rd.per, config=config, role_prefix="school"),
        )
    )
    land_use_dimensions = _configured_land_use_geography_dimensions(rd.land_use, config=config)
    student_dimensions = dict(
        _configured_geography_dimensions(
            student_base,
            config=config,
            base_type="maz" if config.use_maz else "taz",
            base_col="school_zone_id",
            role_prefix="school",
        )
    )
    land_use_outputs = []
    student_outputs = []
    for geography_type, geography_col in land_use_dimensions:
        student_col = student_dimensions.get(geography_type)
        if student_col is None:
            continue
        land_use_outputs.append(
            land_use_base.filter(pl.col(geography_col).is_not_null())
            .group_by([geography_col, "student_type"])
            .agg(enrollment_count=pl.col("enrollment_count").sum())
            .rename({geography_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("student_type").cast(pl.Utf8),
                pl.col("enrollment_count").cast(pl.Float64),
            )
            .select("geography_type", "geography_id", "student_type", "enrollment_count")
        )
        student_outputs.append(
            student_base.filter(pl.col(student_col).is_not_null())
            .group_by([student_col, "student_type"])
            .agg(student_count=pl.col("finalweight").sum())
            .rename({student_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("student_type").cast(pl.Utf8),
                pl.col("student_count").cast(pl.Float64),
            )
            .select("geography_type", "geography_id", "student_type", "student_count")
        )
    if not land_use_outputs or not student_outputs:
        return None
    land_use_counts = pl.concat(land_use_outputs, how="vertical")
    student_counts = pl.concat(student_outputs, how="vertical")
    land_use_all = (
        land_use_base.group_by("student_type")
        .agg(enrollment_count=pl.col("enrollment_count").sum())
        .with_columns(
            pl.lit("all_geographies").alias("geography_type"),
            pl.lit("all_geographies").alias("geography_id"),
            pl.col("student_type").cast(pl.Utf8),
            pl.col("enrollment_count").cast(pl.Float64),
        )
        .select("geography_type", "geography_id", "student_type", "enrollment_count")
    )
    student_all = (
        student_base.group_by("student_type")
        .agg(student_count=pl.col("finalweight").sum())
        .with_columns(
            pl.lit("all_geographies").alias("geography_type"),
            pl.lit("all_geographies").alias("geography_id"),
            pl.col("student_type").cast(pl.Utf8),
            pl.col("student_count").cast(pl.Float64),
        )
        .select("geography_type", "geography_id", "student_type", "student_count")
    )
    return (
        pl.concat([land_use_counts, land_use_all], how="vertical"),
        pl.concat([student_counts, student_all], how="vertical"),
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
    aligned = _school_land_use_and_modeled_counts(rd, config)
    if aligned is None:
        return empty_summary_frame(school_loc_vs_land_use_enrollment)
    land_use_counts, student_counts = aligned
    return (
        land_use_counts.join(
            student_counts,
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
        "target_count": pl.Float64,
        "modeled_count": pl.Float64,
        "residual_count": pl.Float64,
        "absolute_residual_count": pl.Float64,
        "percent_error": pl.Float64,
    },
    required_columns={
        "land_use": ("MAZ", "employment_count"),
        "per": ("workplace_zone_id", "is_worker", "finalweight"),
    },
)
def workplace_shadow_pricing_residuals(rd: RunData, config: Config) -> pl.DataFrame:
    aligned = _workplace_land_use_and_modeled_counts(rd, config)
    if aligned is None:
        return empty_summary_frame(workplace_shadow_pricing_residuals)
    land_use_counts, worker_counts = aligned
    return _finalize_residual_frame(
        land_use_counts.join(
            worker_counts,
            on=["geography_type", "geography_id"],
            how="full",
            coalesce=True,
        )
        .with_columns(
            pl.col("employment_count").fill_null(0.0).cast(pl.Float64),
            pl.col("worker_count").fill_null(0.0).cast(pl.Float64),
        )
        .with_columns(*_residual_metrics_columns("employment_count", "worker_count"))
    ).sort(["geography_type", "geography_id"])


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "student_type": pl.Utf8,
        "target_count": pl.Float64,
        "modeled_count": pl.Float64,
        "residual_count": pl.Float64,
        "absolute_residual_count": pl.Float64,
        "percent_error": pl.Float64,
    },
    required_columns={
        "land_use": ("MAZ", "enrollment_count", "student_type"),
        "per": ("school_zone_id", "is_student", "finalweight", "student_type"),
    },
)
def school_shadow_pricing_residuals(rd: RunData, config: Config) -> pl.DataFrame:
    aligned = _school_land_use_and_modeled_counts(rd, config)
    if aligned is None:
        return empty_summary_frame(school_shadow_pricing_residuals)
    land_use_counts, student_counts = aligned
    return _finalize_residual_frame(
        land_use_counts.join(
            student_counts,
            on=["geography_type", "geography_id", "student_type"],
            how="full",
            coalesce=True,
        )
        .with_columns(
            pl.col("enrollment_count").fill_null(0.0).cast(pl.Float64),
            pl.col("student_count").fill_null(0.0).cast(pl.Float64),
        )
        .with_columns(*_residual_metrics_columns("enrollment_count", "student_count")),
        group_cols=["student_type"],
    ).sort(["geography_type", "geography_id", "student_type"])


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "bin_start": pl.Float64,
        "bin_end": pl.Float64,
        "geography_count": pl.Float64,
    },
    required_columns={
        "land_use": ("MAZ", "employment_count"),
        "per": ("workplace_zone_id", "is_worker", "finalweight"),
    },
)
def workplace_shadow_pricing_residual_histogram(
    rd: RunData,
    config: Config,
) -> pl.DataFrame:
    residuals = workplace_shadow_pricing_residuals(rd, config)
    if residuals.is_empty():
        return empty_summary_frame(workplace_shadow_pricing_residual_histogram)
    return _residual_histogram_summary(
        residuals,
        group_cols=["geography_type"],
        value_col="residual_count",
    ).sort(["geography_type", "bin_start", "bin_end"])


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "student_type": pl.Utf8,
        "bin_start": pl.Float64,
        "bin_end": pl.Float64,
        "geography_count": pl.Float64,
    },
    required_columns={
        "land_use": ("MAZ", "enrollment_count", "student_type"),
        "per": ("school_zone_id", "is_student", "finalweight", "student_type"),
    },
)
def school_shadow_pricing_residual_histogram(
    rd: RunData,
    config: Config,
) -> pl.DataFrame:
    residuals = school_shadow_pricing_residuals(rd, config)
    if residuals.is_empty():
        return empty_summary_frame(school_shadow_pricing_residual_histogram)
    by_student_type = _residual_histogram_summary(
        residuals,
        group_cols=["geography_type", "student_type"],
        value_col="residual_count",
    )
    all_student_types = (
        _residual_histogram_summary(
            residuals,
            group_cols=["geography_type"],
            value_col="residual_count",
        )
        .with_columns(pl.lit("All").alias("student_type"))
        .select(
            "geography_type",
            "student_type",
            "bin_start",
            "bin_end",
            "geography_count",
        )
    )
    return pl.concat([by_student_type, all_student_types], how="vertical").sort(
        ["geography_type", "student_type", "bin_start", "bin_end"]
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
    ).select(
        "workplace_zone_id",
        "free_parking_at_work",
        "finalweight",
        *_configured_geography_columns(rd.per, config=config, role_prefix="work"),
    )
    if base.is_empty():
        return empty_summary_frame(free_parking)

    return (
        pl.concat(
            [
                aggregate_counts(
                    base,
                    geography_type=geography_type,
                    geography_id_col=geography_col,
                )
                for geography_type, geography_col in _configured_geography_dimensions(
                    base,
                    config=config,
                    base_type="maz" if config.use_maz else "taz",
                    base_col="workplace_zone_id",
                    role_prefix="work",
                )
            ],
            how="vertical",
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
