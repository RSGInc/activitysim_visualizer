from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.engine import annotate_lookup_table
from processor.skimjoin.config.normalize import TOUR_DIRECTION_COLUMN
from processor.skimjoin.config.schema import NormalizedConfig
from processor.skimjoin.skimstore.base import SkimStore


def annotate_tours(
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None = None,
    include_fallback_report: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame] | tuple[
    pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame
]:
    tours_with_ids = tours.with_row_index("_row_id")
    contexts = pl.concat(
        [
            _directional_tour_context(
                tours_with_ids,
                normalized,
                outbound=True,
            ),
            _directional_tour_context(
                tours_with_ids,
                normalized,
                outbound=False,
            ),
        ],
        how="vertical_relaxed",
    )
    return annotate_lookup_table(
        tours_with_ids,
        source_table=contexts,
        rules=normalized.tour_lookups,
        normalized=normalized,
        inventory=inventory,
        mode_column=normalized.activitysim.tour_mode_column,
        skim_store=skim_store,
        include_fallback_report=include_fallback_report,
        table_name="tours",
    )


def _directional_tour_context(
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    *,
    outbound: bool,
) -> pl.DataFrame:
    activitysim = normalized.activitysim
    origin_column = activitysim.tour_origin_column
    destination_column = activitysim.tour_destination_column
    context_origin = pl.col(origin_column) if outbound else pl.col(destination_column)
    context_destination = (
        pl.col(destination_column) if outbound else pl.col(origin_column)
    )
    return tours.with_columns(
        pl.col("_row_id").cast(pl.Int64),
        pl.col(activitysim.tour_id_column).cast(pl.Int64, strict=False).alias("trip_id"),
        pl.lit(outbound).alias(activitysim.outbound_column),
        pl.lit("outbound" if outbound else "inbound").alias(TOUR_DIRECTION_COLUMN),
        context_origin.cast(pl.Float64).alias("OTAZ"),
        context_destination.cast(pl.Float64).alias("DTAZ"),
        context_origin.cast(pl.Float64).alias("o_maz"),
        context_destination.cast(pl.Float64).alias("d_maz"),
    )


def aggregate_tours_from_trips(
    trips: pl.DataFrame,
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    raise RuntimeError(
        "aggregate_tours_from_trips is no longer supported; use annotate_tours instead."
    )
