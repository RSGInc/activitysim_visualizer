"""Derived summaries built from validation scaffold tables."""

from __future__ import annotations

import math

from runtime.logging import get_logger
import polars as pl

from processor.summarize.cache_types import SummaryRun, create_summary_run
from processor.summarize.contracts import empty_summary_frame
from processor.summarize.summaries import validation_scaffolds

LOGGER = get_logger("processor.summarize")

COUNT_LOCATION_COUNTS_ID = "count_location_counts_validation_summary"
COUNT_LOCATION_VOLUMES_ID = "count_location_volumes_validation_summary"
COUNT_LOCATION_SCATTER_ID = "count_location_scatter_validation_summary"
COUNT_LOCATION_FIT_ID = "count_location_fit_validation_summary"

COUNT_LOCATION_DERIVED_IDS = (
    COUNT_LOCATION_SCATTER_ID,
    COUNT_LOCATION_FIT_ID,
)

COUNT_LOCATION_PERIOD_COLUMNS = {
    "AM": "am_vol",
    "MD": "md_vol",
    "PM": "pm_vol",
    "Day": "day_vol",
}


def _empty_count_location_scatter_validation_summary() -> pl.DataFrame:
    return empty_summary_frame(
        validation_scaffolds.count_location_scatter_validation_summary
    )


def _empty_count_location_fit_validation_summary() -> pl.DataFrame:
    return empty_summary_frame(
        validation_scaffolds.count_location_fit_validation_summary
    )


def build_count_location_scatter_validation_summary(
    counts: pl.DataFrame,
    volumes: pl.DataFrame,
) -> pl.DataFrame:
    """Return long observed/modeled count-location rows from wide source tables."""
    frames: list[pl.DataFrame] = []
    for period, volume_col in COUNT_LOCATION_PERIOD_COLUMNS.items():
        if volume_col not in counts.columns or volume_col not in volumes.columns:
            continue
        count_period = counts.select(
            pl.col("id").cast(pl.Int64, strict=False),
            pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
            pl.lit(period).alias("period"),
            pl.col(volume_col).cast(pl.Float64).alias("observed_volume"),
        )
        volume_period = volumes.select(
            pl.col("id").cast(pl.Int64, strict=False),
            pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
            pl.lit(period).alias("period"),
            pl.col(volume_col).cast(pl.Float64).alias("modeled_volume"),
        )
        frames.append(
            count_period.join(
                volume_period,
                on=["id", "facility_type", "period"],
                how="inner",
            )
        )
    if not frames:
        return _empty_count_location_scatter_validation_summary()
    return (
        pl.concat(frames, how="vertical")
        .filter(
            pl.col("id").is_not_null()
            & pl.col("facility_type").is_not_null()
            & pl.col("observed_volume").is_not_null()
            & pl.col("modeled_volume").is_not_null()
        )
        .select(
            "id",
            "facility_type",
            "period",
            "observed_volume",
            "modeled_volume",
        )
        .sort(["period", "facility_type", "id"])
    )


def _equation_label(slope: float, intercept: float) -> str:
    sign = "+" if intercept >= 0 else "-"
    return f"y = {slope:.2f}x {sign} {abs(intercept):.2f}"


def _fit_group(
    df: pl.DataFrame, *, facility_type: str, period: str
) -> dict[str, object]:
    points = df.select("observed_volume", "modeled_volume").drop_nulls()
    n = points.height
    base: dict[str, object] = {
        "facility_type": facility_type,
        "period": period,
        "slope": None,
        "intercept": None,
        "r_squared": None,
        "n_locations": n,
        "observed_min": None,
        "observed_max": None,
        "equation_label": "",
        "r_squared_label": "",
    }
    if n == 0:
        return base

    x = [float(value) for value in points["observed_volume"].to_list()]
    y = [float(value) for value in points["modeled_volume"].to_list()]
    observed_min = min(x)
    observed_max = max(x)
    base["observed_min"] = observed_min
    base["observed_max"] = observed_max
    if n < 2:
        return base

    x_mean = sum(x) / n
    y_mean = sum(y) / n
    ss_xx = sum((value - x_mean) ** 2 for value in x)
    if math.isclose(ss_xx, 0.0):
        return base

    ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    fitted = [slope * xi + intercept for xi in x]
    sse = sum((yi - yhat) ** 2 for yi, yhat in zip(y, fitted))
    ss_yy = sum((yi - y_mean) ** 2 for yi in y)
    r_squared = (
        (1.0 if math.isclose(sse, 0.0) else 0.0)
        if math.isclose(ss_yy, 0.0)
        else max(0.0, min(1.0, 1.0 - sse / ss_yy))
    )

    base.update(
        slope=float(slope),
        intercept=float(intercept),
        r_squared=float(r_squared),
        equation_label=_equation_label(slope, intercept),
        r_squared_label=f"R^2 = {r_squared:.2f}",
    )
    return base


