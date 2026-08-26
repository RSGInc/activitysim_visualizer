"""Long-term travel distance distributions."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import output_schema, summary
from processor.summarize.summaries.long_term_shared import (
    _internal_non_wfh_workers,
    _student_filter_expr,
)
from processor.summarize.summaries.summary_helpers import (
    _configured_geography_columns,
    _configured_geography_dimensions,
    _distance_bin_expr,
    _distance_bin_labels,
    _distance_bin_sort_expr,
)
from runtime.config import Config


@output_schema(
    schema={
        "distance_bin": pl.Utf8,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    }
)
def tlfd(rd: RunData, config: Config) -> dict[str, pl.DataFrame]:
    def _bin_dist(df: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        return df.with_columns(_distance_bin_expr(dist_col, cap_value=51)).filter(
            pl.col("distance_bin").is_not_null()
        )

    def _make_tlfd(persons: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        empty = work_tlfd.empty()
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
        if df.is_empty():
            return empty
        distance_bins = pl.DataFrame(
            {"distance_bin": _distance_bin_labels(51)},
            schema={"distance_bin": pl.Utf8},
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
                .select(
                    "distance_bin", "geography_type", "geography_id", "person_count"
                )
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
            .with_columns(_distance_bin_sort_expr().alias("_sort_distance"))
            .sort(["geography_type", "geography_id", "_sort_distance"])
            .drop("_sort_distance")
            .select("distance_bin", "geography_type", "geography_id", "person_count")
        )

    ptype_col = "person_type" if "person_type" in rd.per.columns else None
    workers = _internal_non_wfh_workers(rd.per)

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


@summary(
    id="work_location_distance_distribution_by_geography",
    schema={
        "distance_bin": pl.Utf8,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={
        "per": (
            "distance_to_work",
            "external_workplace_zone_id",
            "finalweight",
            "is_external_worker",
            "is_worker",
            "work_from_home",
            "workplace_zone_id",
        )
    },
)
def work_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["work"]


@summary(
    id="university_location_distance_distribution_by_geography",
    schema={
        "distance_bin": pl.Utf8,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_school", "finalweight")},
)
def univ_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["univ"]


@summary(
    id="school_location_distance_distribution_by_geography",
    schema={
        "distance_bin": pl.Utf8,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("distance_to_school", "finalweight")},
)
def schl_tlfd(rd: RunData, config: Config) -> pl.DataFrame:
    return tlfd(rd, config)["schl"]
