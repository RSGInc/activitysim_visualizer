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


def workplace_vs_land_use_employment(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def commuting_flows(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def school_loc_vs_land_use_enrollment(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


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


def vehicle_char_age(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def vehicle_char_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def vehicle_char_body(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def transit_pass(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def transit_subsidy(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def free_parking(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


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
