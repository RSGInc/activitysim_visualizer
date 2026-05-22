"""Geography-oriented tour summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.summary_helpers import (
    _aggregate_counts_across_geographies,
    _aggregate_counts_by_geography,
    _configured_geography_columns,
    _configured_geography_dimensions,
    _summary_purpose_column,
)
from runtime.config import Config


@summary_contract(
    schema={
        "mandatory_tour_purpose": pl.Utf8,
        "geography": pl.Utf8,
        "average_tour_distance": pl.Float64,
    },
    required_columns={"per": ("finalweight",)},
)
def avg_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
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
        univ_s = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (pl.col("is_student").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
        schl_s = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (pl.col("is_student").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
                & (pl.col(ptype_col).cast(pl.Utf8).cast(pl.Int32, strict=False) >= 6)
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
    else:
        univ_s = rd.per.head(0)
        schl_s = rd.per.head(0)

    def _avg_by_geo(persons: pl.DataFrame, purpose_name: str, dist_col: str, geo_col: str = "HGEO") -> pl.DataFrame:
        if dist_col not in persons.columns or len(persons) == 0:
            return pl.DataFrame(
                {
                    "mandatory_tour_purpose": [purpose_name],
                    "geography": ["all_geographies"],
                    "average_tour_distance": [None],
                }
            )
        rows: list[dict[str, object]] = []
        if config.geography_enabled and geo_col in persons.columns:
            groups = sorted(persons[geo_col].drop_nulls().unique().to_list())
            for grp in groups:
                sub = persons.filter(pl.col(geo_col) == grp)
                rows.append(
                    {
                        "mandatory_tour_purpose": purpose_name,
                        "geography": str(grp),
                        "average_tour_distance": sub[dist_col].mean(),
                    }
                )
        rows.append(
            {
                "mandatory_tour_purpose": purpose_name,
                "geography": "all_geographies",
                "average_tour_distance": persons[dist_col].mean(),
            }
        )
        return pl.DataFrame(
            rows,
            schema={
                "mandatory_tour_purpose": pl.Utf8,
                "geography": pl.Utf8,
                "average_tour_distance": pl.Float64,
            },
        )

    result = pl.concat(
        [
            _avg_by_geo(workers, "work", "distance_to_work"),
            _avg_by_geo(univ_s, "university", "distance_to_school"),
            _avg_by_geo(schl_s, "school", "distance_to_school"),
        ],
        how="vertical",
    )
    return result.select(
        "mandatory_tour_purpose",
        "geography",
        "average_tour_distance",
    ).sort(["mandatory_tour_purpose", "geography"])


@summary_contract(
    schema={
        "nonmandatory_tour_purpose": pl.Utf8,
        "geography": pl.Utf8,
        "average_tour_distance": pl.Float64,
    },
    required_columns={
        "tours": ("tour_category", "tour_purpose", "SKIMDIST", "finalweight")
    },
)
def avg_non_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_category", "tour_purpose", "SKIMDIST", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(avg_non_mand_tour_distance)

    tours = rd.tours.filter(
        (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
        & pl.col("tour_purpose").is_not_null()
        & pl.col("SKIMDIST").is_not_null()
        & pl.col("finalweight").is_not_null()
    )
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(avg_non_mand_tour_distance)
    tours = tours.with_columns(pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"))
    if tours.is_empty():
        return empty_summary_frame(avg_non_mand_tour_distance)

    def _weighted_avg_by_geo(df: pl.DataFrame, purpose_name: str, geo_col: str = "HGEO") -> pl.DataFrame:
        rows: list[dict[str, object]] = []
        if config.geography_enabled and geo_col in df.columns:
            groups = sorted(df[geo_col].drop_nulls().unique().to_list())
            for grp in groups:
                sub = df.filter(pl.col(geo_col) == grp)
                weight_sum = sub["finalweight"].sum()
                avg_dist = None if weight_sum in (None, 0) else (sub["SKIMDIST"] * sub["finalweight"]).sum() / weight_sum
                rows.append(
                    {
                        "nonmandatory_tour_purpose": purpose_name,
                        "geography": str(grp),
                        "average_tour_distance": avg_dist,
                    }
                )
        total_weight = df["finalweight"].sum()
        total_avg = None if total_weight in (None, 0) else (df["SKIMDIST"] * df["finalweight"]).sum() / total_weight
        rows.append(
            {
                "nonmandatory_tour_purpose": purpose_name,
                "geography": "all_geographies",
                "average_tour_distance": total_avg,
            }
        )
        return pl.DataFrame(
            rows,
            schema={
                "nonmandatory_tour_purpose": pl.Utf8,
                "geography": pl.Utf8,
                "average_tour_distance": pl.Float64,
            },
        )

    purposes = (
        tours.select("tour_purpose")
        .unique()
        .drop_nulls()
        .sort("tour_purpose")
        .get_column("tour_purpose")
        .to_list()
    )
    result = pl.concat(
        [
            _weighted_avg_by_geo(
                tours.filter(pl.col("tour_purpose") == purpose),
                str(purpose),
            )
            for purpose in purposes
        ],
        how="vertical",
    )
    return (
        result.with_columns(
            pl.col("nonmandatory_tour_purpose").cast(pl.Utf8),
            pl.col("geography").cast(pl.Utf8),
            pl.col("average_tour_distance").cast(pl.Float64),
        )
        .select(
            "nonmandatory_tour_purpose",
            "geography",
            "average_tour_distance",
        )
        .sort(["nonmandatory_tour_purpose", "geography"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "internal_nonmandatory_tour_count": pl.Float64,
        "external_nonmandatory_tour_count": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "home_zone_id"),
        "tours": ("person_id", "tour_category", "is_external_tour", "finalweight"),
    },
)
def int_vs_ext_non_mand_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"person_id", "home_zone_id"}
    tour_required = {"person_id", "tour_category", "is_external_tour", "finalweight"}
    if not person_required.issubset(set(rd.per.columns)) or not tour_required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(int_vs_ext_non_mand_tour_freq)

    base = (
        rd.tours.filter(
            (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
            & pl.col("person_id").is_not_null()
            & pl.col("is_external_tour").is_not_null()
        )
        .join(
            rd.per.select(
                "person_id",
                "home_zone_id",
                *_configured_geography_columns(
                    rd.per,
                    config=config,
                    role_prefix="home",
                ),
            ),
            on="person_id",
            how="inner",
        )
        .filter(pl.col("home_zone_id").is_not_null())
        .select(
            "home_zone_id",
            "is_external_tour",
            "finalweight",
            *_configured_geography_columns(rd.per, config=config, role_prefix="home"),
        )
    )
    if base.is_empty():
        return empty_summary_frame(int_vs_ext_non_mand_tour_freq)

    geography_dimensions = _configured_geography_dimensions(
        base,
        config=config,
        base_type="maz" if config.use_maz else "taz",
        base_col="home_zone_id",
        role_prefix="home",
    )
    outputs = []
    for geography_type, geography_col in geography_dimensions:
        outputs.append(
            base.filter(pl.col(geography_col).is_not_null())
            .group_by(geography_col)
            .agg(
                internal_nonmandatory_tour_count=pl.when(~pl.col("is_external_tour"))
                .then(pl.col("finalweight"))
                .otherwise(0.0)
                .sum(),
                external_nonmandatory_tour_count=pl.when(pl.col("is_external_tour"))
                .then(pl.col("finalweight"))
                .otherwise(0.0)
                .sum(),
            )
            .rename({geography_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("internal_nonmandatory_tour_count").cast(pl.Float64),
                pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
            )
            .select(
                "geography_type",
                "geography_id",
                "internal_nonmandatory_tour_count",
                "external_nonmandatory_tour_count",
            )
        )

    outputs.append(
        base.select(
            pl.lit("all_geographies").alias("geography_type"),
            pl.lit("all_geographies").alias("geography_id"),
            pl.when(~pl.col("is_external_tour"))
            .then(pl.col("finalweight"))
            .otherwise(0.0)
            .sum()
            .cast(pl.Float64)
            .alias("internal_nonmandatory_tour_count"),
            pl.when(pl.col("is_external_tour"))
            .then(pl.col("finalweight"))
            .otherwise(0.0)
            .sum()
            .cast(pl.Float64)
            .alias("external_nonmandatory_tour_count"),
        )
    )

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("internal_nonmandatory_tour_count").cast(pl.Float64),
            pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "internal_nonmandatory_tour_count",
            "external_nonmandatory_tour_count",
        )
        .sort(["geography_type", "geography_id"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "external_nonmandatory_tour_count": pl.Float64,
    },
    required_columns={
        "tours": ("tour_category", "is_external_tour", "destination", "finalweight")
    },
)
def ext_non_mand_tour_loc(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "tour_category",
        "is_external_tour",
        "destination",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(ext_non_mand_tour_loc)

    base = rd.tours.filter(
        (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
        & (pl.col("is_external_tour") == True)
        & pl.col("destination").is_not_null()
    ).select(
        "destination",
        "finalweight",
        *_configured_geography_columns(rd.tours, config=config, role_prefix="destination"),
    )
    if base.is_empty():
        return empty_summary_frame(ext_non_mand_tour_loc)

    outputs = [
        _aggregate_counts_across_geographies(
            base,
            geography_dimensions=_configured_geography_dimensions(
                base,
                config=config,
                base_type="maz" if config.use_maz else "taz",
                base_col="destination",
                role_prefix="destination",
            ),
            value_col="external_nonmandatory_tour_count",
        ),
        base.select(
            pl.lit("all_geographies").alias("geography_type"),
            pl.lit("all_geographies").alias("geography_id"),
            pl.col("finalweight")
            .sum()
            .cast(pl.Float64)
            .alias("external_nonmandatory_tour_count"),
        ),
    ]
    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "external_nonmandatory_tour_count",
        )
        .sort(["geography_type", "geography_id"])
    )
