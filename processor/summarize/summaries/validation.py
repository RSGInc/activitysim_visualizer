"""Validation summaries."""

import polars as pl
from runtime.config import Config
from processor.models import RunData
from processor.summarize.contracts import summary_contract


def traffic_count_comparison(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def screenline_flow_comparison(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def total_transit_boardings(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def transit_transfer_rate(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


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


def commercial_vehicle_vmt(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def bicycle_vmt_by_facility(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()
