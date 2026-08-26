from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.tours import _directional_tour_context
from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore


def plan_csv_od_demands(
    *,
    trips: pl.DataFrame,
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore,
) -> None:
    if skim_store.od_csv_demand_planned():
        return

    rules = [*normalized.trip_lookups, *normalized.tour_lookups]
    skim_store.plan_csv_tables(
        inventory,
        matrix_templates={rule.matrix for rule in rules},
    )
    if not skim_store.has_planned_od_csv_tables():
        return

    trip_od = _demand_frames(trips, normalized.trip_lookups)
    tour_od: list[pl.DataFrame] = []
    if normalized.tour_lookups:
        tours_with_ids = tours.with_row_index("_row_id")
        for outbound in (True, False):
            context = _directional_tour_context(
                tours_with_ids,
                normalized,
                outbound=outbound,
            )
            tour_od.extend(_demand_frames(context, normalized.tour_lookups))

    skim_store.set_complete_od_csv_demand(
        demand=_combine_demands(
            [*trip_od, *tour_od],
            {
                "__lookup_origin": pl.Float64,
                "__lookup_destination": pl.Float64,
            },
        ),
    )


def _demand_frames(
    source: pl.DataFrame,
    rules: list[NormalizedLookupRule],
) -> list[pl.DataFrame]:
    od_columns = {
        (rule.origin, rule.destination)
        for rule in rules
        if rule.lookup == "od"
        and rule.origin in source.columns
        and rule.destination in source.columns
    }
    return [
        source.select(
            pl.col(origin).cast(pl.Float64).alias("__lookup_origin"),
            pl.col(destination).cast(pl.Float64).alias("__lookup_destination"),
        )
        for origin, destination in od_columns
    ]


def _combine_demands(
    frames: list[pl.DataFrame],
    schema: dict[str, pl.DataType],
) -> pl.DataFrame:
    if not frames:
        return pl.DataFrame(schema=schema)
    columns = list(schema)
    return (
        pl.concat(frames, how="vertical_relaxed")
        .filter(pl.all_horizontal(pl.col(column).is_not_null() for column in columns))
        .unique()
        .cast(schema)
    )
