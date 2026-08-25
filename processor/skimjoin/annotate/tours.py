from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.engine import (
    annotate_lookup_table,
    lookup_output_values,
)
from processor.skimjoin.config.normalize import TOUR_DIRECTION_COLUMN
from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore


def annotate_tours(
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    trips: pl.DataFrame | None = None,
    skim_store: SkimStore | None = None,
    include_fallback_report: bool = False,
    *,
    rules: list[NormalizedLookupRule] | None = None,
    collect_reports: bool = True,
) -> (
    tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]
    | tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]
):
    tours_with_ids = tours.with_row_index("_row_id")
    contexts = pl.concat(
        [
            _directional_tour_context(
                tours_with_ids,
                normalized,
                trips=trips,
                outbound=True,
            ),
            _directional_tour_context(
                tours_with_ids,
                normalized,
                trips=trips,
                outbound=False,
            ),
        ],
        how="vertical_relaxed",
    )
    return annotate_lookup_table(
        tours_with_ids,
        source_table=contexts,
        rules=rules if rules is not None else normalized.tour_lookups,
        normalized=normalized,
        inventory=inventory,
        mode_column=normalized.activitysim.tour_mode_column,
        skim_store=skim_store,
        include_fallback_report=include_fallback_report,
        collect_reports=collect_reports,
        table_name="tours",
    )


def lookup_tour_output_values(
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    *,
    rules: list[NormalizedLookupRule],
    skim_store: SkimStore | None = None,
) -> pl.DataFrame:
    tours_with_ids = tours.with_row_index("_row_id")
    contexts = pl.concat(
        [
            _directional_tour_context(tours_with_ids, normalized, outbound=True),
            _directional_tour_context(tours_with_ids, normalized, outbound=False),
        ],
        how="vertical_relaxed",
    )
    return lookup_output_values(
        contexts,
        rules=rules,
        normalized=normalized,
        inventory=inventory,
        mode_column=normalized.activitysim.tour_mode_column,
        skim_store=skim_store,
    )


def _directional_tour_context(
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    trips: pl.DataFrame | None = None,
    *,
    outbound: bool,
) -> pl.DataFrame:
    activitysim = normalized.activitysim
    od_columns = _tour_od_columns(tours, normalized)
    context_origin = (
        pl.col(od_columns["origin"]) if outbound else pl.col(od_columns["destination"])
    )
    context_destination = (
        pl.col(od_columns["destination"]) if outbound else pl.col(od_columns["origin"])
    )
    maz_origin = pl.col(od_columns["o_maz"]) if outbound else pl.col(od_columns["d_maz"])
    maz_destination = (
        pl.col(od_columns["d_maz"]) if outbound else pl.col(od_columns["o_maz"])
    )
    depart_expr = _tour_departure_expr(tours)
    return tours.with_columns(
        pl.col("_row_id").cast(pl.Int64),
        pl.col(activitysim.tour_id_column)
        .cast(pl.Int64, strict=False)
        .alias("trip_id"),
        pl.lit(outbound).alias(activitysim.outbound_column),
        pl.lit("outbound" if outbound else "inbound").alias(TOUR_DIRECTION_COLUMN),
        depart_expr.alias("depart"),
        context_origin.cast(pl.Float64).alias("OTAZ"),
        context_destination.cast(pl.Float64).alias("DTAZ"),
        maz_origin.cast(pl.Float64).alias("o_maz"),
        maz_destination.cast(pl.Float64).alias("d_maz"),
    )


def _tour_od_columns(
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
) -> dict[str, str]:
    defaults = normalized.defaults
    return {
        "origin": _first_present_column(
            tours,
            defaults.origin,
            "OTAZ",
            "origin",
        ),
        "destination": _first_present_column(
            tours,
            defaults.destination,
            "DTAZ",
            "destination",
        ),
        "o_maz": _first_present_column(
            tours,
            "o_maz",
            defaults.origin,
            "OTAZ",
            "origin",
        ),
        "d_maz": _first_present_column(
            tours,
            "d_maz",
            defaults.destination,
            "DTAZ",
            "destination",
        ),
    }


def _first_present_column(
    tours: pl.DataFrame,
    *candidates: str,
) -> str:
    for column in candidates:
        if column in tours.columns:
            return column
    raise ValueError(
        "Tour skimjoin context requires one of the configured origin/destination "
        f"columns, but none were present. Tried: {', '.join(repr(column) for column in candidates)}"
    )


def _tour_departure_expr(tours: pl.DataFrame) -> pl.Expr:
    if "depart" in tours.columns:
        return pl.col("depart")
    if "start" in tours.columns:
        return pl.col("start")
    if "start_hour" in tours.columns:
        return pl.col("start_hour")
    return pl.lit(None, dtype=pl.Int64)


def _first_inbound_departures(
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
) -> dict[int, int | float | None] | None:
    activitysim = normalized.activitysim
    required = {activitysim.tour_id_column, activitysim.outbound_column, "depart"}
    if not required.issubset(trips.columns):
        return None
    trip_num_present = "trip_num" in trips.columns
    inbound = trips.filter(
        pl.col(activitysim.outbound_column).is_not_null()
        & ~pl.col(activitysim.outbound_column).cast(pl.Boolean, strict=False)
        & pl.col("depart").is_not_null()
    )
    if inbound.is_empty():
        return {}
    sort_columns = [activitysim.tour_id_column]
    if trip_num_present:
        sort_columns.append("trip_num")
    sort_columns.append("depart")
    first_inbound = (
        inbound.sort(sort_columns)
        .group_by(activitysim.tour_id_column)
        .agg(pl.col("depart").first().alias("first_inbound_depart"))
    )
    return {
        int(row[activitysim.tour_id_column]): row["first_inbound_depart"]
        for row in first_inbound.to_dicts()
        if row.get(activitysim.tour_id_column) is not None
    }


def aggregate_tours_from_trips(
    trips: pl.DataFrame,
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    raise RuntimeError(
        "aggregate_tours_from_trips is no longer supported; use annotate_tours instead."
    )
