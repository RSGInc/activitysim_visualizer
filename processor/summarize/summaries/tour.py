"""Tour summaries."""

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.summary_helpers import _summary_purpose_column
from processor.summarize.summaries.tour_geography import (
    avg_mand_tour_distance,
    avg_non_mand_tour_distance,
    ext_non_mand_tour_loc,
    int_vs_ext_non_mand_tour_freq,
)
from processor.summarize.summaries.tour_profiles import (
    at_work_sub_tour_freq,
    atwork_subtour_frequency_distribution,
    stop_freq,
    tour_distance,
    tour_mode,
    tour_tod,
)
from processor.summarize.summaries.tour_vehicles import (
    allocated_vehicle_age,
    allocated_vehicle_body,
    allocated_vehicle_fuel,
)
from runtime.config import Config


@summary_contract(
    schema={"tour_category": pl.Utf8, "tour_count": pl.Float64},
    required_columns={"tours": ("tour_category", "finalweight")},
)
def tour_category(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_category", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(tour_category)

    return (
        rd.tours.filter(pl.col("tour_category").is_not_null())
        .group_by("tour_category")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("tour_category").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("tour_category", "tour_count")
        .sort("tour_category")
    )


@summary_contract(
    schema={"tour_purpose": pl.Utf8, "tour_count": pl.Float64},
    required_columns={"tours": ("tour_purpose", "finalweight")},
)
def tour_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_purpose", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(tour_purpose)
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_purpose)

    return (
        rd.tours.filter(pl.col(purpose_col).is_not_null())
        .group_by(purpose_col)
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("tour_purpose", "tour_count")
        .sort("tour_purpose")
    )
