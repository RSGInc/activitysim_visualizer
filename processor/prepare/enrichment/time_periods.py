"""Prepared trip and tour time-period label derivation."""

from __future__ import annotations

import polars as pl

from processor.prepare.enrichment.types import _PrepareState
from processor.prepare.enrichment.zones import _record_prepare_metric
from processor.time_periods import load_network_los_period_mapping
from runtime.config import Config


def _mapping_frame(mapping: dict[str, str], output_column: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "__period_key": list(mapping.keys()),
            output_column: list(mapping.values()),
        },
        schema={"__period_key": pl.Utf8, output_column: pl.Utf8},
    )


def _derive_period_column(
    df: pl.DataFrame,
    *,
    source_column: str,
    output_column: str,
    mapping: dict[str, str],
) -> pl.DataFrame:
    if source_column not in df.columns:
        return df
    if df.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(output_column))
    period_lookup = _mapping_frame(mapping, output_column)
    return (
        df.drop(output_column) if output_column in df.columns else df
    ).with_columns(
        pl.col(source_column)
        .cast(pl.Int64, strict=False)
        .cast(pl.Utf8)
        .alias("__period_key")
    ).join(period_lookup, on="__period_key", how="left").drop("__period_key")


def _record_period_metric(
    state: _PrepareState,
    *,
    metric_id: str,
    df: pl.DataFrame,
    source_column: str,
    output_column: str,
) -> None:
    if source_column not in df.columns or output_column not in df.columns:
        _record_prepare_metric(
            state,
            metric_id,
            total=0,
            unresolved=0,
            details={
                "source_column": source_column,
                "output_column": output_column,
                "status": "source_column_missing",
            },
        )
        return
    total = df.height
    unresolved = df.filter(pl.col(output_column).is_null()).height
    _record_prepare_metric(
        state,
        metric_id,
        total=total,
        unresolved=unresolved,
        details={
            "source_column": source_column,
            "output_column": output_column,
            "status": "derived",
        },
    )


def _attach_first_inbound_trip_period(state: _PrepareState) -> None:
    required = {"tour_id", "outbound", "trip_period"}
    if "tour_id" not in state.tours.columns or not required.issubset(state.trips.columns):
        return

    sort_columns = ["tour_id"]
    if "trip_num" in state.trips.columns:
        sort_columns.append("trip_num")

    first_inbound = (
        state.trips.filter(
            pl.col("outbound").cast(pl.Utf8).str.to_lowercase().is_in(["false", "0"])
        )
        .sort(sort_columns)
        .group_by("tour_id", maintain_order=True)
        .agg(pl.col("trip_period").first().alias("first_inbound_trip_period"))
    )

    if "first_inbound_trip_period" in state.tours.columns:
        state.tours = state.tours.drop("first_inbound_trip_period")
    state.tours = state.tours.join(first_inbound, on="tour_id", how="left")
    total = state.tours.height
    unresolved = state.tours.filter(pl.col("first_inbound_trip_period").is_null()).height
    _record_prepare_metric(
        state,
        "time_periods.tours.first_inbound_trip_period",
        total=total,
        unresolved=unresolved,
        details={
            "source_column": "trips.trip_period",
            "output_column": "first_inbound_trip_period",
            "status": "derived",
        },
    )


def _derive_time_periods(state: _PrepareState, config: Config) -> _PrepareState:
    settings = config.prepare_time_periods
    if not settings.enabled or settings.network_los_file is None:
        return state

    mapping = load_network_los_period_mapping(settings.network_los_file)

    trip_source = settings.trip_period_number_column
    if trip_source in state.trips.columns:
        state.trips = _derive_period_column(
            state.trips,
            source_column=trip_source,
            output_column="trip_period",
            mapping=mapping,
        )
    _record_period_metric(
        state,
        metric_id="time_periods.trips.trip_period",
        df=state.trips,
        source_column=trip_source,
        output_column="trip_period",
    )

    start_source = settings.tour_start_period_number_column
    if start_source in state.tours.columns:
        state.tours = _derive_period_column(
            state.tours,
            source_column=start_source,
            output_column="start_period",
            mapping=mapping,
        )
    _record_period_metric(
        state,
        metric_id="time_periods.tours.start_period",
        df=state.tours,
        source_column=start_source,
        output_column="start_period",
    )

    end_source = settings.tour_end_period_number_column
    if end_source in state.tours.columns:
        state.tours = _derive_period_column(
            state.tours,
            source_column=end_source,
            output_column="end_period",
            mapping=mapping,
        )
    _record_period_metric(
        state,
        metric_id="time_periods.tours.end_period",
        df=state.tours,
        source_column=end_source,
        output_column="end_period",
    )

    _attach_first_inbound_trip_period(state)
    return state
