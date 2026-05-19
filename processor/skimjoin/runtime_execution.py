"""Preflight and execution helpers for integrated skimjoin runtime."""

from __future__ import annotations

from collections import Counter
from typing import Callable

import polars as pl

from processor.models import RunData
from processor.skimjoin.annotate.tours import annotate_tours
from processor.skimjoin.annotate.trips import annotate_trips
from processor.skimjoin.inventory import inventory_skim_files
from processor.skimjoin.runtime_types import _RuntimeSkimjoinResult
from processor.skimjoin.skimstore.omx import OmxSkimStore


def _validate_runtime_inventory(inventory: pl.DataFrame) -> None:
    if inventory.is_empty():
        raise ValueError("Integrated skimjoin could not resolve any skim matrices.")

    source_kinds = {
        str(value) for value in inventory.get_column("source_kind").unique().to_list()
    }
    unsupported = sorted(
        source_kind
        for source_kind in source_kinds
        if source_kind not in {"od_matrix", "keyed_column", "od_table"}
    )
    if unsupported:
        raise ValueError(
            "Integrated skimjoin encountered unsupported skim source kinds: "
            + ", ".join(repr(value) for value in unsupported)
        )

    matrix_names = [
        str(value) for value in inventory.get_column("matrix_name").to_list()
    ]
    duplicates = sorted(
        matrix_name
        for matrix_name, count in Counter(matrix_names).items()
        if count > 1
    )
    if duplicates:
        raise ValueError(
            "Integrated skimjoin requires unique matrix names across skim inputs. "
            + "Duplicate names: "
            + ", ".join(repr(name) for name in duplicates)
        )


def _resolved_runtime_inventory(normalized: object) -> pl.DataFrame:
    inventory = inventory_skim_files(normalized.skim_files)
    _validate_runtime_inventory(inventory)
    return inventory


def _run_integrated_skimjoin(
    *,
    rd: RunData,
    normalized: object,
    annotate_trips_fn: Callable[..., tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]] = annotate_trips,
    annotate_tours_fn: Callable[..., tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]] = annotate_tours,
) -> _RuntimeSkimjoinResult:
    inventory = _resolved_runtime_inventory(normalized)
    trip_outputs = annotate_trips_fn(
        rd.trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        include_fallback_report=True,
    )
    annotated_trips, lookup_summary, missing_lookup_report, fallback_lookup_report = trip_outputs
    tour_outputs = annotate_tours_fn(
        rd.tours,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        include_fallback_report=True,
    )
    enriched_tours, tour_lookup_summary, tour_missing_lookup_report, tour_fallback_lookup_report = tour_outputs
    return _RuntimeSkimjoinResult(
        annotated_trips=annotated_trips,
        enriched_tours=enriched_tours,
        lookup_summary=pl.concat(
            [lookup_summary, tour_lookup_summary],
            how="vertical_relaxed",
        ),
        missing_lookup_report=pl.concat(
            [missing_lookup_report, tour_missing_lookup_report],
            how="vertical_relaxed",
        ),
        fallback_lookup_report=pl.concat(
            [fallback_lookup_report, tour_fallback_lookup_report],
            how="vertical_relaxed",
        ),
        tour_aggregation_summary=tour_lookup_summary,
    )
