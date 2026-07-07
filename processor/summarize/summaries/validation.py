"""Validation summaries."""

from pathlib import Path

from activitysim_viz_logging import get_logger
import polars as pl
from runtime.config import Config
from processor.models import RunData
from processor.skimjoin.config.network_los import load_network_los_period_mapping
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.summary_helpers import (
    _configured_geography_dimensions,
)


LOGGER = get_logger("processor.summarize.validation")
ALL_GEOGRAPHIES = "all_geographies"
ALL_INCOME_SEGMENTS = "all_income_segments"
ALL_HOUSEHOLD_SIZES = "all_household_sizes"
ALL_AUTO_MODES = "All Auto"
DAILY_TIME_PERIOD = "Daily"


# TODO: Update with actual fields from Visum outputs/traffic count inputs
# TODO Maybe change to outer join
def traffic_count_comparisons(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "count_location_id": pl.Utf8,
        "direction": pl.Utf8,
        "count_period": pl.Utf8,
        "observed_volume": pl.Float64,
        "modeled_volume": pl.Float64,
    }

    if not hasattr(rd, "observed_traffic_counts") or not hasattr(
        rd, "visum_traffic_counts"
    ):
        return pl.DataFrame(schema=result_schema)

    observed_required = {
        "count_location_id",
        "direction",
        "count_period",
        "count",
    }
    modeled_required = {
        "count_location_id",
        "direction",
        "count_period",
        "count",
    }

    if not observed_required.issubset(
        set(rd.observed_traffic_counts.columns)
    ) or not modeled_required.issubset(set(rd.visum_traffic_counts.columns)):
        return pl.DataFrame(schema=result_schema)

    observed = (
        rd.observed_traffic_counts.filter(
            pl.col("count_location_id").is_not_null()
            & pl.col("direction").is_not_null()
            & pl.col("count_period").is_not_null()
            & pl.col("count").is_not_null()
        )
        .group_by(["count_location_id", "direction", "count_period"])
        .agg(observed_volume=pl.col("count").sum())
        .with_columns(
            pl.col("count_location_id").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("count_period").cast(pl.Utf8),
            pl.col("observed_volume").cast(pl.Float64),
        )
    )

    modeled = (
        rd.visum_traffic_counts.filter(
            pl.col("count_location_id").is_not_null()
            & pl.col("direction").is_not_null()
            & pl.col("count_period").is_not_null()
            & pl.col("count").is_not_null()
        )
        .group_by(["count_location_id", "direction", "count_period"])
        .agg(modeled_volume=pl.col("count").sum())
        .with_columns(
            pl.col("count_location_id").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("count_period").cast(pl.Utf8),
            pl.col("modeled_volume").cast(pl.Float64),
        )
    )

    return (
        observed.join(
            modeled,
            on=["count_location_id", "direction", "count_period"],
            how="inner",
        )
        .select(
            "count_location_id",
            "direction",
            "count_period",
            "observed_volume",
            "modeled_volume",
        )
        .sort(["count_location_id", "direction", "count_period"])
    )


# TODO update based on actual visum output shape; input shape
def screenline_flow_comparisons(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "screenline_id": pl.Utf8,
        "direction": pl.Utf8,
        "count_period": pl.Utf8,
        "observed_volume": pl.Float64,
        "modeled_volume": pl.Float64,
    }

    if not hasattr(rd, "observed_screenline_flows") or not hasattr(
        rd, "visum_screenline_flows"
    ):
        return pl.DataFrame(schema=result_schema)

    required = {"screenline_id", "direction", "count_period", "volume"}

    if not required.issubset(
        set(rd.observed_screenline_flows.columns)
    ) or not required.issubset(set(rd.visum_screenline_flows.columns)):
        return pl.DataFrame(schema=result_schema)

    observed = (
        rd.observed_screenline_flows.filter(
            pl.col("screenline_id").is_not_null()
            & pl.col("direction").is_not_null()
            & pl.col("count_period").is_not_null()
            & pl.col("volume").is_not_null()
        )
        .group_by(["screenline_id", "direction", "count_period"])
        .agg(observed_volume=pl.col("volume").sum())
        .with_columns(
            pl.col("screenline_id").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("count_period").cast(pl.Utf8),
            pl.col("observed_volume").cast(pl.Float64),
        )
    )

    modeled = (
        rd.visum_screenline_flows.filter(
            pl.col("screenline_id").is_not_null()
            & pl.col("direction").is_not_null()
            & pl.col("count_period").is_not_null()
            & pl.col("volume").is_not_null()
        )
        .group_by(["screenline_id", "direction", "count_period"])
        .agg(modeled_volume=pl.col("volume").sum())
        .with_columns(
            pl.col("screenline_id").cast(pl.Utf8),
            pl.col("direction").cast(pl.Utf8),
            pl.col("count_period").cast(pl.Utf8),
            pl.col("modeled_volume").cast(pl.Float64),
        )
    )

    return (
        observed.join(
            modeled,
            on=["screenline_id", "direction", "count_period"],
            how="inner",
        )
        .select(
            "screenline_id",
            "direction",
            "count_period",
            "observed_volume",
            "modeled_volume",
        )
        .sort(["screenline_id", "direction", "count_period"])
    )


