"""Geography-oriented tour summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    aggregate_counts_across_geographies,
    _configured_geography_columns,
    _configured_geography_dimensions,
    aggregate_weighted_average_across_geographies,
    _summary_purpose_column,
)
from runtime.config import Config


@summary(
    id="average_mandatory_tour_distance_by_purpose_and_geography",
    schema={
        "mandatory_tour_purpose": pl.Utf8,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "average_tour_distance": pl.Float64,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("finalweight", "home_zone_id")},
)
def avg_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    ptype_col = "person_type" if "person_type" in rd.per.columns else None

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
        if {"is_worker", "workplace_zone_id"}.issubset(rd.per.columns)
        else rd.per.head(0)
    )

    if ptype_col is not None:
        univ_s = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (
                    pl.col("is_student")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .is_in(["true", "1"])
                )
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if {"is_student", "school_zone_id"}.issubset(rd.per.columns)
            else rd.per.head(0)
        )
        schl_s = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (
                    pl.col("is_student")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .is_in(["true", "1"])
                )
                & (pl.col(ptype_col).cast(pl.Utf8).cast(pl.Int32, strict=False) >= 6)
            )
            if {"is_student", "school_zone_id"}.issubset(rd.per.columns)
            else rd.per.head(0)
        )
    else:
        univ_s = rd.per.head(0)
        schl_s = rd.per.head(0)

    def _avg_by_geo(
        persons: pl.DataFrame, purpose_name: str, dist_col: str
    ) -> pl.DataFrame:
        if dist_col not in persons.columns or len(persons) == 0:
            return pl.DataFrame(
                schema={
                    "mandatory_tour_purpose": pl.Utf8,
                    "geography_type": pl.Utf8,
                    "geography_id": pl.Utf8,
                    "average_tour_distance": pl.Float64,
                    "person_count": pl.Float64,
                }
            )
        base = persons.select(
            "finalweight",
            dist_col,
            "home_zone_id",
            *_configured_geography_columns(
                persons,
                config=config,
                role_prefix="home",
            ),
        ).filter(pl.col(dist_col).is_not_null() & pl.col("finalweight").is_not_null())
        if base.is_empty():
            return pl.DataFrame(
                schema={
                    "mandatory_tour_purpose": pl.Utf8,
                    "geography_type": pl.Utf8,
                    "geography_id": pl.Utf8,
                    "average_tour_distance": pl.Float64,
                    "person_count": pl.Float64,
                }
            )
        outputs = [
            aggregate_weighted_average_across_geographies(
                base,
                geography_dimensions=_configured_geography_dimensions(
                    base,
                    config=config,
                    base_type="maz" if config.use_maz else "taz",
                    base_col="home_zone_id",
                    role_prefix="home",
                ),
                value_col=dist_col,
                output_col="average_tour_distance",
                count_col="person_count",
            ),
            base.select(
                pl.lit("all_geographies").alias("geography_type"),
                pl.lit("all_geographies").alias("geography_id"),
                (
                    (pl.col(dist_col) * pl.col("finalweight")).sum()
                    / pl.col("finalweight").sum()
                )
                .cast(pl.Float64)
                .alias("average_tour_distance"),
                pl.col("finalweight").sum().cast(pl.Float64).alias("person_count"),
            ),
        ]
        return (
            pl.concat(outputs, how="vertical")
            .with_columns(
                pl.lit(purpose_name).alias("mandatory_tour_purpose"),
                pl.col("geography_type").cast(pl.Utf8),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("average_tour_distance").cast(pl.Float64),
                pl.col("person_count").cast(pl.Float64),
            )
            .select(
                "mandatory_tour_purpose",
                "geography_type",
                "geography_id",
                "average_tour_distance",
                "person_count",
            )
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
        "geography_type",
        "geography_id",
        "average_tour_distance",
        "person_count",
    ).sort(["mandatory_tour_purpose", "geography_type", "geography_id"])


@summary(
    id="average_nonmandatory_tour_distance_by_purpose_and_geography",
    schema={
        "nonmandatory_tour_purpose": pl.Utf8,
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "average_tour_distance": pl.Float64,
        "tour_count": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "home_zone_id"),
        "tours": (
            "person_id",
            "tour_category",
            "tour_purpose",
            "SKIMDIST",
            "finalweight",
        ),
    },
)
def avg_non_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"person_id", "home_zone_id"}
    tour_required = {
        "person_id",
        "tour_category",
        "tour_purpose",
        "SKIMDIST",
        "finalweight",
    }
    if not person_required.issubset(set(rd.per.columns)) or not tour_required.issubset(
        set(rd.tours.columns)
    ):
        return avg_non_mand_tour_distance.empty()

    tours = rd.tours.filter(
        (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
        & pl.col("person_id").is_not_null()
        & pl.col("tour_purpose").is_not_null()
        & pl.col("SKIMDIST").is_not_null()
        & pl.col("finalweight").is_not_null()
    )
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return avg_non_mand_tour_distance.empty()
    base = (
        tours.with_columns(pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"))
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
            "tour_purpose",
            "SKIMDIST",
            "finalweight",
            "home_zone_id",
            *_configured_geography_columns(
                rd.per,
                config=config,
                role_prefix="home",
            ),
        )
    )
    if base.is_empty():
        return avg_non_mand_tour_distance.empty()

    outputs = [
        aggregate_weighted_average_across_geographies(
            base,
            geography_dimensions=_configured_geography_dimensions(
                base,
                config=config,
                base_type="maz" if config.use_maz else "taz",
                base_col="home_zone_id",
                role_prefix="home",
            ),
            value_col="SKIMDIST",
            output_col="average_tour_distance",
            group_cols=["tour_purpose"],
            count_col="tour_count",
        )
        .rename({"tour_purpose": "nonmandatory_tour_purpose"})
        .select(
            "nonmandatory_tour_purpose",
            "geography_type",
            "geography_id",
            "average_tour_distance",
            "tour_count",
        ),
        (
            base.group_by("tour_purpose")
            .agg(
                average_tour_distance=(
                    (pl.col("SKIMDIST") * pl.col("finalweight")).sum()
                    / pl.col("finalweight").sum()
                ).cast(pl.Float64),
                tour_count=pl.col("finalweight").sum().cast(pl.Float64),
            )
            .rename({"tour_purpose": "nonmandatory_tour_purpose"})
            .with_columns(
                pl.lit("all_geographies").alias("geography_type"),
                pl.lit("all_geographies").alias("geography_id"),
            )
            .select(
                "nonmandatory_tour_purpose",
                "geography_type",
                "geography_id",
                "average_tour_distance",
                "tour_count",
            )
        ),
    ]
    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("nonmandatory_tour_purpose").cast(pl.Utf8),
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("average_tour_distance").cast(pl.Float64),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select(
            "nonmandatory_tour_purpose",
            "geography_type",
            "geography_id",
            "average_tour_distance",
            "tour_count",
        )
        .sort(["nonmandatory_tour_purpose", "geography_type", "geography_id"])
    )


@summary(
    id="internal_external_nonmandatory_tour_frequency_by_home_geography",
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
    if not person_required.issubset(set(rd.per.columns)) or not tour_required.issubset(
        set(rd.tours.columns)
    ):
        return int_vs_ext_non_mand_tour_freq.empty()

    base = (
        rd.tours.filter(
            (
                pl.col("tour_category").cast(pl.Utf8).str.to_lowercase()
                == "non_mandatory"
            )
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
        return int_vs_ext_non_mand_tour_freq.empty()

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


@summary(
    id="external_nonmandatory_tour_locations",
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
        return ext_non_mand_tour_loc.empty()

    base = rd.tours.filter(
        (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
        & (pl.col("is_external_tour") == True)
        & pl.col("destination").is_not_null()
    ).select(
        "destination",
        "finalweight",
        *_configured_geography_columns(
            rd.tours, config=config, role_prefix="destination"
        ),
    )
    if base.is_empty():
        return ext_non_mand_tour_loc.empty()

    outputs = [
        aggregate_counts_across_geographies(
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
