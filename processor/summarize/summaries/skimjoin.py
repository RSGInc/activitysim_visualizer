"""Summaries for skim-enriched prepared tables."""

from __future__ import annotations

import math

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary
from runtime.config import Config

_PERCENTILES = [index / 100 for index in range(101)]
_ALL_MODES = "All Modes"
_CHOSEN_MODE_SCENARIO = "chosen_mode"
_ALL_RECORDS_SCENARIO = "all_records"


def _is_numeric_dtype(dtype: pl.DataType | None) -> bool:
    if dtype is None:
        return False
    checker = getattr(dtype, "is_numeric", None)
    return bool(checker()) if callable(checker) else False


def _skim_component_columns(df: pl.DataFrame) -> list[str]:
    return [
        column
        for column in df.columns
        if "skim_" in column and _is_numeric_dtype(df.schema.get(column))
    ]


def _mode_value(values: list[float], weights: list[float]) -> float | None:
    if not values:
        return None

    totals: dict[float, float] = {}
    for value, weight in zip(values, weights, strict=False):
        totals[value] = totals.get(value, 0.0) + weight

    best_weight = max(totals.values())
    return min(value for value, weight in totals.items() if weight == best_weight)


def _weighted_nonzero_mean(
    values: list[float],
    weights: list[float],
) -> float | None:
    nonzero_pairs = [
        (value, weight)
        for value, weight in zip(values, weights, strict=False)
        if value != 0.0
    ]
    nonzero_weight = sum(weight for _, weight in nonzero_pairs)
    if nonzero_weight <= 0:
        return None
    return sum(value * weight for value, weight in nonzero_pairs) / nonzero_weight


def _weighted_quantile(
    values: list[float],
    weights: list[float],
    percentile: float,
) -> float | None:
    if not values:
        return None

    pairs = sorted(zip(values, weights, strict=False), key=lambda item: item[0])
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None

    threshold = total_weight * percentile
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _sorted_weighted_pairs(
    values: list[float],
    weights: list[float],
) -> tuple[list[float], list[float], float]:
    if not values:
        return [], [], 0.0
    pairs = sorted(zip(values, weights, strict=False), key=lambda item: item[0])
    sorted_values = [value for value, _ in pairs]
    sorted_weights = [weight for _, weight in pairs]
    total_weight = float(sum(sorted_weights))
    return sorted_values, sorted_weights, total_weight


def _weighted_quantiles_from_sorted_pairs(
    sorted_values: list[float],
    sorted_weights: list[float],
    total_weight: float,
    percentiles: list[float],
) -> list[float | None]:
    if not sorted_values or total_weight <= 0:
        return [None] * len(percentiles)

    thresholds = [total_weight * percentile for percentile in percentiles]
    results: list[float | None] = []
    cumulative = 0.0
    index = 0
    current_value = sorted_values[0]

    for threshold in thresholds:
        while index < len(sorted_values) and cumulative < threshold:
            current_value = sorted_values[index]
            cumulative += sorted_weights[index]
            index += 1
        results.append(current_value)

    return results