# TODO: Rewrite once I know what the VISUM fields look like
def total_transit_boardings(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "operator": pl.Utf8,
        "technology": pl.Utf8,
        "boardings": pl.Float64,
    }

    if not hasattr(rd, "visum_transit_boardings"):
        return pl.DataFrame(schema=result_schema)

    df = rd.visum_transit_boardings

    # Plausible alternative field names until the actual VISUM export shape is known.
    operator_candidates = [
        "operator",
        "operator_name",
        "transit_operator",
        "line_operator",
    ]
    technology_candidates = [
        "technology",
        "mode",
        "transit_mode",
        "system",
    ]
    boardings_candidates = [
        "boardings",
        "boarding_count",
        "volume",
        "passenger_volume",
        "transit_boardings",
    ]

    def _first_existing(columns: list[str], candidates: list[str]) -> str | None:
        for c in candidates:
            if c in columns:
                return c
        return None

    operator_col = _first_existing(df.columns, operator_candidates)
    technology_col = _first_existing(df.columns, technology_candidates)
    boardings_col = _first_existing(df.columns, boardings_candidates)

    if operator_col is None or technology_col is None or boardings_col is None:
        return pl.DataFrame(schema=result_schema)

    return (
        df.filter(
            pl.col(operator_col).is_not_null()
            & pl.col(technology_col).is_not_null()
            & pl.col(boardings_col).is_not_null()
        )
        .group_by([operator_col, technology_col])
        .agg(boardings=pl.col(boardings_col).sum())
        .rename(
            {
                operator_col: "operator",
                technology_col: "technology",
            }
        )
        .with_columns(
            pl.col("operator").cast(pl.Utf8),
            pl.col("technology").cast(pl.Utf8),
            pl.col("boardings").cast(pl.Float64),
        )
        .select("operator", "technology", "boardings")
        .sort(["operator", "technology"])
    )


