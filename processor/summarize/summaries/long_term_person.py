"""Person-oriented long-term summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.long_term_shared import (
    _person_type_distribution_with_total,
    _person_type_label_expr,
    _worker_filter_expr,
)
from processor.summarize.summaries.summary_helpers import (
    _configured_geography_columns,
    _configured_geography_dimensions,
)
from runtime.config import Config


@summary(
    id="license_holding_status_distribution",
    schema={
        "person_type": pl.Utf8,
        "license_holding_status": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "has_license", "finalweight", "age")},
)
def license_holding_status(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"person_type", "has_license", "finalweight", "age"}
    if not required.issubset(set(rd.per.columns)):
        return license_holding_status.empty()

    eligible_driver = (
        pl.col("can_drive").cast(pl.Int64, strict=False).is_in([1, 3])
        if "can_drive" in rd.per.columns
        else pl.col("age") >= 16
    )
    base = rd.per.filter(
        pl.col("person_type").is_not_null()
        & pl.col("has_license").is_not_null()
        & eligible_driver
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.when(pl.col("has_license"))
        .then(pl.lit("has_license"))
        .otherwise(pl.lit("no_license"))
        .alias("license_holding_status"),
    )

    return (
        _person_type_distribution_with_total(
            base,
            category_col="license_holding_status",
        )
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("license_holding_status").cast(pl.Utf8),
            _person_type_label_expr(config),
            pl.col("person_count").cast(pl.Float64),
        )
        .select(
            "person_type",
            "license_holding_status",
            "person_type_label",
            "person_count",
        )
        .sort(["person_type", "license_holding_status"])
    )


@summary(
    id="bicycle_comfort_level_distribution",
    schema={
        "person_type": pl.Utf8,
        "bicycle_comfort_level": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "bike_comfort", "finalweight")},
)
def bicycle_comfort_level(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"person_type", "bike_comfort", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return bicycle_comfort_level.empty()

    base = rd.per.filter(
        pl.col("person_type").is_not_null() & pl.col("bike_comfort").is_not_null()
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.col("bike_comfort").cast(pl.Utf8).alias("bicycle_comfort_level"),
    )

    return (
        _person_type_distribution_with_total(
            base,
            category_col="bicycle_comfort_level",
        )
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("bicycle_comfort_level").cast(pl.Utf8),
            _person_type_label_expr(config),
            pl.col("person_count").cast(pl.Float64),
        )
        .select(
            "person_type",
            "bicycle_comfort_level",
            "person_type_label",
            "person_count",
        )
        .sort(["person_type", "bicycle_comfort_level"])
    )


@summary(
    id="transit_pass_ownership_by_person_type",
    schema={
        "person_type": pl.Utf8,
        "transit_pass_ownership_status": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={"per": ("person_type", "transit_pass_ownership", "finalweight")},
)
def transit_pass(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"person_type", "transit_pass_ownership", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return transit_pass.empty()

    base = rd.per.filter(
        pl.col("person_type").is_not_null()
        & pl.col("transit_pass_ownership").is_not_null()
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.when(pl.col("transit_pass_ownership") == True)
        .then(pl.lit("has_transit_pass"))
        .otherwise(pl.lit("no_transit_pass"))
        .alias("transit_pass_ownership_status"),
    )

    return (
        _person_type_distribution_with_total(
            base,
            category_col="transit_pass_ownership_status",
        )
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("transit_pass_ownership_status").cast(pl.Utf8),
            _person_type_label_expr(config),
            pl.col("person_count").cast(pl.Float64),
        )
        .select(
            "person_type",
            "transit_pass_ownership_status",
            "person_type_label",
            "person_count",
        )
        .sort(["person_type", "transit_pass_ownership_status"])
    )


@summary(
    id="transit_subsidy_by_person_type",
    schema={
        "person_type": pl.Utf8,
        "transit_subsidy_status": pl.Utf8,
        "transit_subsidy_label": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={
        "per": (
            "person_type",
            "transit_pass_subsidy",
            "is_worker",
            "is_student",
            "finalweight",
        )
    },
)
def transit_subsidy(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "person_type",
        "transit_pass_subsidy",
        "is_worker",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return transit_subsidy.empty()

    base = rd.per.filter(
        pl.col("person_type").is_not_null()
        & pl.col("transit_pass_subsidy").is_not_null()
        & _worker_filter_expr()
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.col("transit_pass_subsidy").cast(pl.Utf8).alias("transit_subsidy_status"),
    )

    return (
        _person_type_distribution_with_total(
            base,
            category_col="transit_subsidy_status",
        )
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("transit_subsidy_status").cast(pl.Utf8),
            pl.col("transit_subsidy_status")
            .map_elements(config.transit_subsidy_label, return_dtype=pl.Utf8)
            .alias("transit_subsidy_label"),
            _person_type_label_expr(config),
            pl.col("person_count").cast(pl.Float64),
        )
        .select(
            "person_type",
            "transit_subsidy_status",
            "transit_subsidy_label",
            "person_type_label",
            "person_count",
        )
        .sort(["person_type", "transit_subsidy_status"])
    )


@summary(
    id="telecommute_frequency_distribution",
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "telecommute_frequency": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={
        "per": (
            "telecommute_frequency",
            "finalweight",
            "is_worker",
            "work_from_home",
            "home_zone_id",
        )
    },
)
def telecommute(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    if not {
        "telecommute_frequency",
        "finalweight",
        "is_worker",
        "work_from_home",
        "home_zone_id",
    }.issubset(rd.per.columns):
        return telecommute.empty()

    base = rd.per.filter(
        pl.col("telecommute_frequency").is_not_null()
        & (pl.col("telecommute_frequency") != "")
        & _worker_filter_expr()
        & ~pl.col("work_from_home")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "work_from_home", "home"])
    ).select(
        "telecommute_frequency",
        "finalweight",
        "home_zone_id",
        *_configured_geography_columns(rd.per, config=config, role_prefix="home"),
    )
    if base.is_empty():
        return telecommute.empty()

    outputs: list[pl.DataFrame] = []
    for geography_type, geography_col in _configured_geography_dimensions(
        base,
        config=config,
        base_type="maz" if config.use_maz else "taz",
        base_col="home_zone_id",
        role_prefix="home",
    ):
        outputs.append(
            base.filter(pl.col(geography_col).is_not_null())
            .group_by([geography_col, "telecommute_frequency"])
            .agg(person_count=pl.col("finalweight").sum())
            .rename({geography_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("telecommute_frequency").cast(pl.Utf8),
                pl.col("person_count").cast(pl.Float64),
            )
            .select(
                "geography_type",
                "geography_id",
                "telecommute_frequency",
                "person_count",
            )
        )

    outputs.append(
        base.group_by("telecommute_frequency")
        .agg(person_count=pl.col("finalweight").sum())
        .with_columns(
            pl.lit("all_geographies").alias("geography_type"),
            pl.lit("all_geographies").alias("geography_id"),
            pl.col("telecommute_frequency").cast(pl.Utf8),
            pl.col("person_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "telecommute_frequency",
            "person_count",
        )
    )

    return pl.concat(outputs, how="vertical").sort(
        ["geography_type", "geography_id", "telecommute_frequency"]
    )
