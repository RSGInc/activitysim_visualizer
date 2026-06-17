"""No-op builders for externally supplied validation summary tables."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from runtime.config import Config


@summary_contract(
    schema={
        "id": pl.Int64,
        "From_Node": pl.Int64,
        "To_Node": pl.Int64,
        "FACTYPE": pl.Int64,
        "am_vol": pl.Float64,
        "md_vol": pl.Float64,
        "pm_vol": pl.Float64,
        "day_vol": pl.Float64,
    }
)
def link_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(link_summary)


@summary_contract(
    schema={
        "id": pl.Int64,
        "FACTYPE": pl.Int64,
        "am_vol": pl.Float64,
        "md_vol": pl.Float64,
        "pm_vol": pl.Float64,
        "day_vol": pl.Float64,
    }
)
def count_location_counts(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(count_location_counts)


@summary_contract(
    schema={
        "id": pl.Int64,
        "FACTYPE": pl.Int64,
        "am_vol": pl.Float64,
        "md_vol": pl.Float64,
        "pm_vol": pl.Float64,
        "day_vol": pl.Float64,
    }
)
def count_location_volumes(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(count_location_volumes)


@summary_contract(
    schema={
        "": pl.Utf8,
        "Albany": pl.Float64,
        "Corvallis": pl.Float64,
        "Lebanon": pl.Float64,
        "Philomath": pl.Float64,
        "Total": pl.Float64,
    }
)
def county_flows(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(county_flows)


@summary_contract(
    schema={
        "": pl.Utf8,
        "Benton": pl.Float64,
        "Linn": pl.Float64,
        "Marion": pl.Float64,
        "Total": pl.Float64,
    }
)
def county_flows_joja(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(county_flows_joja)


@summary_contract(
    schema={
        "tod": pl.Utf8,
        "car": pl.Float64,
        "mu": pl.Float64,
        "su": pl.Float64,
        "Total": pl.Float64,
    }
)
def commercial_vehicle_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(commercial_vehicle_summary)


@summary_contract(
    schema={
        "tod": pl.Utf8,
        "car": pl.Float64,
        "mu": pl.Float64,
        "su": pl.Float64,
        "Total": pl.Float64,
    }
)
def commercial_vehicle_vmt_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(commercial_vehicle_vmt_summary)


_EXTERNAL_PURPOSE_SCHEMA = {
    "tod": pl.Utf8,
    "hbcoll": pl.Float64,
    "hbo": pl.Float64,
    "hbr": pl.Float64,
    "hbs": pl.Float64,
    "hbsch": pl.Float64,
    "hbw": pl.Float64,
    "nhbnw": pl.Float64,
    "nhbw": pl.Float64,
    "truck": pl.Float64,
    "Total": pl.Float64,
}


@summary_contract(schema=_EXTERNAL_PURPOSE_SCHEMA)
def external_trip_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(external_trip_summary)


@summary_contract(schema=_EXTERNAL_PURPOSE_SCHEMA)
def external_vmt_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(external_vmt_summary)


@summary_contract(
    schema={
        "TOD": pl.Utf8,
        "SOV": pl.Float64,
        "HOV2": pl.Float64,
        "HOV3": pl.Float64,
        "Truck": pl.Float64,
        "Total": pl.Float64,
    }
)
def auto_vmt_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(auto_vmt_summary)


@summary_contract(
    schema={
        "District": pl.Utf8,
        "Workers": pl.Float64,
        "WFH": pl.Float64,
    }
)
def work_from_home_summary(rd: RunData, config: Config) -> pl.DataFrame:
    return empty_summary_frame(work_from_home_summary)