def _weighted_stats_rows(
    df: pl.DataFrame,
    *,
    mode_column: str,
    skim_scenario: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    component_columns = _skim_component_columns(df)
    if not component_columns:
        return rows

    if mode_column not in df.columns or "finalweight" not in df.columns:
        return rows

    mode_groups = _mode_groups(df, mode_column=mode_column)
    for component in component_columns:
        pertinent_df = _pertinent_component_df(
            df, component=component, mode_column=mode_column
        )
        for mode_value, mode_df in [(_ALL_MODES, pertinent_df), *mode_groups]:
            rows.append(
                _weighted_stats_row(
                    mode_df,
                    mode_column=mode_column,
                    mode_value=mode_value,
                    component=component,
                    skim_scenario=skim_scenario,
                )
            )

    return rows


def _weighted_ecdf_rows(
    df: pl.DataFrame,
    *,
    mode_column: str,
    skim_scenario: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    component_columns = _skim_component_columns(df)
    if not component_columns:
        return rows

    if mode_column not in df.columns or "finalweight" not in df.columns:
        return rows

    mode_groups = _mode_groups(df, mode_column=mode_column)
    for component in component_columns:
        pertinent_df = _pertinent_component_df(
            df, component=component, mode_column=mode_column
        )
        for mode_value, mode_df in [(_ALL_MODES, pertinent_df), *mode_groups]:
            valid_df = mode_df.filter(pl.col(component).is_not_null())
            if valid_df.is_empty():
                continue

            values = [
                float(value)
                for value in valid_df.get_column(component).cast(pl.Float64).to_list()
            ]
            weights = [
                float(value)
                for value in valid_df.get_column("finalweight")
                .cast(pl.Float64)
                .to_list()
            ]
            sorted_values, sorted_weights, n_valid = _sorted_weighted_pairs(
                values, weights
            )
            if n_valid <= 0:
                continue

            quantile_values = _weighted_quantiles_from_sorted_pairs(
                sorted_values,
                sorted_weights,
                n_valid,
                _PERCENTILES,
            )
            for percentile, quantile_value in zip(
                _PERCENTILES, quantile_values, strict=False
            ):
                rows.append(
                    {
                        "skim_scenario": skim_scenario,
                        mode_column: mode_value,
                        "component": component,
                        "percentile": float(percentile),
                        "value": quantile_value,
                        "n_valid": n_valid,
                    }
                )

    return rows


def _stats_frame(
    df: pl.DataFrame,
    *,
    mode_column: str,
    sidecar: pl.DataFrame,
    builder,
) -> pl.DataFrame:
    rows = _weighted_stats_rows(
        df,
        mode_column=mode_column,
        skim_scenario=_CHOSEN_MODE_SCENARIO,
    )
    rows.extend(_weighted_stats_rows_from_sidecar(sidecar, mode_column=mode_column))
    if not rows:
        return empty_summary_frame(builder)
    empty_frame = empty_summary_frame(builder)
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(*empty_frame.columns)
        .cast(empty_frame.schema)
        .with_columns(
            pl.when(pl.col("skim_scenario") == _CHOSEN_MODE_SCENARIO)
            .then(0)
            .otherwise(1)
            .alias("__scenario_sort"),
            pl.when(pl.col(mode_column) == _ALL_MODES)
            .then(0)
            .otherwise(1)
            .alias("__mode_sort"),
        )
        .sort(["__scenario_sort", "__mode_sort", mode_column, "component"])
        .drop("__scenario_sort", "__mode_sort")
    )


def _ecdf_frame(
    df: pl.DataFrame,
    *,
    mode_column: str,
    sidecar: pl.DataFrame,
    builder,
) -> pl.DataFrame:
    rows = _weighted_ecdf_rows(
        df,
        mode_column=mode_column,
        skim_scenario=_CHOSEN_MODE_SCENARIO,
    )
    rows.extend(
        _weighted_ecdf_rows_from_sidecar(
            sidecar,
            mode_column=mode_column,
        )
    )
    if not rows:
        return empty_summary_frame(builder)
    empty_frame = empty_summary_frame(builder)
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(*empty_frame.columns)
        .cast(empty_frame.schema)
        .with_columns(
            pl.when(pl.col("skim_scenario") == _CHOSEN_MODE_SCENARIO)
            .then(0)
            .otherwise(1)
            .alias("__scenario_sort"),
            pl.when(pl.col(mode_column) == _ALL_MODES)
            .then(0)
            .otherwise(1)
            .alias("__mode_sort"),
        )
        .sort(
            ["__scenario_sort", "__mode_sort", mode_column, "component", "percentile"]
        )
        .drop("__scenario_sort", "__mode_sort")
    )


def _mode_groups(
    df: pl.DataFrame,
    *,
    mode_column: str,
) -> list[tuple[str, pl.DataFrame]]:
    mode_values = (
        df.filter(pl.col(mode_column).is_not_null())
        .select(pl.col(mode_column).cast(pl.Utf8))
        .unique()
        .sort(mode_column)
        .get_column(mode_column)
        .to_list()
    )
    groups: list[tuple[str, pl.DataFrame]] = []
    groups.extend(
        (
            str(mode_value),
            df.filter(pl.col(mode_column).cast(pl.Utf8) == mode_value),
        )
        for mode_value in mode_values
    )
    return groups


def _pertinent_component_df(
    df: pl.DataFrame,
    *,
    component: str,
    mode_column: str,
) -> pl.DataFrame:
    pertinent_modes = (
        df.filter(pl.col(component).is_not_null() & pl.col(mode_column).is_not_null())
        .select(pl.col(mode_column).cast(pl.Utf8))
        .unique()
        .get_column(mode_column)
        .to_list()
    )
    if not pertinent_modes:
        return df.head(0)
    return df.filter(pl.col(mode_column).cast(pl.Utf8).is_in(pertinent_modes))


