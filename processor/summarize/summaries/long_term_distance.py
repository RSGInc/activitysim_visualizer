"""Long-term travel distance distributions."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.long_term_shared import _student_filter_expr
from processor.summarize.summaries.summary_helpers import (
    _configured_geography_columns,
    _configured_geography_dimensions,
)
from runtime.config import Config


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    }
)
def tlfd(rd: RunData, config: Config) -> dict[str, pl.DataFrame]:
    def _bin_dist(df: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        return df.with_columns(
            pl.col(dist_col).fill_null(0.0).clip(0, 9999)
        ).with_columns(
            (pl.col(dist_col).cast(pl.Int32) + 1).clip(1, 51).alias("distance_bin")
        )

    def _make_tlfd(persons: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        empty = empty_summary_frame(work_tlfd)
        if dist_col not in persons.columns:
            return empty

        df = _bin_dist(
            persons.select(
                dist_col,
                "finalweight",
                "home_zone_id",
                *_configured_geography_columns(
                    persons,
                    config=config,
                    role_prefix="home",
                ),
            ),
            dist_col,
        )
        distance_bins = pl.DataFrame(
            {"distance_bin": list(range(1, 52))}, schema={"distance_bin": pl.Int32}
        )

        outputs: list[pl.DataFrame] = []
        for geography_type, geography_col in _configured_geography_dimensions(
            df,
            config=config,
            base_type="maz" if config.use_maz else "taz",
            base_col="home_zone_id",
            role_prefix="home",
        ):
            geographies = (
                df.filter(pl.col(geography_col).is_not_null())
                .select(pl.col(geography_col).cast(pl.Utf8).alias("geography_id"))
                .drop_nulls()
                .unique()
                .sort("geography_id")
            )
            if geographies.is_empty():
                continue
            by_geo = (
                df.filter(pl.col(geography_col).is_not_null())
                .with_columns(pl.col(geography_col).cast(pl.Utf8).alias("geography_id"))
                .group_by(["distance_bin", "geography_id"])
                .agg(person_count=pl.col("finalweight").sum())
            )
            outputs.append(
                distance_bins.join(geographies, how="cross")
                .join(by_geo, on=["distance_bin", "geography_id"], how="left")
                .with_columns(
                    pl.lit(geography_type).alias("geography_type"),
                    pl.col("person_count").fill_null(0.0).cast(pl.Float64),
                )
                .select("distance_bin", "geography_type", "geography_id", "person_count")
            )

        total = (
            df.group_by("distance_bin")
            .agg(person_count=pl.col("finalweight").sum())
            .with_columns(
                pl.lit("all_geographies").alias("geography_type"),
                pl.lit("all_geographies").alias("geography_id"),
            )
            .select("distance_bin", "geography_type", "geography_id", "person_count")
        )
        outputs.append(
            distance_bins.with_columns(
                pl.lit("all_geographies").alias("geography_type"),
                pl.lit("all_geographies").alias("geography_id"),
            )
            .join(
                total,
                on=["distance_bin", "geography_type", "geography_id"],
                how="left",
            )
            .with_columns(pl.col("person_count").fill_null(0.0).cast(pl.Float64))
            .select("distance_bin", "geography_type", "geography_id", "person_count")
        )

        return (
            pl.concat(outputs, how="vertical")
            .sort(["geography_type", "geography_id", "distance_bin"])
            .select("distance_bin", "geography_type", "geography_id", "person_count")
        )

    ptype_col = "person_type" if "person_type" in rd.per.columns else None
    workers = (
        rd.per.filter(
            (pl.col("workplace_zone_id") > 0)
            & (pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
        )
        if "is_worker" in rd.per.columns
        else rd.per.head(0)
    )

    if ptype_col is not None:
        univ = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & _student_filter_expr()
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
        schl = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & _student_filter_expr()
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


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_work", "finalweight")},
)
def work_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["work"]


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_school", "finalweight")},
)
def univ_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["univ"]


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_school", "finalweight")},
)
def schl_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["schl"]
