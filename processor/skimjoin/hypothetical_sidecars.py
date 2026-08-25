"""Helpers for optional hypothetical skim sidecar generation."""

from __future__ import annotations

import polars as pl

from processor.skimjoin.annotate.tours import lookup_tour_output_values
from processor.skimjoin.annotate.trips import lookup_trip_output_values
from processor.skimjoin.config.schema import NormalizedConfig, NormalizedLookupRule
from processor.skimjoin.skimstore.base import SkimStore

TRIP_HYPOTHETICAL_SIDECAR_SCHEMA = {
    "trip_id": pl.Int64,
    "observed_mode": pl.Utf8,
    "hypothetical_mode": pl.Utf8,
    "component": pl.Utf8,
    "value": pl.Float64,
    "finalweight": pl.Float64,
}

TOUR_HYPOTHETICAL_SIDECAR_SCHEMA = {
    "tour_id": pl.Int64,
    "observed_mode": pl.Utf8,
    "hypothetical_mode": pl.Utf8,
    "direction": pl.Utf8,
    "component": pl.Utf8,
    "value": pl.Float64,
    "finalweight": pl.Float64,
}


def build_hypothetical_sidecars(
    *,
    trips: pl.DataFrame,
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build long-form hypothetical skim sidecars for trips and tours."""
    trip_sidecar = _build_trip_hypothetical_sidecar(
        trips=trips,
        normalized=normalized,
        inventory=inventory,
        skim_store=skim_store,
    )
    tour_sidecar = _build_tour_hypothetical_sidecar(
        tours=tours,
        normalized=normalized,
        inventory=inventory,
        skim_store=skim_store,
    )
    return trip_sidecar, tour_sidecar


def _build_trip_hypothetical_sidecar(
    *,
    trips: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None,
) -> pl.DataFrame:
    mode_column = normalized.activitysim.trip_mode_column
    trip_id_column = normalized.activitysim.trip_id_column
    if (
        trips.is_empty()
        or mode_column not in trips.columns
        or trip_id_column not in trips.columns
        or "finalweight" not in trips.columns
    ):
        return pl.DataFrame(schema=TRIP_HYPOTHETICAL_SIDECAR_SCHEMA)

    frames: list[pl.DataFrame] = []
    for mode in _lookup_modes(normalized.trip_lookups):
        mode_rules = _rules_for_mode(normalized.trip_lookups, mode)
        outputs = _outputs_for_mode(mode_rules, mode)
        if not outputs:
            continue
        hypothetical_input = trips.with_columns(
            pl.col(mode_column).cast(pl.Utf8).alias("__observed_mode"),
            pl.lit(mode).alias(mode_column),
        )
        output_values = lookup_trip_output_values(
            hypothetical_input,
            normalized,
            inventory,
            skim_store=skim_store,
            rules=mode_rules,
        )
        frames.append(
            _trip_sidecar_from_output_values(
                hypothetical_input,
                output_values,
                outputs=outputs,
                trip_id_column=trip_id_column,
                hypothetical_mode=mode,
            )
        )
    return _concat_frames(frames, TRIP_HYPOTHETICAL_SIDECAR_SCHEMA)


def _build_tour_hypothetical_sidecar(
    *,
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
    inventory: pl.DataFrame,
    skim_store: SkimStore | None,
) -> pl.DataFrame:
    mode_column = normalized.activitysim.tour_mode_column
    tour_id_column = normalized.activitysim.tour_id_column
    if (
        tours.is_empty()
        or mode_column not in tours.columns
        or tour_id_column not in tours.columns
        or "finalweight" not in tours.columns
    ):
        return pl.DataFrame(schema=TOUR_HYPOTHETICAL_SIDECAR_SCHEMA)

    frames: list[pl.DataFrame] = []
    for mode in _lookup_modes(normalized.tour_lookups):
        mode_rules = _rules_for_mode(normalized.tour_lookups, mode)
        outputs = _outputs_for_mode(mode_rules, mode)
        if not outputs:
            continue
        hypothetical_input = tours.with_columns(
            pl.col(mode_column).cast(pl.Utf8).alias("__observed_mode"),
            pl.lit(mode).alias(mode_column),
        )
        output_values = lookup_tour_output_values(
            hypothetical_input,
            normalized,
            inventory,
            skim_store=skim_store,
            rules=mode_rules,
        )
        frames.append(
            _tour_sidecar_from_output_values(
                hypothetical_input,
                output_values,
                outputs=outputs,
                tour_id_column=tour_id_column,
                hypothetical_mode=mode,
            )
        )
    return _concat_frames(frames, TOUR_HYPOTHETICAL_SIDECAR_SCHEMA)


def _lookup_modes(rules) -> list[str]:
    return sorted({str(rule.mode) for rule in rules})


def _outputs_for_mode(rules, mode: str) -> list[str]:
    return sorted({str(rule.output) for rule in rules if str(rule.mode) == str(mode)})


def _rules_for_mode(
    rules: list[NormalizedLookupRule],
    mode: str,
) -> list[NormalizedLookupRule]:
    return [rule for rule in rules if str(rule.mode) == str(mode)]


def _trip_sidecar_from_output_values(
    trips: pl.DataFrame,
    output_values: pl.DataFrame,
    *,
    outputs: list[str],
    trip_id_column: str,
    hypothetical_mode: str,
) -> pl.DataFrame:
    available_outputs = _available_outputs(output_values, outputs)
    if not available_outputs:
        return pl.DataFrame(schema=TRIP_HYPOTHETICAL_SIDECAR_SCHEMA)
    return (
        pl.DataFrame({"component": available_outputs})
        .join(
            trips.with_row_index("_row_id").select(
                "_row_id",
                pl.col(trip_id_column).cast(pl.Int64, strict=False).alias("trip_id"),
                pl.col("__observed_mode").cast(pl.Utf8).alias("observed_mode"),
                pl.col("finalweight").cast(pl.Float64),
            ),
            how="cross",
        )
        .join(
            output_values.rename({"output": "component"}),
            on=["_row_id", "component"],
            how="left",
        )
        .with_columns(
            pl.lit(hypothetical_mode).alias("hypothetical_mode"),
            pl.col("value").cast(pl.Float64, strict=False).fill_nan(None),
        )
        .select(
            "trip_id",
            "observed_mode",
            "hypothetical_mode",
            "component",
            "value",
            "finalweight",
        )
        .cast(TRIP_HYPOTHETICAL_SIDECAR_SCHEMA, strict=False)
    )


def _tour_sidecar_from_output_values(
    tours: pl.DataFrame,
    output_values: pl.DataFrame,
    *,
    outputs: list[str],
    tour_id_column: str,
    hypothetical_mode: str,
) -> pl.DataFrame:
    available_outputs = _available_outputs(output_values, outputs)
    if not available_outputs:
        return pl.DataFrame(schema=TOUR_HYPOTHETICAL_SIDECAR_SCHEMA)
    return (
        pl.DataFrame({"component": available_outputs})
        .join(
            tours.with_row_index("_row_id").select(
                "_row_id",
                pl.col(tour_id_column).cast(pl.Int64, strict=False).alias("tour_id"),
                pl.col("__observed_mode").cast(pl.Utf8).alias("observed_mode"),
                pl.col("finalweight").cast(pl.Float64),
            ),
            how="cross",
        )
        .join(
            output_values.rename({"output": "component"}),
            on=["_row_id", "component"],
            how="left",
        )
        .with_columns(
            pl.lit(hypothetical_mode).alias("hypothetical_mode"),
            pl.col("value").cast(pl.Float64, strict=False).fill_nan(None),
            pl.when(pl.col("component").str.ends_with("_outbound"))
            .then(pl.lit("outbound"))
            .when(pl.col("component").str.ends_with("_inbound"))
            .then(pl.lit("inbound"))
            .otherwise(None)
            .alias("direction"),
        )
        .select(
            "tour_id",
            "observed_mode",
            "hypothetical_mode",
            "direction",
            "component",
            "value",
            "finalweight",
        )
        .cast(TOUR_HYPOTHETICAL_SIDECAR_SCHEMA, strict=False)
    )


def _available_outputs(
    output_values: pl.DataFrame,
    configured_outputs: list[str],
) -> list[str]:
    if output_values.is_empty():
        return []
    present = set(output_values.get_column("output").to_list())
    return [output for output in configured_outputs if output in present]


def _concat_frames(
    frames: list[pl.DataFrame],
    schema: dict[str, pl.DataType],
) -> pl.DataFrame:
    populated = [frame for frame in frames if not frame.is_empty()]
    if not populated:
        return pl.DataFrame(schema=schema)
    return pl.concat(populated, how="vertical_relaxed").cast(schema, strict=False)
