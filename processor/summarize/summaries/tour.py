"""Tour summaries."""

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import _summary_purpose_column
from runtime.config import Config


@summary(
    id="tour_category_distribution",
    schema={"tour_category": pl.Utf8, "tour_count": pl.Float64},
    required_columns={"tours": ("tour_category", "finalweight")},
)
def tour_category(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_category", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return tour_category.empty()

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


@summary(
    id="tour_purpose_distribution",
    schema={"tour_purpose": pl.Utf8, "tour_count": pl.Float64},
    required_columns={"tours": ("tour_purpose", "finalweight")},
)
def tour_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_purpose", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return tour_purpose.empty()
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return tour_purpose.empty()

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