# TODO: Update once we know the shape of the Visum transit output
def transit_transfer_rate(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "operator": pl.Utf8,
        "technology": pl.Utf8,
        "access_mode": pl.Utf8,
        "transfer_rate": pl.Float64,
    }

    if not hasattr(rd, "visum_transit_assignment"):
        return pl.DataFrame(schema=result_schema)

    df = rd.visum_transit_assignment

    operator_candidates = [
        "operator",
        "operator_name",
        "transit_operator",
        "line_operator",
    ]
    technology_candidates = [
        "technology",
        "mode",
        "transit_mode",
        "system",
    ]
    access_mode_candidates = [
        "access_mode",
        "accessmode",
        "trip_access_mode",
        "first_mode",
        "boarding_access_mode",
    ]
    boardings_candidates = [
        "assigned_boardings",
        "boardings",
        "transit_boardings",
        "boarding_count",
        "passenger_boardings",
    ]
    linked_trips_candidates = [
        "linked_trips",
        "linked_trip_count",
        "transit_linked_trips",
        "passenger_trips",
        "trips",
    ]

    def _first_existing(columns: list[str], candidates: list[str]) -> str | None:
        for c in candidates:
            if c in columns:
                return c
        return None

    operator_col = _first_existing(df.columns, operator_candidates)
    technology_col = _first_existing(df.columns, technology_candidates)
    access_mode_col = _first_existing(df.columns, access_mode_candidates)
    boardings_col = _first_existing(df.columns, boardings_candidates)
    linked_trips_col = _first_existing(df.columns, linked_trips_candidates)

    if (
        operator_col is None
        or technology_col is None
        or access_mode_col is None
        or boardings_col is None
        or linked_trips_col is None
    ):
        return pl.DataFrame(schema=result_schema)

    aggregated = (
        df.filter(
            pl.col(operator_col).is_not_null()
            & pl.col(technology_col).is_not_null()
            & pl.col(access_mode_col).is_not_null()
        )
        .group_by([operator_col, technology_col, access_mode_col])
        .agg(
            assigned_boardings=pl.col(boardings_col).sum(),
            linked_trips=pl.col(linked_trips_col).sum(),
        )
        .rename(
            {
                operator_col: "operator",
                technology_col: "technology",
                access_mode_col: "access_mode",
            }
        )
    )

    return (
        aggregated.with_columns(
            pl.when(pl.col("linked_trips") > 0)
            .then(pl.col("assigned_boardings") / pl.col("linked_trips"))
            .otherwise(None)
            .alias("transfer_rate")
        )
        .with_columns(
            pl.col("operator").cast(pl.Utf8),
            pl.col("technology").cast(pl.Utf8),
            pl.col("access_mode").cast(pl.Utf8),
            pl.col("transfer_rate").cast(pl.Float64),
        )
        .select("operator", "technology", "access_mode", "transfer_rate")
        .sort(["operator", "technology", "access_mode"])
    )


