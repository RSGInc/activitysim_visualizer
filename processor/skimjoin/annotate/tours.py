from __future__ import annotations

import polars as pl

from processor.skimjoin.config.schema import NormalizedConfig


def aggregate_tours_from_trips(
    trips: pl.DataFrame,
    tours: pl.DataFrame,
    normalized: NormalizedConfig,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    tour_id_column = normalized.activitysim.tour_id_column
    if tour_id_column not in trips.columns:
        raise ValueError(f"Trips must include {tour_id_column!r} for tour aggregation.")
    if tour_id_column not in tours.columns:
        raise ValueError(f"Tours must include {tour_id_column!r} for tour aggregation.")

    aggregations = normalized.tour_aggregation.aggregations
    if not aggregations:
        skim_columns = [column for column in trips.columns if column.startswith("skim_")]
        aggregations = {column: "sum" for column in skim_columns}
    else:
        aggregations = {column: method for column, method in aggregations.items() if column in trips.columns}

    grouped = trips.group_by(tour_id_column).agg(
        [_aggregation_expr(column, method).alias(column) for column, method in aggregations.items()]
    )

    summary_rows: list[dict[str, object]] = []
    for column, method in aggregations.items():
        series = grouped.get_column(column)
        summary_rows.append(
            {
                "aggregation_column": column,
                "aggregation_function": method,
                "n_tours_with_values": int(series.drop_nulls().len()),
                "n_tours_missing_values": int(series.null_count()),
                "mean_value": float(series.mean()) if series.drop_nulls().len() else None,
                "min_value": float(series.min()) if series.drop_nulls().len() else None,
                "max_value": float(series.max()) if series.drop_nulls().len() else None,
            }
        )

    outbound_column = normalized.activitysim.outbound_column
    if outbound_column in trips.columns and normalized.tour_aggregation.directional_outputs.get("outbound"):
        outbound = trips.filter(pl.col(outbound_column)).group_by(tour_id_column).agg(
            [_aggregation_expr(column, method).alias(f"outbound_{column}") for column, method in aggregations.items()]
        )
        grouped = grouped.join(outbound, on=tour_id_column, how="left")
    if outbound_column in trips.columns and normalized.tour_aggregation.directional_outputs.get("inbound"):
        inbound = trips.filter(~pl.col(outbound_column)).group_by(tour_id_column).agg(
            [_aggregation_expr(column, method).alias(f"inbound_{column}") for column, method in aggregations.items()]
        )
        grouped = grouped.join(inbound, on=tour_id_column, how="left")

    return tours.join(grouped, on=tour_id_column, how="left"), pl.DataFrame(summary_rows)


def _aggregation_expr(column: str, method: str) -> pl.Expr:
    expr = pl.col(column)
    if method == "sum":
        return expr.sum()
    if method == "mean":
        return expr.mean()
    if method == "min":
        return expr.min()
    if method == "max":
        return expr.max()
    if method == "first":
        return expr.first()
    if method == "last":
        return expr.last()
    raise ValueError(f"Unsupported aggregation method: {method}")