def _weighted_stats_row(
    df: pl.DataFrame,
    *,
    mode_column: str,
    mode_value: str,
    component: str,
    skim_scenario: str,
) -> dict[str, object]:
    n_total = float(
        df.select(pl.col("finalweight").sum().alias("n_total"))["n_total"][0] or 0.0
    )
    valid_df = df.filter(pl.col(component).is_not_null())
    if valid_df.is_empty():
        return {
            "skim_scenario": skim_scenario,
            mode_column: mode_value,
            "component": component,
            "n_total": n_total,
            "n_valid": 0.0,
            "mean": None,
            "mean_nonzero": None,
            "std": None,
            "min": None,
            "max": None,
            "median": None,
            "mode": None,
            "zero_share": None,
            "missing_share": (None if n_total == 0 else (n_total - 0.0) / n_total),
        }

    values = [
        float(value)
        for value in valid_df.get_column(component).cast(pl.Float64).to_list()
    ]
    weights = [
        float(value)
        for value in valid_df.get_column("finalweight").cast(pl.Float64).to_list()
    ]
    n_valid = float(sum(weights))
    if n_valid <= 0:
        return {
            "skim_scenario": skim_scenario,
            mode_column: mode_value,
            "component": component,
            "n_total": n_total,
            "n_valid": 0.0,
            "mean": None,
            "mean_nonzero": None,
            "std": None,
            "min": None,
            "max": None,
            "median": None,
            "mode": None,
            "zero_share": None,
            "missing_share": None if n_total == 0 else 1.0,
        }

    mean = (
        sum(value * weight for value, weight in zip(values, weights, strict=False))
        / n_valid
    )
    variance = (
        sum(
            weight * ((value - mean) ** 2)
            for value, weight in zip(values, weights, strict=False)
        )
        / n_valid
    )
    zero_weight = sum(
        weight for value, weight in zip(values, weights, strict=False) if value == 0.0
    )
    return {
        "skim_scenario": skim_scenario,
        mode_column: mode_value,
        "component": component,
        "n_total": n_total,
        "n_valid": n_valid,
        "mean": mean,
        "mean_nonzero": _weighted_nonzero_mean(values, weights),
        "std": math.sqrt(variance),
        "min": min(values),
        "max": max(values),
        "median": _weighted_quantile(values, weights, 0.5),
        "mode": _mode_value(values, weights),
        "zero_share": zero_weight / n_valid,
        "missing_share": None if n_total == 0 else (n_total - n_valid) / n_total,
    }


def _weighted_stats_rows_from_sidecar(
    sidecar: pl.DataFrame,
    *,
    mode_column: str,
) -> list[dict[str, object]]:
    return _weighted_rows_from_sidecar(
        sidecar,
        mode_column=mode_column,
        row_builder=_weighted_stats_row_from_sidecar_group,
    )


def _weighted_ecdf_rows_from_sidecar(
    sidecar: pl.DataFrame,
    *,
    mode_column: str,
) -> list[dict[str, object]]:
    return _weighted_rows_from_sidecar(
        sidecar,
        mode_column=mode_column,
        row_builder=_weighted_ecdf_rows_from_sidecar_group,
    )


def _weighted_rows_from_sidecar(
    sidecar: pl.DataFrame,
    *,
    mode_column: str,
    row_builder,
) -> list[dict[str, object]]:
    if sidecar.is_empty():
        return []
    required = {"hypothetical_mode", "component", "value", "finalweight"}
    if not required.issubset(sidecar.columns):
        return []
    rows: list[dict[str, object]] = []
    for group_key, group in sidecar.group_by(
        ["hypothetical_mode", "component"],
        maintain_order=True,
    ):
        hypothetical_mode, component = group_key
        rows.extend(
            row_builder(
                group,
                mode_column=mode_column,
                mode_value=str(hypothetical_mode),
                component=str(component),
            )
        )
    return rows


def _weighted_stats_row_from_sidecar_group(
    df: pl.DataFrame,
    *,
    mode_column: str,
    mode_value: str,
    component: str,
) -> list[dict[str, object]]:
    n_total = float(
        df.select(pl.col("finalweight").sum().alias("n_total"))["n_total"][0] or 0.0
    )
    valid_df = df.filter(pl.col("value").is_not_null())
    if valid_df.is_empty():
        return [
            {
                "skim_scenario": _ALL_RECORDS_SCENARIO,
                mode_column: mode_value,
                "component": component,
                "n_total": n_total,
                "n_valid": 0.0,
                "mean": None,
                "mean_nonzero": None,
                "std": None,
                "min": None,
                "max": None,
                "median": None,
                "mode": None,
                "zero_share": None,
                "missing_share": (None if n_total == 0 else 1.0),
            }
        ]
    values = [
        float(value)
        for value in valid_df.get_column("value").cast(pl.Float64).to_list()
    ]
    weights = [
        float(value)
        for value in valid_df.get_column("finalweight").cast(pl.Float64).to_list()
    ]
    n_valid = float(sum(weights))
    if n_valid <= 0:
        return []
    mean = (
        sum(value * weight for value, weight in zip(values, weights, strict=False))
        / n_valid
    )
    variance = (
        sum(
            weight * ((value - mean) ** 2)
            for value, weight in zip(values, weights, strict=False)
        )
        / n_valid
    )
    zero_weight = sum(
        weight for value, weight in zip(values, weights, strict=False) if value == 0.0
    )
    return [
        {
            "skim_scenario": _ALL_RECORDS_SCENARIO,
            mode_column: mode_value,
            "component": component,
            "n_total": n_total,
            "n_valid": n_valid,
            "mean": mean,
            "mean_nonzero": _weighted_nonzero_mean(values, weights),
            "std": math.sqrt(variance),
            "min": min(values),
            "max": max(values),
            "median": _weighted_quantile(values, weights, 0.5),
            "mode": _mode_value(values, weights),
            "zero_share": zero_weight / n_valid,
            "missing_share": None if n_total == 0 else (n_total - n_valid) / n_total,
        }
    ]


