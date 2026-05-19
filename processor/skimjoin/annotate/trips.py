from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.engine import annotate_lookup_table
from processor.skimjoin.config.schema import NormalizedConfig
from processor.skimjoin.skimstore.base import SkimStore


def annotate_trips(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None = None,
    include_fallback_report: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame] | tuple[
    pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame
]:
    return annotate_lookup_table(
        trips,
        source_table=None,
        rules=normalized.trip_lookups or normalized.lookups,
        normalized=normalized,
        inventory=inventory,
        mode_column=normalized.activitysim.mode_column,
        skim_store=skim_store,
        include_fallback_report=include_fallback_report,
        table_name="trips",
    )
