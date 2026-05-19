"""Person-oriented long-term summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.long_term_shared import (
    _person_type_distribution_with_total,
    _person_type_label_expr,
    _worker_filter_expr,
)
from runtime.config import Config


@summary_contract(
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
        return empty_summary_frame(license_holding_status)

    base = rd.per.filter(
        pl.col("person_type").is_not_null()
        & pl.col("has_license").is_not_null()
        & pl.col("age").is_not_null()
        & (pl.col("age") >= 16)
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


@summary_contract(
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
        return empty_summary_frame(bicycle_comfort_level)

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


@summary_contract(
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
        return empty_summary_frame(transit_pass)

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


@summary_contract(
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
        return empty_summary_frame(transit_subsidy)

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


@summary_contract(
    schema={
        "telecommute_frequency": pl.Utf8,
        "person_count": pl.Float64,
    },
    required_columns={
        "per": ("telecommute_frequency", "finalweight", "is_worker", "work_from_home")
    },
)
def telecommute(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    if not {
        "telecommute_frequency",
        "finalweight",
        "is_worker",
        "work_from_home",
    }.issubset(rd.per.columns):
        return empty_summary_frame(telecommute)

    return (
        rd.per.filter(
            pl.col("telecommute_frequency").is_not_null()
            & (pl.col("telecommute_frequency") != "")
            & _worker_filter_expr()
            & ~pl.col("work_from_home")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes", "work_from_home", "home"])
        )
        .group_by("telecommute_frequency")
        .agg(person_count=pl.col("finalweight").sum())
        .sort("telecommute_frequency")
    )