@summary_contract(
    schema={
        "auto_vmt": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "od_dist", "finalweight")},
)
def auto_vmt_totals(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns single-row DataFrame with column: auto_vmt."""
    trips_df = rd.trips

    if (
        "trip_mode" not in trips_df.columns
        or "od_dist" not in trips_df.columns
        or "finalweight" not in trips_df.columns
    ):
        return pl.DataFrame([{"auto_vmt": 0.0}], schema={"auto_vmt": pl.Float64})

    auto_modes: list[str] | None = None
    if config is not None and config.mode_groups and "Auto" in config.mode_groups:
        auto_modes = config.mode_groups["Auto"]

    if auto_modes is not None:
        auto_filter = pl.col("trip_mode").cast(pl.Utf8).is_in(auto_modes)
    else:
        auto_filter = (
            pl.col("trip_mode")
            .cast(pl.Utf8)
            .str.to_uppercase()
            .str.contains("DRIVE|SHARED|SOV|HOV|AUTO")
        )

    auto_trips = trips_df.filter(auto_filter)

    occupancy_expr = (
        pl.col("num_participants").fill_null(1).clip(lower_bound=1)
        if "num_participants" in auto_trips.columns
        else pl.lit(1)
    )

    auto_vmt = auto_trips.with_columns(
        (pl.col("od_dist") * pl.col("finalweight") / occupancy_expr).alias("auto_vmt_w")
    )["auto_vmt_w"].sum()

    return pl.DataFrame(
        [{"auto_vmt": float(auto_vmt) if auto_vmt else 0.0}],
        schema={"auto_vmt": pl.Float64},
    )


def _auto_mode_filter(config: Config | None) -> pl.Expr:
    auto_modes: list[str] | None = None
    if config is not None and config.mode_groups and "Auto" in config.mode_groups:
        auto_modes = config.mode_groups["Auto"]

    if auto_modes is not None:
        return pl.col("trip_mode").cast(pl.Utf8).is_in(auto_modes)
    return (
        pl.col("trip_mode")
        .cast(pl.Utf8)
        .str.to_uppercase()
        .str.contains("DRIVE|SHARED|SOV|HOV|AUTO|TAXI|TNC")
    )


def _resolved_network_los_file(rd: RunData, config: Config | None) -> str | None:
    value = rd.skimjoin_manifest.get("skimjoin_resolved_network_los_file")
    if value:
        return str(value)
    if config is not None and config.skimjoin.resolved_network_los_file:
        return config.skimjoin.resolved_network_los_file
    return None


def _network_los_period_mapping(
    rd: RunData,
    config: Config | None,
) -> dict[str, str] | None:
    path = _resolved_network_los_file(rd, config)
    if not path:
        return None
    if not Path(path).exists():
        LOGGER.warning(
            "[vmt_by_segment] Run %r network_los_file is unavailable; using Daily time period: %s",
            rd.label,
            path,
        )
        return None
    try:
        return load_network_los_period_mapping(path)
    except Exception as exc:
        LOGGER.warning(
            "[vmt_by_segment] Run %r network_los_file could not be read; using Daily time period: %s",
            rd.label,
            exc,
        )
        return None


def _distance_base(
    rd: RunData,
    config: Config | None,
) -> tuple[pl.DataFrame, str] | None:
    trips = rd.trips
    if "finalweight" not in trips.columns:
        return None

    if (
        "skim_auto_distance" in trips.columns
        and trips["skim_auto_distance"].is_not_null().any()
    ):
        LOGGER.info(
            "[vmt_by_segment] Run %r using distance_source=skim_auto_distance",
            rd.label,
        )
        return (
            trips.filter(pl.col("skim_auto_distance").is_not_null()).with_columns(
                pl.col("skim_auto_distance").cast(pl.Float64).alias("_vmt_distance")
            ),
            "skim_auto_distance",
        )

    if "od_dist" not in trips.columns or "trip_mode" not in trips.columns:
        LOGGER.warning(
            "[vmt_by_segment] Run %r has no usable auto distance source.",
            rd.label,
        )
        return None

    LOGGER.info(
        "[vmt_by_segment] Run %r using distance_source=od_dist",
        rd.label,
    )
    return (
        trips.filter(_auto_mode_filter(config) & pl.col("od_dist").is_not_null())
        .with_columns(pl.col("od_dist").cast(pl.Float64).alias("_vmt_distance")),
        "od_dist",
    )


def _with_time_period(
    df: pl.DataFrame,
    rd: RunData,
    config: Config | None,
) -> tuple[pl.DataFrame, str]:
    if "trip_period" in df.columns and df["trip_period"].is_not_null().any():
        LOGGER.info(
            "[vmt_by_segment] Run %r using time_period_source=trip_period",
            rd.label,
        )
        return (
            df.with_columns(
                pl.col("trip_period")
                .cast(pl.Utf8)
                .fill_null(DAILY_TIME_PERIOD)
                .alias("time_period")
            ),
            "trip_period",
        )

    period_mapping = _network_los_period_mapping(rd, config)
    if period_mapping and "depart_hour" in df.columns:
        LOGGER.info(
            "[vmt_by_segment] Run %r using time_period_source=network_los",
            rd.label,
        )
        return (
            df.with_columns(
                pl.col("depart_hour")
                .cast(pl.Int64, strict=False)
                .cast(pl.Utf8)
                .map_elements(
                    lambda value: period_mapping.get(value),
                    return_dtype=pl.Utf8,
                )
                .fill_null(DAILY_TIME_PERIOD)
                .alias("time_period")
            ),
            "network_los",
        )

    LOGGER.info(
        "[vmt_by_segment] Run %r using time_period_source=daily",
        rd.label,
    )
    return df.with_columns(pl.lit(DAILY_TIME_PERIOD).alias("time_period")), "daily"


def _household_join_columns(hh: pl.DataFrame) -> list[str]:
    candidates = [
        "household_id",
        "income_segment",
        "HHSIZE",
        "hhsize",
        "home_taz",
        "home_county",
        "home_mpo",
        *sorted(column for column in hh.columns if column.startswith("home_geo__")),
    ]
    return list(dict.fromkeys(column for column in candidates if column in hh.columns))


def _aggregate_vmt_for_geography(
    df: pl.DataFrame,
    *,
    geography_type: str,
    geography_col: str | None,
    distance_source: str,
    time_period_source: str,
) -> pl.DataFrame:
    working = df
    if geography_col is None:
        working = working.with_columns(
            pl.lit(ALL_GEOGRAPHIES).alias("_geography_id")
        )
    else:
        working = working.filter(pl.col(geography_col).is_not_null()).with_columns(
            pl.col(geography_col).cast(pl.Utf8).alias("_geography_id")
        )

    if working.is_empty():
        return empty_summary_frame(auto_vmt_by_home_geography_income_hhsize_time_period)

    aggregated = (
        working.group_by(
            ["_geography_id", "income_segment", "household_size", "time_period", "mode"]
        )
        .agg(
            pl.col("auto_vmt").sum().alias("auto_vmt"),
            pl.col("finalweight").sum().alias("trip_count"),
        )
        .with_columns(
            pl.lit(geography_type).alias("geography_type"),
            pl.col("_geography_id").alias("geography_id"),
            pl.lit(distance_source).alias("distance_source"),
            pl.lit(time_period_source).alias("time_period_source"),
        )
        .select(
            "geography_type",
            "geography_id",
            "income_segment",
            "household_size",
            "time_period",
            "mode",
            "auto_vmt",
            "trip_count",
            "distance_source",
            "time_period_source",
        )
    )
    return _with_derived_daily_vmt_rows(aggregated)


def _with_derived_daily_vmt_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Add a Daily total for segment groups that have time-period rows."""
    if df.is_empty() or "time_period" not in df.columns:
        return df

    group_cols = [
        "geography_type",
        "geography_id",
        "income_segment",
        "household_size",
        "mode",
        "distance_source",
        "time_period_source",
    ]
    if not set(group_cols).issubset(df.columns):
        return df

    non_daily = df.filter(pl.col("time_period") != DAILY_TIME_PERIOD)
    if non_daily.is_empty():
        return df

    groups_with_period_rows = non_daily.select(group_cols).unique()
    daily_only_rows = (
        df.filter(pl.col("time_period") == DAILY_TIME_PERIOD)
        .join(groups_with_period_rows, on=group_cols, how="anti")
    )
    derived_daily_rows = (
        df.join(groups_with_period_rows, on=group_cols, how="inner")
        .group_by(group_cols)
        .agg(
            pl.col("auto_vmt").sum().alias("auto_vmt"),
            pl.col("trip_count").sum().alias("trip_count"),
        )
        .with_columns(pl.lit(DAILY_TIME_PERIOD).alias("time_period"))
        .select(df.columns)
    )

    return pl.concat(
        [non_daily, daily_only_rows, derived_daily_rows],
        how="vertical",
    ).select(df.columns)


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "income_segment": pl.Utf8,
        "household_size": pl.Utf8,
        "time_period": pl.Utf8,
        "mode": pl.Utf8,
        "auto_vmt": pl.Float64,
        "trip_count": pl.Float64,
        "distance_source": pl.Utf8,
        "time_period_source": pl.Utf8,
    },
    required_columns={"trips": ("finalweight",)},
)
def auto_vmt_by_home_geography_income_hhsize_time_period(
    rd: RunData,
    config: Config,
) -> pl.DataFrame:
    distance_selection = _distance_base(rd, config)
    if distance_selection is None:
        return empty_summary_frame(auto_vmt_by_home_geography_income_hhsize_time_period)

    base, distance_source = distance_selection
    base, time_period_source = _with_time_period(base, rd, config)

    if "household_id" in base.columns and not rd.hh.is_empty():
        household_columns = _household_join_columns(rd.hh)
        if "household_id" in household_columns:
            household_preferred_columns = [
                column
                for column in household_columns
                if column not in {"household_id", "income_segment"}
            ]
            base = base.drop(household_preferred_columns, strict=False)
            base = base.join(
                rd.hh.select(household_columns).rename(
                    {"income_segment": "income_segment_hh"}
                    if "income_segment" in household_columns
                    else {}
                ),
                on="household_id",
                how="left",
            )

    income_exprs: list[pl.Expr] = []
    if "income_segment" in base.columns and "income_segment_hh" in base.columns:
        income_exprs.append(
            pl.coalesce(
                [pl.col("income_segment"), pl.col("income_segment_hh")]
            ).alias("_income_segment")
        )
    elif "income_segment" in base.columns:
        income_exprs.append(pl.col("income_segment").alias("_income_segment"))
    elif "income_segment_hh" in base.columns:
        income_exprs.append(pl.col("income_segment_hh").alias("_income_segment"))
    else:
        income_exprs.append(pl.lit(ALL_INCOME_SEGMENTS).alias("_income_segment"))

    household_size_expr = (
        pl.col("HHSIZE")
        if "HHSIZE" in base.columns
        else pl.col("hhsize")
        if "hhsize" in base.columns
        else pl.lit(ALL_HOUSEHOLD_SIZES)
    )
    occupancy_expr = (
        pl.col("num_participants").fill_null(1).clip(lower_bound=1)
        if "num_participants" in base.columns
        else pl.lit(1)
    )

    base = (
        base.with_columns(*income_exprs)
        .with_columns(
            pl.col("_income_segment")
            .cast(pl.Utf8)
            .fill_null(ALL_INCOME_SEGMENTS)
            .alias("income_segment"),
            household_size_expr.cast(pl.Utf8)
            .fill_null(ALL_HOUSEHOLD_SIZES)
            .alias("household_size"),
            (
                pl.col("trip_mode").cast(pl.Utf8).fill_null(ALL_AUTO_MODES)
                if "trip_mode" in base.columns
                else pl.lit(ALL_AUTO_MODES)
            ).alias("mode"),
            (
                pl.col("_vmt_distance")
                * pl.col("finalweight").cast(pl.Float64)
                / occupancy_expr
            ).alias("auto_vmt"),
        )
        .filter(pl.col("auto_vmt").is_not_null())
    )

    geography_dimensions: list[tuple[str, str | None]] = [
        (ALL_GEOGRAPHIES, None),
        *_configured_geography_dimensions(
            base,
            config=config,
            base_type="home_taz",
            base_col="home_taz",
            role_prefix="home",
        ),
    ]
    LOGGER.info(
        "[vmt_by_segment] Run %r home geography dimensions: %s",
        rd.label,
        ", ".join(geography_type for geography_type, _ in geography_dimensions),
    )
    if len(geography_dimensions) == 1:
        LOGGER.info(
            "[vmt_by_segment] Run %r using all_geographies only.",
            rd.label,
        )

    outputs = [
        _aggregate_vmt_for_geography(
            base,
            geography_type=geography_type,
            geography_col=geography_col,
            distance_source=distance_source,
            time_period_source=time_period_source,
        )
        for geography_type, geography_col in geography_dimensions
    ]
    outputs = [output for output in outputs if not output.is_empty()]
    if not outputs:
        return empty_summary_frame(auto_vmt_by_home_geography_income_hhsize_time_period)

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("income_segment").cast(pl.Utf8),
            pl.col("household_size").cast(pl.Utf8),
            pl.col("time_period").cast(pl.Utf8),
            pl.col("mode").cast(pl.Utf8),
            pl.col("auto_vmt").cast(pl.Float64),
            pl.col("trip_count").cast(pl.Float64),
            pl.col("distance_source").cast(pl.Utf8),
            pl.col("time_period_source").cast(pl.Utf8),
        )
        .sort(
            [
                "geography_type",
                "geography_id",
                "income_segment",
                "household_size",
                "mode",
                "time_period",
            ]
        )
    )


