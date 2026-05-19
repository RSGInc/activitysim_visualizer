"""Typed helpers for integrated skimjoin runtime execution."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class _RuntimeSkimjoinResult:
    """Successful integrated skimjoin execution payload."""

    annotated_trips: pl.DataFrame
    enriched_tours: pl.DataFrame
    lookup_summary: pl.DataFrame
    missing_lookup_report: pl.DataFrame
    tour_aggregation_summary: pl.DataFrame
