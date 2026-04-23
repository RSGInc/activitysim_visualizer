"""Long Term summaries."""

import polars as pl

from runtime.config import Config
from processor.models import RunData


def license_holding_status(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "person_type": pl.Utf8,
        "license_holding_status": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    }

    required = {"person_type", "has_license", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return pl.DataFrame(schema=result_schema)

    base = rd.per.filter(
        pl.col("person_type").is_not_null() & pl.col("has_license").is_not_null()
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.when(pl.col("has_license"))
        .then(pl.lit("has_license"))
        .otherwise(pl.lit("no_license"))
        .alias("license_holding_status"),
    )

    by_person_type = base.group_by(["person_type", "license_holding_status"]).agg(
        person_count=pl.col("finalweight").sum()
    )

    all_person_types = (
        base.with_columns(pl.lit("all_person_types").alias("person_type"))
        .group_by(["person_type", "license_holding_status"])
        .agg(person_count=pl.col("finalweight").sum())
    )

    return (
        pl.concat([by_person_type, all_person_types], how="vertical")
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("license_holding_status").cast(pl.Utf8),
            pl.col("person_type")
            .map_elements(
                lambda x: (
                    "All Person Types"
                    if x == "all_person_types"
                    else config.person_type_label(x)
                ),
                return_dtype=pl.Utf8,
            )
            .alias("person_type_label"),
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


def bicycle_comfort_level(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "person_type": pl.Utf8,
        "bicycle_comfort_level": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    }

    required = {"person_type", "bike_comfort", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return pl.DataFrame(schema=result_schema)

    base = rd.per.filter(
        pl.col("person_type").is_not_null() & pl.col("bike_comfort").is_not_null()
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.col("bike_comfort").cast(pl.Utf8).alias("bicycle_comfort_level"),
    )

    by_person_type = base.group_by(["person_type", "bicycle_comfort_level"]).agg(
        person_count=pl.col("finalweight").sum()
    )

    all_person_types = (
        base.with_columns(pl.lit("all_person_types").alias("person_type"))
        .group_by(["person_type", "bicycle_comfort_level"])
        .agg(person_count=pl.col("finalweight").sum())
    )

    return (
        pl.concat([by_person_type, all_person_types], how="vertical")
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("bicycle_comfort_level").cast(pl.Utf8),
            pl.col("person_type")
            .map_elements(
                lambda x: (
                    "All Person Types"
                    if x == "all_person_types"
                    else config.person_type_label(x)
                ),
                return_dtype=pl.Utf8,
            )
            .alias("person_type_label"),
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


def av_ownership(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "household_with_autonomous_vehicle_count": pl.Float64,
    }

    required = {"av_ownership", "finalweight"}
    if not required.issubset(set(rd.hh.columns)):
        return pl.DataFrame(schema=result_schema)

    return rd.hh.filter(pl.col("av_ownership") == True).select(
        pl.col("finalweight")
        .sum()
        .cast(pl.Float64)
        .alias("household_with_autonomous_vehicle_count")
    )


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

    RESULT_SCHEMA = {
        "geography": pl.Utf8,
        "worker_count": pl.Float64,
        "work_from_home_worker_count": pl.Float64,
    }
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
        by_geo = pl.DataFrame(schema=RESULT_SCHEMA)

    total = workers.select(
        geography=pl.lit("all_geographies"),
        worker_count=pl.col("finalweight").sum(),
        work_from_home_worker_count=(
            pl.col("finalweight") * pl.col("_is_wfh").cast(pl.Float64)
        ).sum(),
    )

    return pl.concat([by_geo, total]).sort("geography")


def _empty_internal_external_worker_by_geography() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            "internal_worker_count": pl.Float64,
            "external_worker_count": pl.Float64,
        }
    )


def _empty_external_worker_workplace_locations() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            "external_worker_count": pl.Float64,
        }
    )


def _worker_filter_expr() -> pl.Expr:
    # rd.per["is_worker"] is documented as a large_string column in the uploaded schema,
    # so this handles both string- and bool-like encodings defensively.
    return (
        pl.col("is_worker")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "worker"])
    )


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


