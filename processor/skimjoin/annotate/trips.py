from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.engine import (
    annotate_lookup_table,
    lookup_output_values,
)
from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore


def annotate_trips(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None = None,
    include_fallback_report: bool = False,
    *,
    rules: list[NormalizedLookupRule] | None = None,
    collect_reports: bool = True,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame] | tuple[
    pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame
]:
    trips_with_ids = trips.with_row_index("_row_id")
    source_table = _trip_lookup_source(trips_with_ids, normalized)
    return annotate_lookup_table(
        trips_with_ids,
        source_table=source_table,
        rules=(
            rules
            if rules is not None
            else normalized.trip_lookups or normalized.lookups
        ),
        normalized=normalized,
        inventory=inventory,
        mode_column=normalized.activitysim.trip_mode_column,
        skim_store=skim_store,
        include_fallback_report=include_fallback_report,
        collect_reports=collect_reports,
        table_name="trips",
    )


def lookup_trip_output_values(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    *,
    rules: list[NormalizedLookupRule],
    skim_store: SkimStore | None = None,
) -> pl.DataFrame:
    trips_with_ids = trips.with_row_index("_row_id")
    return lookup_output_values(
        _trip_lookup_source(trips_with_ids, normalized),
        rules=rules,
        normalized=normalized,
        inventory=inventory,
        mode_column=normalized.activitysim.trip_mode_column,
        skim_store=skim_store,
    )


def _trip_lookup_source(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
) -> pl.DataFrame:
    activitysim = normalized.activitysim
    trip_id_column = activitysim.trip_id_column
    if trip_id_column == "trip_id":
        return trips
    return trips.with_columns(
        pl.col(trip_id_column).cast(pl.Int64, strict=False).alias("trip_id")
    )