def build_count_location_fit_validation_summary(scatter: pl.DataFrame) -> pl.DataFrame:
    """Return OLS fit rows by period and facility type, including All."""
    if scatter.is_empty():
        return _empty_count_location_fit_validation_summary()

    rows: list[dict[str, object]] = []
    for period in COUNT_LOCATION_PERIOD_COLUMNS:
        period_df = scatter.filter(pl.col("period") == period)
        if period_df.is_empty():
            continue
        rows.append(_fit_group(period_df, facility_type="All", period=period))
        facility_types = sorted(
            str(value)
            for value in period_df["facility_type"].drop_nulls().unique().to_list()
        )
        for facility_type in facility_types:
            rows.append(
                _fit_group(
                    period_df.filter(pl.col("facility_type") == facility_type),
                    facility_type=facility_type,
                    period=period,
                )
            )
    if not rows:
        return _empty_count_location_fit_validation_summary()
    return pl.DataFrame(rows).with_columns(
        pl.col("facility_type").cast(pl.Utf8),
        pl.col("period").cast(pl.Utf8),
        pl.col("slope").cast(pl.Float64),
        pl.col("intercept").cast(pl.Float64),
        pl.col("r_squared").cast(pl.Float64),
        pl.col("n_locations").cast(pl.Int64),
        pl.col("observed_min").cast(pl.Float64),
        pl.col("observed_max").cast(pl.Float64),
        pl.col("equation_label").cast(pl.Utf8),
        pl.col("r_squared_label").cast(pl.Utf8),
    )


def apply_validation_derived_summaries(
    summary_runs: list[SummaryRun],
) -> list[SummaryRun]:
    """Rebuild derived validation summaries for every summary run when inputs exist."""
    if not summary_runs:
        return []

    derived_runs: list[SummaryRun] = []
    for summary_run in summary_runs:
        summaries_by_mode: dict[str, dict[str, pl.DataFrame]] = {}
        metadata_by_mode: dict[str, dict[str, dict[str, object]]] = {}
        for mode, tables in summary_run.summaries_by_mode.items():
            mode_tables = {
                summary_id: table
                for summary_id, table in tables.items()
                if summary_id not in COUNT_LOCATION_DERIVED_IDS
            }
            mode_metadata = {
                summary_id: dict(metadata)
                for summary_id, metadata in summary_run.summary_metadata_by_mode.get(
                    mode, {}
                ).items()
                if summary_id not in COUNT_LOCATION_DERIVED_IDS
            }
            counts = mode_tables.get(COUNT_LOCATION_COUNTS_ID)
            volumes = mode_tables.get(COUNT_LOCATION_VOLUMES_ID)
            if counts is not None and volumes is not None:
                scatter = build_count_location_scatter_validation_summary(
                    counts, volumes
                )
                fit = build_count_location_fit_validation_summary(scatter)
                mode_tables[COUNT_LOCATION_SCATTER_ID] = scatter
                mode_tables[COUNT_LOCATION_FIT_ID] = fit
                detail = (
                    "derived from count_location_counts_validation_summary and "
                    "count_location_volumes_validation_summary"
                )
                mode_metadata[COUNT_LOCATION_SCATTER_ID] = {
                    "state": "empty" if scatter.is_empty() else "available",
                    "source": "derived_summary",
                    "detail": detail,
                    "dependencies": [
                        COUNT_LOCATION_COUNTS_ID,
                        COUNT_LOCATION_VOLUMES_ID,
                    ],
                }
                mode_metadata[COUNT_LOCATION_FIT_ID] = {
                    "state": "empty" if fit.is_empty() else "available",
                    "source": "derived_summary",
                    "detail": detail,
                    "dependencies": [
                        COUNT_LOCATION_COUNTS_ID,
                        COUNT_LOCATION_VOLUMES_ID,
                    ],
                }
                LOGGER.info(
                    "Built count-location validation derived summaries for %r "
                    "(%s): %d scatter rows, %d fit rows",
                    summary_run.label,
                    mode,
                    scatter.height,
                    fit.height,
                )
            summaries_by_mode[mode] = mode_tables
            metadata_by_mode[mode] = mode_metadata

        derived_runs.append(
            create_summary_run(
                label=summary_run.label,
                run_key=summary_run.run_key,
                summaries_by_mode=summaries_by_mode,
                summary_metadata_by_mode=metadata_by_mode,
                segmentation_type=summary_run.segmentation_type,
                segment_id=summary_run.segment_id,
                segment_label=summary_run.segment_label,
                is_full_segment=summary_run.is_full_segment,
                segment_source_type=summary_run.segment_source_type,
                segment_column=summary_run.segment_column,
                segment_values=summary_run.segment_values,
                segment_source_table=summary_run.segment_source_table,
                segment_source_key_column=summary_run.segment_source_key_column,
                segment_csv_file=summary_run.segment_csv_file,
                segment_csv_key_column=summary_run.segment_csv_key_column,
                segment_csv_value_column=summary_run.segment_csv_value_column,
                source_run_dir=summary_run.source_run_dir,
                manifest=summary_run.manifest,
            )
        )
    return derived_runs


__all__ = [
    "COUNT_LOCATION_DERIVED_IDS",
    "COUNT_LOCATION_FIT_ID",
    "COUNT_LOCATION_SCATTER_ID",
    "apply_validation_derived_summaries",
    "build_count_location_fit_validation_summary",
    "build_count_location_scatter_validation_summary",
]