def internal_vs_external(rd: RunData, config: Config) -> pl.DataFrame:
    """
    Always emits MAZ/home_zone_id rows.
    May also emit configured geography aggregations if the repo exposes
    a geography lookup/mapping helper in config.
    """
    required = {
        "is_worker",
        "is_external_worker",
        "home_zone_id",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return _empty_internal_external_worker_by_geography()

    base = rd.per.filter(
        _worker_filter_expr()
        & pl.col("is_external_worker").is_not_null()
        & pl.col("home_zone_id").is_not_null()
    ).select("home_zone_id", "is_external_worker", "finalweight")

    if base.is_empty():
        return _empty_internal_external_worker_by_geography()

    outputs = [
        _aggregate_internal_external_counts(
            base,
            geography_type="maz",
            geography_id_col="home_zone_id",
        )
    ]

    # TODO: Need to update below for geographic aggregation

    # Adapt this block to your repo's existing geography config/helper pattern.
    # The primer says geography-aware summaries may aggregate to configured
    # geographies when a MAZ-to-geography lookup is provided.
    #
    # Example expected pattern:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.home_maz_geography_lookups():
    #         # lookup_df must map home_zone_id -> geography_id
    #         geo_df = (
    #             base.join(lookup_df, on="home_zone_id", how="inner")
    #             .pipe(_aggregate_internal_external_counts, geography_type, "geography_id")
    #         )
    #         outputs.append(geo_df)

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


def external_workplace_loc(rd: RunData, config: Config) -> pl.DataFrame:
    """
    Always emits MAZ/external_workplace_zone_id rows.
    May also emit configured geography aggregations if the repo exposes
    an external-workplace geography lookup/mapping helper in config.
    """
    required = {
        "is_external_worker",
        "external_workplace_zone_id",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return _empty_external_worker_workplace_locations()

    base = rd.per.filter(
        (pl.col("is_external_worker") == True)
        & pl.col("external_workplace_zone_id").is_not_null()
    ).select("external_workplace_zone_id", "finalweight")

    if base.is_empty():
        return _empty_external_worker_workplace_locations()

    outputs = [
        _aggregate_external_worker_counts(
            base,
            geography_type="maz",
            geography_id_col="external_workplace_zone_id",
        )
    ]

    # TODO Update to match geographic aggregation API
    # Adapt this block to your repo's actual config/helper API.
    # Example expected pattern:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.external_workplace_maz_geography_lookups():
    #         # lookup_df must map external_workplace_zone_id -> geography_id
    #         geo_df = (
    #             base.join(lookup_df, on="external_workplace_zone_id", how="inner")
    #             .pipe(_aggregate_external_worker_counts, geography_type, "geography_id")
    #         )
    #         outputs.append(geo_df)

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("external_worker_count").cast(pl.Float64),
        )
        .sort(["geography_type", "geography_id"])
    )


def _empty_workplace_location_employment_comparison() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            "employment_count": pl.Float64,
            "worker_count": pl.Float64,
        }
    )


def _worker_filter_expr() -> pl.Expr:
    return (
        pl.col("is_worker")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "worker"])
    )


# TODO verify prepared land_use canonical column names
def workplace_vs_land_use_employment(rd: RunData, config: Config) -> pl.DataFrame:
    """
    Assumes rd.land_use contains:
      - MAZ
      - employment_count
    and rd.per contains:
      - workplace_zone_id
      - is_worker
      - finalweight
    """
    land_use_required = {"MAZ", "employment_count"}
    person_required = {"workplace_zone_id", "is_worker", "finalweight"}

    if not land_use_required.issubset(
        set(rd.land_use.columns)
    ) or not person_required.issubset(set(rd.per.columns)):
        return _empty_workplace_location_employment_comparison()

    land_use_maz = (
        rd.land_use.filter(
            pl.col("MAZ").is_not_null() & pl.col("employment_count").is_not_null()
        )
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

    outputs = [
        land_use_maz.join(
            worker_maz,
            on=["geography_type", "geography_id"],
            how="full",
            coalesce=True,
        )
    ]

    # TODO Update to match geographic aggregation API
    # Adapt to your repo's geography helper pattern.
    # Expected idea:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.workplace_maz_geography_lookups():
    #         # lookup_df maps MAZ -> geography_id
    #         lu_geo = (
    #             rd.land_use
    #             .filter(pl.col("MAZ").is_not_null() & pl.col("employment_count").is_not_null())
    #             .join(lookup_df, left_on="MAZ", right_on="MAZ", how="inner")
    #             .group_by("geography_id")
    #             .agg(employment_count=pl.col("employment_count").sum())
    #             .with_columns(
    #                 pl.lit(geography_type).alias("geography_type"),
    #                 pl.col("geography_id").cast(pl.Utf8),
    #                 pl.col("employment_count").cast(pl.Float64),
    #             )
    #         )
    #
    #         workers_geo = (
    #             rd.per
    #             .filter(_worker_filter_expr() & pl.col("workplace_zone_id").is_not_null())
    #             .join(lookup_df, left_on="workplace_zone_id", right_on="MAZ", how="inner")
    #             .group_by("geography_id")
    #             .agg(worker_count=pl.col("finalweight").sum())
    #             .with_columns(
    #                 pl.lit(geography_type).alias("geography_type"),
    #                 pl.col("geography_id").cast(pl.Utf8),
    #                 pl.col("worker_count").cast(pl.Float64),
    #             )
    #         )
    #
    #         outputs.append(
    #             lu_geo.join(
    #                 workers_geo,
    #                 on=["geography_type", "geography_id"],
    #                 how="full",
    #                 coalesce=True,
    #             )
    #         )

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("employment_count").fill_null(0.0).cast(pl.Float64),
            pl.col("worker_count").fill_null(0.0).cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "employment_count",
            "worker_count",
        )
        .sort(["geography_type", "geography_id"])
    )


