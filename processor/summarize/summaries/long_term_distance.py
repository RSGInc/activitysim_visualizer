"""Long-term travel distance distributions."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.long_term_shared import _student_filter_expr
from runtime.config import Config


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography": pl.Utf8,
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

        df = _bin_dist(persons, dist_col)
        distance_bins = pl.DataFrame(
            {"distance_bin": list(range(1, 52))}, schema={"distance_bin": pl.Int32}
        )

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
        "geography": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_work", "finalweight")},
)
def work_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["work"]


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_school", "finalweight")},
)
def univ_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["univ"]


@summary_contract(
    schema={
        "distance_bin": pl.Int32,
        "geography": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_school", "finalweight")},
)
def schl_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["schl"]