def _weighted_ecdf_rows_from_sidecar_group(
    df: pl.DataFrame,
    *,
    mode_column: str,
    mode_value: str,
    component: str,
) -> list[dict[str, object]]:
    valid_df = df.filter(pl.col("value").is_not_null())
    if valid_df.is_empty():
        return []
    values = [
        float(value)
        for value in valid_df.get_column("value").cast(pl.Float64).to_list()
    ]
    weights = [
        float(value)
        for value in valid_df.get_column("finalweight").cast(pl.Float64).to_list()
    ]
    sorted_values, sorted_weights, n_valid = _sorted_weighted_pairs(values, weights)
    if n_valid <= 0:
        return []
    quantile_values = _weighted_quantiles_from_sorted_pairs(
        sorted_values,
        sorted_weights,
        n_valid,
        _PERCENTILES,
    )
    return [
        {
            "skim_scenario": _ALL_RECORDS_SCENARIO,
            mode_column: mode_value,
            "component": component,
            "percentile": float(percentile),
            "value": quantile_value,
            "n_valid": n_valid,
        }
        for percentile, quantile_value in zip(
            _PERCENTILES, quantile_values, strict=False
        )
    ]


@summary(
    id="skimjoin_trip_component_stats",
    schema={
        "skim_scenario": pl.Utf8,
        "trip_mode": pl.Utf8,
        "component": pl.Utf8,
        "n_total": pl.Float64,
        "n_valid": pl.Float64,
        "mean": pl.Float64,
        "mean_nonzero": pl.Float64,
        "std": pl.Float64,
        "min": pl.Float64,
        "max": pl.Float64,
        "median": pl.Float64,
        "mode": pl.Float64,
        "zero_share": pl.Float64,
        "missing_share": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "finalweight")},
)
def trip_skim_component_stats(rd: RunData, config: Config) -> pl.DataFrame:
    return _stats_frame(
        rd.trips,
        mode_column="trip_mode",
        sidecar=rd.trip_hypothetical_skims,
        builder=trip_skim_component_stats,
    )


@summary(
    id="skimjoin_trip_component_ecdf",
    build_by_default=False,
    schema={
        "skim_scenario": pl.Utf8,
        "trip_mode": pl.Utf8,
        "component": pl.Utf8,
        "percentile": pl.Float64,
        "value": pl.Float64,
        "n_valid": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "finalweight")},
)
def trip_skim_component_ecdf(rd: RunData, config: Config) -> pl.DataFrame:
    return _ecdf_frame(
        rd.trips,
        mode_column="trip_mode",
        sidecar=rd.trip_hypothetical_skims,
        builder=trip_skim_component_ecdf,
    )


@summary(
    id="skimjoin_tour_component_stats",
    schema={
        "skim_scenario": pl.Utf8,
        "tour_mode": pl.Utf8,
        "component": pl.Utf8,
        "n_total": pl.Float64,
        "n_valid": pl.Float64,
        "mean": pl.Float64,
        "mean_nonzero": pl.Float64,
        "std": pl.Float64,
        "min": pl.Float64,
        "max": pl.Float64,
        "median": pl.Float64,
        "mode": pl.Float64,
        "zero_share": pl.Float64,
        "missing_share": pl.Float64,
    },
    required_columns={"tours": ("tour_mode", "finalweight")},
)
def tour_skim_component_stats(rd: RunData, config: Config) -> pl.DataFrame:
    return _stats_frame(
        rd.tours,
        mode_column="tour_mode",
        sidecar=rd.tour_hypothetical_skims,
        builder=tour_skim_component_stats,
    )


@summary(
    id="skimjoin_tour_component_ecdf",
    build_by_default=False,
    schema={
        "skim_scenario": pl.Utf8,
        "tour_mode": pl.Utf8,
        "component": pl.Utf8,
        "percentile": pl.Float64,
        "value": pl.Float64,
        "n_valid": pl.Float64,
    },
    required_columns={"tours": ("tour_mode", "finalweight")},
)
def tour_skim_component_ecdf(rd: RunData, config: Config) -> pl.DataFrame:
    return _ecdf_frame(
        rd.tours,
        mode_column="tour_mode",
        sidecar=rd.tour_hypothetical_skims,
        builder=tour_skim_component_ecdf,
    )