def commuting_flows(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "origin_geography_type": pl.Utf8,
        "origin_geography_id": pl.Utf8,
        "destination_geography_type": pl.Utf8,
        "destination_geography_id": pl.Utf8,
        "commuter_count": pl.Float64,
    }

    required = {
        "home_zone_id",
        "workplace_zone_id",
        "is_worker",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return pl.DataFrame(schema=result_schema)

    def worker_filter_expr() -> pl.Expr:
        # Defensive because the uploaded schema shows is_worker as large_string.
        return (
            pl.col("is_worker")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes", "worker"])
        )

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
        worker_filter_expr()
        & pl.col("home_zone_id").is_not_null()
        & pl.col("workplace_zone_id").is_not_null()
    ).select("home_zone_id", "workplace_zone_id", "finalweight")

    if base.is_empty():
        return pl.DataFrame(schema=result_schema)

    outputs = [
        aggregate_flows(
            base,
            origin_type="maz",
            origin_col="home_zone_id",
            destination_type="maz",
            destination_col="workplace_zone_id",
        )
    ]

    # TODO: Update below with geography aggregation helper
    # The summary description calls for optional:
    #   - MAZ -> geography
    #   - geography -> MAZ
    #   - geography -> geography
    # flows, depending on configured lookup tables.

    # Example expected pattern:
    #
    # home_lookups = list(config.home_maz_geography_lookups()) if config.geography_enabled else []
    # workplace_lookups = list(config.workplace_maz_geography_lookups()) if config.geography_enabled else []
    #
    # for origin_type, home_lookup_df in home_lookups:
    #     # home_lookup_df maps MAZ -> geography_id
    #     geo_origin = (
    #         base.join(
    #             home_lookup_df,
    #             left_on="home_zone_id",
    #             right_on="MAZ",
    #             how="inner",
    #         )
    #     )
    #
    #     outputs.append(
    #         aggregate_flows(
    #             geo_origin,
    #             origin_type=origin_type,
    #             origin_col="geography_id",
    #             destination_type="maz",
    #             destination_col="workplace_zone_id",
    #         )
    #     )
    #
    # for destination_type, workplace_lookup_df in workplace_lookups:
    #     # workplace_lookup_df maps MAZ -> geography_id
    #     geo_dest = (
    #         base.join(
    #             workplace_lookup_df,
    #             left_on="workplace_zone_id",
    #             right_on="MAZ",
    #             how="inner",
    #         )
    #     )
    #
    #     outputs.append(
    #         aggregate_flows(
    #             geo_dest,
    #             origin_type="maz",
    #             origin_col="home_zone_id",
    #             destination_type=destination_type,
    #             destination_col="geography_id",
    #         )
    #     )
    #
    # for origin_type, home_lookup_df in home_lookups:
    #     for destination_type, workplace_lookup_df in workplace_lookups:
    #         geo_both = (
    #             base.join(
    #                 home_lookup_df.rename({"geography_id": "origin_geography_id"}),
    #                 left_on="home_zone_id",
    #                 right_on="MAZ",
    #                 how="inner",
    #             )
    #             .join(
    #                 workplace_lookup_df.rename({"geography_id": "destination_geography_id"}),
    #                 left_on="workplace_zone_id",
    #                 right_on="MAZ",
    #                 how="inner",
    #             )
    #         )
    #
    #         outputs.append(
    #             aggregate_flows(
    #                 geo_both,
    #                 origin_type=origin_type,
    #                 origin_col="origin_geography_id",
    #                 destination_type=destination_type,
    #                 destination_col="destination_geography_id",
    #             )
    #         )

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


