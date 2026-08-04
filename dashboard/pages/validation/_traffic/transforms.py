"""Pure transformations for Traffic Validation."""

from __future__ import annotations

import math

import polars as pl

from dashboard.helpers.category_helpers import (
    label_category_frame,
    nonempty,
    raw_display_options,
)
from runtime.config import Config

from .contracts import *


def screenline_scatter_data(
    data_list: list[tuple[str, pl.DataFrame]],
    *,
    period: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter screenline observed/modeled points for one period and facility."""
    out: list[tuple[str, pl.DataFrame]] = []
    required = {
        "screenline_id",
        "count_period",
        "observed_volume",
        "modeled_volume",
    }
    for label, df in nonempty(data_list):
        if not required.issubset(df.columns):
            continue
        filtered = df.with_columns(
            pl.col("count_period").cast(pl.Utf8),
            (
                pl.col("facility_type").cast(pl.Utf8)
                if "facility_type" in df.columns
                else pl.lit("All")
            ).alias("facility_type"),
        ).filter(pl.col("count_period") == period)
        if facility_type != "All":
            filtered = filtered.filter(pl.col("facility_type") == facility_type)
        out.append(
            (
                label,
                filtered.select(
                    "screenline_id",
                    "facility_type",
                    "count_period",
                    "observed_volume",
                    "modeled_volume",
                ).sort("screenline_id"),
            )
        )
    return out


def demo_facility_options(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
    config: Config,
) -> tuple[list[str], dict[str, str | None]]:
    values: list[str] = []
    seen: set[str] = set()
    for data_list in data_lists:
        for _, df in nonempty(data_list or []):
            for column in ("facility_type", "FACTYPE"):
                if column not in df.columns:
                    continue
                for value in df[column].drop_nulls().cast(pl.Utf8).to_list():
                    value_str = str(value)
                    if value_str == "All" or value_str in seen:
                        continue
                    values.append(value_str)
                    seen.add(value_str)
    ordered_values = config.ordered_values(FACILITY_TYPE_CATEGORY_ID, values)
    return raw_display_options(
        ordered_values,
        category_id=FACILITY_TYPE_CATEGORY_ID,
        config=config,
        total_raw="All",
        total_label="All",
    )


def _filter_facility(df: pl.DataFrame, facility_type: str) -> pl.DataFrame:
    if facility_type == "All" or "FACTYPE" not in df.columns:
        return df
    return df.with_columns(pl.col("FACTYPE").cast(pl.Utf8)).filter(
        pl.col("FACTYPE") == facility_type
    )


def demo_count_scatter_data(
    scatter_list: list[tuple[str, pl.DataFrame]],
    *,
    period: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(scatter_list):
        required = {"facility_type", "period", "observed_volume", "modeled_volume"}
        if not required.issubset(set(df.columns)):
            continue
        filtered = df.with_columns(
            pl.col("facility_type").cast(pl.Utf8),
            pl.col("period").cast(pl.Utf8),
        ).filter(pl.col("period") == period)
        if facility_type != "All":
            filtered = filtered.filter(pl.col("facility_type") == facility_type)
        out.append(
            (
                label,
                filtered.select(
                    "id",
                    "facility_type",
                    "period",
                    "observed_volume",
                    "modeled_volume",
                ).sort("id"),
            )
        )
    return out


def demo_count_scatter_data_from_sources(
    count_list: list[tuple[str, pl.DataFrame]],
    volume_list: list[tuple[str, pl.DataFrame]],
    *,
    volume_col: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    volume_by_label = dict(volume_list)
    out: list[tuple[str, pl.DataFrame]] = []
    for label, count_df in nonempty(count_list):
        volume_df = volume_by_label.get(label)
        if volume_df is None or volume_df.is_empty():
            continue
        count_df = _filter_facility(count_df, facility_type)
        volume_df = _filter_facility(volume_df, facility_type)
        if volume_col not in count_df.columns or volume_col not in volume_df.columns:
            continue
        joined = (
            count_df.select(
                "id",
                pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                pl.col(volume_col).alias("observed_volume"),
            )
            .join(
                volume_df.select(
                    "id",
                    pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                    pl.col(volume_col).alias("modeled_volume"),
                ),
                on=["id", "facility_type"],
                how="inner",
            )
            .sort("id")
        )
        out.append((label, joined))
    return out


def _fit_line_frame(
    *,
    observed_min: float,
    observed_max: float,
    slope: float,
    intercept: float,
    annotation: str,
) -> pl.DataFrame:
    point_count = 101
    step = (observed_max - observed_min) / (point_count - 1)
    observed = [observed_min + step * index for index in range(point_count)]
    return pl.DataFrame(
        {
            "observed_volume": observed,
            "modeled_volume": [slope * value + intercept for value in observed],
            "annotation": [annotation] * point_count,
        }
    )


def demo_count_fit_line_data(
    fit_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    period: str,
    facility_type: str,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(fit_list or []):
        required = {
            "facility_type",
            "period",
            "slope",
            "intercept",
            "r_squared",
            "n_locations",
            "observed_min",
            "observed_max",
            "equation_label",
            "r_squared_label",
        }
        if not required.issubset(set(df.columns)):
            continue
        selected = (
            df.with_columns(
                pl.col("facility_type").cast(pl.Utf8),
                pl.col("period").cast(pl.Utf8),
            )
            .filter(
                (pl.col("period") == period)
                & (pl.col("facility_type") == str(facility_type))
                & pl.col("slope").is_not_null()
                & pl.col("intercept").is_not_null()
                & pl.col("observed_min").is_not_null()
                & pl.col("observed_max").is_not_null()
            )
            .head(1)
        )
        if selected.is_empty():
            continue
        row = selected.row(0, named=True)
        observed_min = float(row["observed_min"])
        observed_max = float(row["observed_max"])
        slope = float(row["slope"])
        intercept = float(row["intercept"])
        annotation = (
            f"{label}<br>{row['equation_label']}<br>"
            f"{row['r_squared_label']}<br>n = {int(row['n_locations'])}"
        )
        out.append(
            (
                label,
                _fit_line_frame(
                    observed_min=observed_min,
                    observed_max=observed_max,
                    slope=slope,
                    intercept=intercept,
                    annotation=annotation,
                ),
            )
        )
    return out


def _linear_fit_from_points(
    points: pl.DataFrame,
) -> tuple[float, float, float] | None:
    if points.height < 2:
        return None
    x = [float(value) for value in points["observed_volume"].to_list()]
    y = [float(value) for value in points["modeled_volume"].to_list()]
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    ss_xx = sum((value - x_mean) ** 2 for value in x)
    if math.isclose(ss_xx, 0.0):
        return None
    ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    fitted = [slope * xi + intercept for xi in x]
    sse = sum((yi - yhat) ** 2 for yi, yhat in zip(y, fitted))
    ss_yy = sum((yi - y_mean) ** 2 for yi in y)
    if math.isclose(ss_yy, 0.0):
        r_squared = 1.0 if math.isclose(sse, 0.0) else 0.0
    else:
        r_squared = max(0.0, min(1.0, 1.0 - sse / ss_yy))
    return slope, intercept, r_squared


def _r_squared_from_points(points: pl.DataFrame) -> float | None:
    fit = _linear_fit_from_points(points)
    return None if fit is None else fit[2]


def screenline_fit_line_data(
    scatter_data: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    """Build regression lines and annotations from filtered screenline points."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(scatter_data):
        points = df.select("observed_volume", "modeled_volume").drop_nulls()
        fit = _linear_fit_from_points(points)
        if fit is None:
            continue
        slope, intercept, r_squared = fit
        observed_min = float(points["observed_volume"].min())
        observed_max = float(points["observed_volume"].max())
        sign = "+" if intercept >= 0 else "-"
        annotation = (
            f"{label}<br>y = {slope:.2f}x {sign} {abs(intercept):.2f}"
            f"<br>R^2 = {r_squared:.2f}<br>n = {points.height}"
        )
        out.append(
            (
                label,
                _fit_line_frame(
                    observed_min=observed_min,
                    observed_max=observed_max,
                    slope=slope,
                    intercept=intercept,
                    annotation=annotation,
                ),
            )
        )
    return out


def _fit_r_squared_lookup(
    fit_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    label: str,
    period: str,
    facility_type: str,
) -> dict[str, float]:
    if not fit_list:
        return {}
    fit_by_label = dict(fit_list)
    fit_df = fit_by_label.get(label)
    if fit_df is None or fit_df.is_empty():
        return {}
    required = {"facility_type", "period", "r_squared"}
    if not required.issubset(set(fit_df.columns)):
        return {}
    selected = fit_df.with_columns(
        pl.col("facility_type").cast(pl.Utf8),
        pl.col("period").cast(pl.Utf8),
    ).filter(
        (pl.col("period") == period)
        & (pl.col("facility_type") != "All")
        & pl.col("r_squared").is_not_null()
    )
    if facility_type != "All":
        selected = selected.filter(pl.col("facility_type") == facility_type)
    return {
        str(row["facility_type"]): float(row["r_squared"])
        for row in selected.select("facility_type", "r_squared").iter_rows(named=True)
    }


def demo_facility_comparison_table(
    scatter_data: list[tuple[str, pl.DataFrame]],
    fit_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    period: str,
    facility_type: str,
    config: Config,
) -> list[tuple[str, pl.DataFrame]]:
    """Aggregate count-location observed/modeled comparisons by facility type."""
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(scatter_data):
        required = {"facility_type", "observed_volume", "modeled_volume"}
        if df is None or df.is_empty() or not required.issubset(set(df.columns)):
            continue
        select_exprs = [
            pl.col("facility_type").cast(pl.Utf8),
            pl.col("observed_volume").cast(pl.Float64),
            pl.col("modeled_volume").cast(pl.Float64),
        ]
        if "id" in df.columns:
            select_exprs.insert(0, pl.col("id").cast(pl.Utf8).alias("id"))
        points = (
            df.select(*select_exprs)
            .drop_nulls(["facility_type", "observed_volume", "modeled_volume"])
            .filter(pl.col("facility_type") != "All")
        )
        if facility_type != "All":
            points = points.filter(pl.col("facility_type") == facility_type)
        if points.is_empty():
            continue

        r_squared_lookup = _fit_r_squared_lookup(
            fit_list,
            label=label,
            period=period,
            facility_type=facility_type,
        )
        facility_types = config.ordered_values(
            FACILITY_TYPE_CATEGORY_ID,
            [str(value) for value in points["facility_type"].unique().to_list()],
        )
        rows: list[dict[str, object]] = []
        for raw_facility_type in facility_types:
            facility_points = points.filter(
                pl.col("facility_type") == raw_facility_type
            )
            if facility_points.is_empty():
                continue
            observed = [
                float(value) for value in facility_points["observed_volume"].to_list()
            ]
            modeled = [
                float(value) for value in facility_points["modeled_volume"].to_list()
            ]
            total_observed = sum(observed)
            total_modeled = sum(modeled)
            n_locations = (
                facility_points["id"].n_unique()
                if "id" in facility_points.columns
                else facility_points.height
            )
            differences = [model - observe for observe, model in zip(observed, modeled)]
            rmse = math.sqrt(
                sum(difference**2 for difference in differences) / len(differences)
            )
            if any(value == 0.0 for value in observed):
                rmspe = ""
            else:
                squared_percentage_errors = [
                    ((observe - model) / observe) ** 2
                    for observe, model in zip(observed, modeled)
                ]
                rmspe_value = math.sqrt(
                    sum(squared_percentage_errors) / len(squared_percentage_errors)
                ) * 100.0
                rmspe = f"{rmspe_value:.2f}%"
            percent_value = (
                None
                if total_observed == 0.0
                else ((total_modeled - total_observed) / total_observed) * 100.0
            )
            percent_difference = (
                "" if percent_value is None else f"{percent_value:.2f}%"
            )
            rows.append(
                {
                    "Facility Type": config.label_value(
                        FACILITY_TYPE_CATEGORY_ID,
                        raw_facility_type,
                    ),
                    "n": int(n_locations),
                    "Total Observed Count": total_observed,
                    "Total Modeled Count": total_modeled,
                    "% Difference": percent_difference,
                    "RMSE": rmse,
                    "RMSPE": rmspe,
                    "R^2": r_squared_lookup.get(raw_facility_type)
                    if raw_facility_type in r_squared_lookup
                    else _r_squared_from_points(facility_points),
                }
            )
        if rows:
            out.append((label, pl.DataFrame(rows)))
    return out


def demo_link_aggregate_data(
    link_list: list[tuple[str, pl.DataFrame]],
    *,
    volume_col: str,
    facility_type: str,
    config: Config | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    out: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(link_list):
        if volume_col not in df.columns:
            continue
        filtered = _filter_facility(df, facility_type)
        chart_df = (
            filtered.with_columns(pl.col("FACTYPE").cast(pl.Utf8))
            .group_by("FACTYPE")
            .agg(pl.col(volume_col).sum().alias("volume"))
            .sort("FACTYPE")
        )
        if config is not None:
            chart_df = label_category_frame(
                chart_df,
                source_col="FACTYPE",
                category_id=FACILITY_TYPE_CATEGORY_ID,
                config=config,
                target_col="facility_type_label",
            )
        out.append((label, chart_df))
    return out


def demo_volume_comparison_table(
    count_list: list[tuple[str, pl.DataFrame]],
    volume_list: list[tuple[str, pl.DataFrame]],
    *,
    link_list: list[tuple[str, pl.DataFrame]] | None = None,
    volume_col: str,
    facility_type: str,
    top_n: int,
) -> list[tuple[str, pl.DataFrame]]:
    volume_by_label = dict(volume_list)
    link_by_label = dict(link_list or [])
    quantity_a_column = "Observed Link Volume"
    quantity_b_column = "Modeled Link Volume"
    difference_column = "Difference"
    percent_difference_column = "% Difference"
    out: list[tuple[str, pl.DataFrame]] = []
    for label, count_df in nonempty(count_list):
        volume_df = volume_by_label.get(label)
        if volume_df is None or volume_df.is_empty():
            continue
        if volume_col not in count_df.columns or volume_col not in volume_df.columns:
            continue
        required = {"id", "FACTYPE"}
        if not required.issubset(count_df.columns) or not required.issubset(
            volume_df.columns
        ):
            continue

        count_filtered = _filter_facility(count_df, facility_type)
        volume_filtered = _filter_facility(volume_df, facility_type)
        joined = (
            count_filtered.select(
                pl.col("id").cast(pl.Int64, strict=False),
                pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                pl.col(volume_col).cast(pl.Float64).alias("_quantity_a"),
            )
            .join(
                volume_filtered.select(
                    pl.col("id").cast(pl.Int64, strict=False),
                    pl.col("FACTYPE").cast(pl.Utf8).alias("facility_type"),
                    pl.col(volume_col).cast(pl.Float64).alias("_quantity_b"),
                ),
                on=["id", "facility_type"],
                how="inner",
            )
            .filter(
                pl.col("id").is_not_null()
                & pl.col("facility_type").is_not_null()
                & pl.col("_quantity_a").is_not_null()
                & pl.col("_quantity_b").is_not_null()
            )
        )
        link_df = link_by_label.get(label)
        has_link_metadata = link_df is not None and {
            "id",
            "From_Node",
            "To_Node",
        }.issubset(link_df.columns)
        if has_link_metadata:
            link_metadata = (
                link_df.select(
                    pl.col("id").cast(pl.Int64, strict=False),
                    pl.col("From_Node"),
                    pl.col("To_Node"),
                )
                .drop_nulls("id")
                .unique("id")
            )
            joined = joined.join(link_metadata, on="id", how="left")

        joined = joined.sort(["_quantity_b", "id"], descending=[True, False]).head(
            top_n
        )
        metadata_columns: list[str] = []
        if has_link_metadata:
            for column in ("From_Node", "To_Node"):
                if joined.select(pl.col(column).is_not_null().any()).item():
                    metadata_columns.append(column)
        rows = []
        for row in joined.iter_rows(named=True):
            observed = float(row["_quantity_a"])
            modeled = float(row["_quantity_b"])
            difference = modeled - observed
            percent_difference = (
                "" if observed == 0.0 else f"{(difference / observed) * 100.0:.2f}%"
            )
            table_row = {
                "link_id": row["id"],
                "facility_type": row["facility_type"],
                quantity_a_column: observed,
                quantity_b_column: modeled,
                difference_column: difference,
                percent_difference_column: percent_difference,
            }
            for metadata_column in metadata_columns:
                table_row[metadata_column] = row.get(metadata_column)
            rows.append(table_row)
        columns = [
            "link_id",
            "facility_type",
            *metadata_columns,
            quantity_a_column,
            quantity_b_column,
            difference_column,
            percent_difference_column,
        ]
        table = pl.DataFrame(rows).select(columns) if rows else pl.DataFrame()
        if not table.is_empty():
            out.append((label, table))
    return out