# TODO: Update once I know the shape of the Commercial VMT model output
def commercial_vehicle_vmt(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "commercial_vehicle_type": pl.Utf8,
        "external_vmt": pl.Float64,
        "internal_vmt": pl.Float64,
    }

    if not hasattr(rd, "commercial_vehicle_trips"):
        return pl.DataFrame(schema=result_schema)

    df = rd.commercial_vehicle_trips

    vehicle_type_candidates = [
        "commercial_vehicle_type",
        "vehicle_type",
        "truck_type",
        "mode",
        "veh_type",
    ]
    internal_external_candidates = [
        "trip_class",
        "internal_external",
        "trip_type",
        "externality",
    ]
    is_external_candidates = [
        "is_external",
        "external_trip",
        "is_external_trip",
    ]
    vmt_candidates = [
        "vmt",
        "trip_vmt",
        "distance",
        "trip_distance",
        "miles",
    ]

    def _first_existing(columns: list[str], candidates: list[str]) -> str | None:
        for c in candidates:
            if c in columns:
                return c
        return None

    vehicle_type_col = _first_existing(df.columns, vehicle_type_candidates)
    class_col = _first_existing(df.columns, internal_external_candidates)
    is_external_col = _first_existing(df.columns, is_external_candidates)
    vmt_col = _first_existing(df.columns, vmt_candidates)

    if vehicle_type_col is None or vmt_col is None:
        return pl.DataFrame(schema=result_schema)

    # Build a canonical boolean external flag.
    if is_external_col is not None:
        normalized = df.with_columns(
            pl.col(vehicle_type_col).cast(pl.Utf8).alias("commercial_vehicle_type"),
            pl.col(vmt_col).cast(pl.Float64).alias("vmt"),
            pl.col(is_external_col).cast(pl.Boolean).alias("is_external"),
        )
    elif class_col is not None:
        normalized = df.with_columns(
            pl.col(vehicle_type_col).cast(pl.Utf8).alias("commercial_vehicle_type"),
            pl.col(vmt_col).cast(pl.Float64).alias("vmt"),
            pl.col(class_col)
            .cast(pl.Utf8)
            .str.to_lowercase()
            .is_in(["external", "ext", "ie_external", "ee", "external_trip"])
            .alias("is_external"),
        )
    else:
        return pl.DataFrame(schema=result_schema)

    return (
        normalized.filter(
            pl.col("commercial_vehicle_type").is_not_null()
            & pl.col("vmt").is_not_null()
            & pl.col("is_external").is_not_null()
        )
        .group_by("commercial_vehicle_type")
        .agg(
            external_vmt=pl.when(pl.col("is_external"))
            .then(pl.col("vmt"))
            .otherwise(0.0)
            .sum(),
            internal_vmt=pl.when(~pl.col("is_external"))
            .then(pl.col("vmt"))
            .otherwise(0.0)
            .sum(),
        )
        .with_columns(
            pl.col("commercial_vehicle_type").cast(pl.Utf8),
            pl.col("external_vmt").cast(pl.Float64),
            pl.col("internal_vmt").cast(pl.Float64),
        )
        .select("commercial_vehicle_type", "external_vmt", "internal_vmt")
        .sort("commercial_vehicle_type")
    )