def _empty_school_location_enrollment_comparison() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "geography_type": pl.Utf8,
            "geography_id": pl.Utf8,
            "student_type": pl.Utf8,
            "enrollment_count": pl.Float64,
            "student_count": pl.Float64,
        }
    )


def _student_filter_expr() -> pl.Expr:
    return (
        pl.col("is_student")
        .cast(pl.Utf8)
        .str.to_lowercase()
        .is_in(["true", "1", "yes", "student"])
    )


def school_loc_vs_land_use_enrollment(rd: RunData, config: Config) -> pl.DataFrame:
    """
    Assumes rd.land_use contains:
      - MAZ
      - enrollment_count
      - student_type
    and rd.per contains:
      - school_zone_id
      - is_student
      - finalweight
      - columns/config needed to derive student_type
    """
    land_use_required = {"MAZ", "enrollment_count", "student_type"}
    person_required = {"school_zone_id", "is_student", "finalweight"}

    if not land_use_required.issubset(
        set(rd.land_use.columns)
    ) or not person_required.issubset(set(rd.per.columns)):
        return _empty_school_location_enrollment_comparison()

    # TODO: replace with student-type mapping helper.
    # Examples:
    #   config.student_type_for_person_expr()
    #   config.classify_student_type_expr(rd.per)
    #   a CASE/when expression based on pstudent / school_segment / SCHG
    #
    # For now, assume a prepared `student_type` field already exists on persons,
    # or config can supply one.
    if "student_type" in rd.per.columns:
        student_type_expr = pl.col("student_type").cast(pl.Utf8)
    else:
        return _empty_school_location_enrollment_comparison()

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

    outputs = [
        land_use_maz.join(
            student_maz,
            on=["geography_type", "geography_id", "student_type"],
            how="full",
            coalesce=True,
        )
    ]

    # TODO Update to match geographic aggregation API
    # Expected idea:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.school_maz_geography_lookups():
    #         lu_geo = (
    #             rd.land_use
    #             .filter(
    #                 pl.col("MAZ").is_not_null()
    #                 & pl.col("student_type").is_not_null()
    #                 & pl.col("enrollment_count").is_not_null()
    #             )
    #             .join(lookup_df, on="MAZ", how="inner")
    #             .group_by(["geography_id", "student_type"])
    #             .agg(enrollment_count=pl.col("enrollment_count").sum())
    #             .with_columns(
    #                 pl.lit(geography_type).alias("geography_type"),
    #                 pl.col("geography_id").cast(pl.Utf8),
    #                 pl.col("student_type").cast(pl.Utf8),
    #                 pl.col("enrollment_count").cast(pl.Float64),
    #             )
    #         )
    #
    #         students_geo = (
    #             rd.per
    #             .filter(_student_filter_expr() & pl.col("school_zone_id").is_not_null())
    #             .with_columns(student_type=student_type_expr.alias("student_type"))
    #             .filter(pl.col("student_type").is_not_null())
    #             .join(lookup_df, left_on="school_zone_id", right_on="MAZ", how="inner")
    #             .group_by(["geography_id", "student_type"])
    #             .agg(student_count=pl.col("finalweight").sum())
    #             .with_columns(
    #                 pl.lit(geography_type).alias("geography_type"),
    #                 pl.col("geography_id").cast(pl.Utf8),
    #                 pl.col("student_type").cast(pl.Utf8),
    #                 pl.col("student_count").cast(pl.Float64),
    #             )
    #         )
    #
    #         outputs.append(
    #             lu_geo.join(
    #                 students_geo,
    #                 on=["geography_type", "geography_id", "student_type"],
    #                 how="full",
    #                 coalesce=True,
    #             )
    #         )

    return (
        pl.concat(outputs, how="vertical")
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
        result_schema = {
            "distance_bin": pl.Int32,
            "geography": pl.Utf8,
            "person_count": pl.Float64,
        }
        empty = pl.DataFrame(schema=result_schema)

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

    if ptype_col is not None:
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


def _prepare_vehicle_table(rd: RunData) -> pl.DataFrame:
    """
    Expects rd.vehicles with at least:
      - vehicle_type: encoded as {body}_{age}_{fuel}, e.g. Car_11_Gas
      - finalweight OR household weight already attached at vehicle level

    If your vehicle table does not already have finalweight, join household weights
    onto vehicles before calling these summaries, or adapt this helper accordingly.
    """
    required = {"vehicle_type", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return pl.DataFrame()
    if not required.issubset(set(rd.vehicles.columns)):
        return pl.DataFrame()

    return (
        rd.vehicles.filter(pl.col("vehicle_type").is_not_null())
        .with_columns(
            pl.col("vehicle_type").cast(pl.Utf8),
            pl.col("vehicle_type").str.split("_").list.get(0).alias("body_type"),
            pl.col("vehicle_type").str.split("_").list.get(1).alias("vehicle_age_raw"),
            pl.col("vehicle_type").str.split("_").list.get(2).alias("fuel_type"),
        )
        .with_columns(
            pl.col("body_type").cast(pl.Utf8),
            pl.col("fuel_type").cast(pl.Utf8),
            pl.col("vehicle_age_raw").cast(pl.Int64, strict=False),
        )
        .filter(
            pl.col("body_type").is_not_null()
            & pl.col("fuel_type").is_not_null()
            & pl.col("vehicle_age_raw").is_not_null()
        )
        .with_columns(
            pl.when(pl.col("vehicle_age_raw") >= 20)
            .then(pl.lit("20+"))
            .otherwise(pl.col("vehicle_age_raw").cast(pl.Utf8))
            .alias("age")
        )
    )


def vehicle_char_age(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "age": pl.Utf8,
        "vehicle_count": pl.Float64,
    }

    required = {"vehicle_age", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return pl.DataFrame(schema=result_schema)
    if not required.issubset(set(rd.vehicles.columns)):
        return pl.DataFrame(schema=result_schema)

    return (
        rd.vehicles.filter(pl.col("vehicle_age").is_not_null())
        .with_columns(
            pl.when(pl.col("vehicle_age") >= 20)
            .then(pl.lit("20+"))
            .otherwise(pl.col("vehicle_age").cast(pl.Utf8))
            .alias("age")
        )
        .group_by("age")
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("age").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
            pl.when(pl.col("age") == "20+")
            .then(999)
            .otherwise(pl.col("age").cast(pl.Int64, strict=False))
            .alias("_sort_age"),
        )
        .sort("_sort_age")
        .select("age", "vehicle_count")
    )


def vehicle_char_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "fuel_type": pl.Utf8,
        "vehicle_count": pl.Float64,
    }

    required = {"fuel_type", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return pl.DataFrame(schema=result_schema)
    if not required.issubset(set(rd.vehicles.columns)):
        return pl.DataFrame(schema=result_schema)

    return (
        rd.vehicles.filter(pl.col("fuel_type").is_not_null())
        .group_by("fuel_type")
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("fuel_type").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("fuel_type", "vehicle_count")
        .sort("fuel_type")
    )


def vehicle_char_body(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "body_type": pl.Utf8,
        "vehicle_count": pl.Float64,
    }

    required = {"body_type", "finalweight"}
    if not hasattr(rd, "vehicles"):
        return pl.DataFrame(schema=result_schema)
    if not required.issubset(set(rd.vehicles.columns)):
        return pl.DataFrame(schema=result_schema)

    return (
        rd.vehicles.filter(pl.col("body_type").is_not_null())
        .group_by("body_type")
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("body_type").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("body_type", "vehicle_count")
        .sort("body_type")
    )


def transit_pass(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "person_type": pl.Utf8,
        "transit_pass_ownership_status": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    }

    required = {"person_type", "transit_pass_ownership", "finalweight"}
    if not required.issubset(set(rd.per.columns)):
        return pl.DataFrame(schema=result_schema)

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

    by_person_type = base.group_by(
        ["person_type", "transit_pass_ownership_status"]
    ).agg(person_count=pl.col("finalweight").sum())

    all_person_types = (
        base.with_columns(pl.lit("all_person_types").alias("person_type"))
        .group_by(["person_type", "transit_pass_ownership_status"])
        .agg(person_count=pl.col("finalweight").sum())
    )

    return (
        pl.concat([by_person_type, all_person_types], how="vertical")
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("transit_pass_ownership_status").cast(pl.Utf8),
            pl.col("person_type")
            .map_elements(
                lambda x: (
                    "All Person Types"
                    if x == "all_person_types"
                    else config.person_type_label(x)
                ),
                return_dtype=pl.Utf8,
            )
            .alias("person_type_label"),
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


def transit_subsidy(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "person_type": pl.Utf8,
        "transit_subsidy_status": pl.Utf8,
        "person_type_label": pl.Utf8,
        "person_count": pl.Float64,
    }

    required = {
        "person_type",
        "transit_pass_subsidy",
        "is_worker",
        "is_student",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return pl.DataFrame(schema=result_schema)

    base = rd.per.filter(
        pl.col("person_type").is_not_null()
        & pl.col("transit_pass_subsidy").is_not_null()
        & (
            (
                pl.col("is_worker")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["true", "1", "yes", "worker"])
            )
            | (
                pl.col("is_student")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["true", "1", "yes", "student"])
            )
        )
    ).with_columns(
        pl.col("person_type").cast(pl.Utf8),
        pl.when(pl.col("transit_pass_subsidy") == 1)
        .then(pl.lit("has_transit_subsidy"))
        .otherwise(pl.lit("no_transit_subsidy"))
        .alias("transit_subsidy_status"),
    )

    by_person_type = base.group_by(["person_type", "transit_subsidy_status"]).agg(
        person_count=pl.col("finalweight").sum()
    )

    all_person_types = (
        base.with_columns(pl.lit("all_person_types").alias("person_type"))
        .group_by(["person_type", "transit_subsidy_status"])
        .agg(person_count=pl.col("finalweight").sum())
    )

    return (
        pl.concat([by_person_type, all_person_types], how="vertical")
        .with_columns(
            pl.col("person_type").cast(pl.Utf8),
            pl.col("transit_subsidy_status").cast(pl.Utf8),
            pl.col("person_type")
            .map_elements(
                lambda x: (
                    "All Person Types"
                    if x == "all_person_types"
                    else config.person_type_label(x)
                ),
                return_dtype=pl.Utf8,
            )
            .alias("person_type_label"),
            pl.col("person_count").cast(pl.Float64),
        )
        .select(
            "person_type",
            "transit_subsidy_status",
            "person_type_label",
            "person_count",
        )
        .sort(["person_type", "transit_subsidy_status"])
    )


def free_parking(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "workers_without_free_parking_count": pl.Float64,
        "workers_with_free_parking_count": pl.Float64,
    }

    required = {
        "is_worker",
        "free_parking_at_work",
        "workplace_zone_id",
        "finalweight",
    }
    if not required.issubset(set(rd.per.columns)):
        return pl.DataFrame(schema=result_schema)

    def worker_filter_expr() -> pl.Expr:
        # Defensive because prepared schemas can mix bool-like/string-like fields.
        return (
            pl.col("is_worker")
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["true", "1", "yes", "worker"])
        )

    def aggregate_counts(
        df: pl.DataFrame,
        geography_type: str,
        geography_id_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by(geography_id_col)
            .agg(
                workers_without_free_parking_count=pl.when(
                    ~pl.col("free_parking_at_work")
                )
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
        worker_filter_expr()
        & pl.col("workplace_zone_id").is_not_null()
        & pl.col("free_parking_at_work").is_not_null()
    ).select("workplace_zone_id", "free_parking_at_work", "finalweight")

    if base.is_empty():
        return pl.DataFrame(schema=result_schema)

    outputs = [
        aggregate_counts(
            base,
            geography_type="maz",
            geography_id_col="workplace_zone_id",
        )
    ]

    # TODO: Update with geography aggregation helper
    # Geography-aware summaries may also aggregate to configured
    # geographies when a MAZ-to-geography lookup is available.
    #
    # Example expected pattern:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.workplace_maz_geography_lookups():
    #         # lookup_df maps workplace_zone_id/MAZ -> geography_id
    #         geo_df = (
    #             base.join(
    #                 lookup_df,
    #                 left_on="workplace_zone_id",
    #                 right_on="MAZ",
    #                 how="inner",
    #             )
    #             .pipe(aggregate_counts, geography_type, "geography_id")
    #         )
    #         outputs.append(geo_df)

    return (
        pl.concat(outputs, how="vertical")
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


def telecommute(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """Telecommute frequency distribution. Columns: telecommute_frequency, person_count."""
    result_schema = {
        "telecommute_frequency": pl.Utf8,
        "person_count": pl.Float64,
    }
    if "telecommute_frequency" not in rd.per.columns:
        return pl.DataFrame(schema=result_schema)

    return (
        rd.per.filter(
            pl.col("telecommute_frequency").is_not_null()
            & (pl.col("telecommute_frequency") != "")
        )
        .group_by("telecommute_frequency")
        .agg(person_count=pl.col("finalweight").sum())
        .sort("telecommute_frequency")
    )
