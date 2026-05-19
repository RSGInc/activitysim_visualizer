"""Shared helpers for skim summary dashboard pages."""

from __future__ import annotations

import numpy as np
import polars as pl

from processor.models import RunData

TRIP_STATS_SUMMARY_ID = "skimjoin_trip_component_stats"
TOUR_STATS_SUMMARY_ID = "skimjoin_tour_component_stats"
TRIP_ECDF_SUMMARY_ID = "skimjoin_trip_component_ecdf"
TOUR_ECDF_SUMMARY_ID = "skimjoin_tour_component_ecdf"
DEFAULT_BIN_COUNT = 500
DIRECTION_SUFFIXES = ("_outbound", "_inbound")
ALL_MODES = "All Modes"


def nonempty(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, df)
        for label, df in (data_list or [])
        if df is not None and not df.is_empty()
    ]


def component_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    components: list[str] = []
    for _, df in nonempty(data_list):
        if "component" not in df.columns:
            continue
        filtered = df
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty():
            continue
        for value in (
            filtered.select(pl.col("component").cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort("component")
            .get_column("component")
            .to_list()
        ):
            if value not in components:
                components.append(value)
    return components or ["No components available"]


def tour_component_base_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    bases: list[str] = []
    for component in component_options(data_list):
        base = strip_direction_suffix(component)
        if base not in bases:
            bases.append(base)
    return bases or ["No components available"]


def strip_direction_suffix(component: str) -> str:
    for suffix in DIRECTION_SUFFIXES:
        if component.endswith(suffix):
            return component[: -len(suffix)]
    return component


def directional_component_name(component_base: str, direction: str) -> str:
    return f"{component_base}_{direction}"


def mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    mode_column: str,
    component: str | None,
) -> list[str]:
    options: list[str] = []
    for _, df in nonempty(data_list):
        filtered = df
        if (
            component
            and component != "No components available"
            and "component" in df.columns
        ):
            filtered = filtered.filter(pl.col("component").cast(pl.Utf8) == component)
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty() or mode_column not in filtered.columns:
            continue
        values = (
            filtered.select(pl.col(mode_column).cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort(mode_column)
            .get_column(mode_column)
            .to_list()
        )
        for value in values:
            if value == ALL_MODES:
                continue
            if value not in options:
                options.append(value)
    if not options:
        return ["No modes available"]
    return [ALL_MODES, *options]


def tour_mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    mode_column: str,
    component_base: str | None,
) -> list[str]:
    options: list[str] = []
    for _, df in nonempty(data_list):
        filtered = df
        if component_base and component_base != "No components available":
            outbound = directional_component_name(component_base, "outbound")
            inbound = directional_component_name(component_base, "inbound")
            filtered = filtered.filter(
                pl.col("component").cast(pl.Utf8).is_in([outbound, inbound])
            )
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty() or mode_column not in filtered.columns:
            continue
        values = (
            filtered.select(pl.col(mode_column).cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort(mode_column)
            .get_column(mode_column)
            .to_list()
        )
        for value in values:
            if value == ALL_MODES:
                continue
            if value not in options:
                options.append(value)
    if not options:
        return ["No modes available"]
    return [ALL_MODES, *options]


def filter_stats(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    component: str,
    mode_column: str,
    mode_value: str,
) -> list[tuple[str, pl.DataFrame]]:
    metric_columns = [
        "n_total",
        "n_valid",
        "mean",
        "std",
        "min",
        "max",
        "median",
        "mode",
        "zero_share",
        "missing_share",
    ]
    filtered_list: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(
            pl.col("component").cast(pl.Utf8),
            pl.col(mode_column).cast(pl.Utf8),
        ).filter(pl.col("component") == component)
        filtered = filtered.filter(pl.col(mode_column) == mode_value)
        filtered = filtered.select([column for column in metric_columns if column in df.columns])
        filtered_list.append((label, filtered))
    return filtered_list


def prepared_component_values(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    resolved: list[tuple[str, np.ndarray, np.ndarray]] = []
    for label, run in prepared_runs or []:
        df = getattr(run, table_name)
        if df is None or df.is_empty():
            continue
        required_columns = {mode_column, component}
        if not required_columns.issubset(df.columns):
            continue
        filtered = df.with_columns(pl.col(mode_column).cast(pl.Utf8)).filter(
            pl.col(component).is_not_null()
        )
        if mode_value != ALL_MODES:
            filtered = filtered.filter(pl.col(mode_column) == mode_value)
        filtered = filtered.select(
            pl.col(component).cast(pl.Float64).alias(component),
            (
                pl.col("finalweight").cast(pl.Float64)
                if "finalweight" in df.columns
                else pl.lit(1.0)
            ).alias("finalweight"),
        )
        if filtered.is_empty():
            continue
        values = filtered.get_column(component).to_numpy()
        weights = filtered.get_column("finalweight").to_numpy()
        resolved.append((label, values, weights))
    return resolved


def distribution_bins(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
    x_range: tuple[float, float] | None = None,
    bin_count: int = DEFAULT_BIN_COUNT,
) -> list[tuple[str, pl.DataFrame]]:
    value_sets = prepared_component_values(
        prepared_runs,
        table_name=table_name,
        mode_column=mode_column,
        mode_value=mode_value,
        component=component,
    )
    if not value_sets:
        return []

    all_values = np.concatenate([values for _, values, _ in value_sets])
    if all_values.size == 0:
        return []
    min_value = float(np.min(all_values))
    max_value = float(np.max(all_values))

    if x_range is not None:
        min_value = float(x_range[0])
        max_value = float(x_range[1])

    if min_value == max_value:
        bin_mid = min_value
        return [
            (
                label,
                pl.DataFrame(
                    {
                        "bin_mid": [bin_mid],
                        "freq": [float(np.sum(weights))],
                    }
                ),
            )
            for label, _, weights in value_sets
        ]

    edges = np.linspace(min_value, max_value, num=bin_count + 1)
    mids = ((edges[:-1] + edges[1:]) / 2.0).tolist()
    distributions: list[tuple[str, pl.DataFrame]] = []
    for label, values, weights in value_sets:
        in_range = (values >= min_value) & (values <= max_value)
        histogram_values = values[in_range]
        histogram_weights = weights[in_range]
        if histogram_values.size == 0:
            hist = np.zeros(len(mids), dtype=float)
        else:
            hist, _ = np.histogram(
                histogram_values,
                bins=edges,
                weights=histogram_weights,
            )
        distributions.append(
            (
                label,
                pl.DataFrame(
                    {
                        "bin_mid": mids,
                        "freq": hist.astype(float).tolist(),
                    }
                ),
            )
        )
    return distributions


def distribution_data_bounds(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
) -> tuple[float, float] | None:
    value_sets = prepared_component_values(
        prepared_runs,
        table_name=table_name,
        mode_column=mode_column,
        mode_value=mode_value,
        component=component,
    )
    if not value_sets:
        return None
    all_values = np.concatenate(
        [values for _, values, _ in value_sets if values.size > 0]
    )
    if all_values.size == 0:
        return None
    return (float(np.min(all_values)), float(np.max(all_values)))


def resolve_distribution_range(
    min_value: float | None,
    max_value: float | None,
) -> tuple[float, float] | None:
    if min_value is None or max_value is None:
        return None
    if not np.isfinite(min_value) or not np.isfinite(max_value):
        return None
    if float(max_value) <= float(min_value):
        return None
    return (float(min_value), float(max_value))