# TODO: Update once I know the shape of the Bicycle output
def bicycle_vmt_by_facility(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "facility_type": pl.Utf8,
        "bicycle_vmt": pl.Float64,
    }

    if not hasattr(rd, "bicycle_assignment_links"):
        return pl.DataFrame(schema=result_schema)

    df = rd.bicycle_assignment_links

    facility_type_candidates = [
        "facility_type",
        "bike_facility_type",
        "bicycle_facility_type",
        "facility",
        "bike_facility",
        "link_facility_type",
    ]
    vmt_candidates = [
        "bicycle_vmt",
        "bike_vmt",
        "vmt",
    ]
    trips_candidates = [
        "assigned_bicycle_trips",
        "assigned_bike_trips",
        "bike_trips",
        "bicycle_volume",
        "bike_volume",
        "volume",
    ]
    distance_candidates = [
        "link_distance",
        "distance",
        "length",
        "link_length",
        "miles",
    ]

    def _first_existing(columns: list[str], candidates: list[str]) -> str | None:
        for c in candidates:
            if c in columns:
                return c
        return None

    facility_type_col = _first_existing(df.columns, facility_type_candidates)
    vmt_col = _first_existing(df.columns, vmt_candidates)
    trips_col = _first_existing(df.columns, trips_candidates)
    distance_col = _first_existing(df.columns, distance_candidates)

    if facility_type_col is None:
        return pl.DataFrame(schema=result_schema)

    if vmt_col is not None:
        normalized = df.with_columns(
            pl.col(facility_type_col).cast(pl.Utf8).alias("facility_type"),
            pl.col(vmt_col).cast(pl.Float64).alias("bicycle_vmt"),
        )
    elif trips_col is not None and distance_col is not None:
        normalized = df.with_columns(
            pl.col(facility_type_col).cast(pl.Utf8).alias("facility_type"),
            (
                pl.col(trips_col).cast(pl.Float64)
                * pl.col(distance_col).cast(pl.Float64)
            ).alias("bicycle_vmt"),
        )
    else:
        return pl.DataFrame(schema=result_schema)

    return (
        normalized.filter(
            pl.col("facility_type").is_not_null() & pl.col("bicycle_vmt").is_not_null()
        )
        .group_by("facility_type")
        .agg(bicycle_vmt=pl.col("bicycle_vmt").sum())
        .with_columns(
            pl.col("facility_type").cast(pl.Utf8),
            pl.col("bicycle_vmt").cast(pl.Float64),
        )
        .select("facility_type", "bicycle_vmt")
        .sort("facility_type")
    )
