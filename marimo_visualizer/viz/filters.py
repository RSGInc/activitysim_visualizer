"""Deterministic option builders for marimo page controls."""

from __future__ import annotations

from typing import Iterable, Sequence

import polars as pl

from .models import Config, RunData


def _collect_values(dfs: Iterable[pl.DataFrame], column: str) -> list[str]:
    values: set[str] = set()
    for df in dfs:
        if column in df.columns and len(df) > 0:
            values.update(str(value) for value in df[column].drop_nulls().to_list())
    return sorted(values)


def _run_tables(runs: Sequence[tuple[str, RunData]], attr: str) -> list[pl.DataFrame]:
    return [getattr(run_data, attr) for _, run_data in runs]


def purpose_options_from_tours(
    runs: Sequence[tuple[str, RunData]],
    include_total: bool = True,
    include_all_nm: bool = False,
    include_joint_prefix: bool = False,
) -> list[str]:
    """Collect purpose options from tour tables across all runs."""
    values = _collect_values(_run_tables(runs, "tours"), "primary_purpose")
    if not include_joint_prefix:
        values = [value for value in values if not value.startswith("joint_")]
    if include_all_nm:
        values = ["All NM"] + values
    if include_total:
        values = ["Total"] + [value for value in values if value != "Total"]
    return values


def purpose_options_from_trips(runs: Sequence[tuple[str, RunData]], include_total: bool = True) -> list[str]:
    """Collect purpose options from trip tables across all runs."""
    values = _collect_values(_run_tables(runs, "trips"), "primary_purpose")
    if include_total:
        values = ["Total"] + [value for value in values if value != "Total"]
    return values


def person_type_options(runs: Sequence[tuple[str, RunData]], config: Config, include_total: bool = True) -> list[str]:
    """Collect display-ready person type options from all runs."""
    raw_values = _collect_values(_run_tables(runs, "per"), config.col_ptype)
    labels = [config.ptype_label(value) for value in raw_values]
    if include_total:
        labels = ["Total"] + [label for label in labels if label != "Total"]
    return labels


def person_type_label_map(runs: Sequence[tuple[str, RunData]], config: Config, include_total: bool = True) -> dict[str, str]:
    """Return a display-label to raw-value map for person type selectors."""
    raw_values = _collect_values(_run_tables(runs, "per"), config.col_ptype)
    mapping = {config.ptype_label(value): value for value in raw_values}
    if include_total:
        mapping["Total"] = "Total"
    return mapping


def hh_size_options(runs: Sequence[tuple[str, RunData]], include_total: bool = True) -> list[str]:
    """Collect household size options from prepared household tables."""
    values = _collect_values(_run_tables(runs, "hh"), "HHSIZE")
    if include_total:
        values = ["Total"] + [value for value in values if value != "Total"]
    return values


def geography_options(runs: Sequence[tuple[str, RunData]], include_all: bool = True) -> list[str]:
    """Collect geography labels from prepared person or household tables."""
    values = set(_collect_values(_run_tables(runs, "per"), "HGEO"))
    values.update(_collect_values(_run_tables(runs, "hh"), "HGEO"))
    ordered = sorted(values)
    if include_all:
        return ["All"] + [value for value in ordered if value != "All"]
    return ordered


def trip_tour_mode_options(runs: Sequence[tuple[str, RunData]], include_all: bool = True) -> list[str]:
    """Collect tour mode options from prepared trip tables."""
    values = _collect_values(_run_tables(runs, "trips"), "tour_mode")
    if include_all:
        values = ["All"] + [value for value in values if value != "All"]
    return values


def tour_mode_options(runs: Sequence[tuple[str, RunData]], config: Config | None = None, include_total: bool = False) -> list[str]:
    """Collect tour mode options from prepared tour tables, honoring configured ordering when available."""
    values = _collect_values(_run_tables(runs, "tours"), "tour_mode")
    if config is not None:
        values = config.ordered_modes(values)
    if include_total:
        values = ["Total"] + [value for value in values if value != "Total"]
    return values
