from __future__ import annotations

import re

import polars as pl

from processor.skimjoin.config.schema import NormalizedLookupRule

_PLACEHOLDER_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")


def _resolve_rule_work_items(
    rule: NormalizedLookupRule,
    subset: pl.DataFrame,
    *,
    include_errors: bool = True,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    work = _base_rule_work_frame(rule, subset)
    missing_reason_expr = pl.lit(None, dtype=pl.String)

    for dimension_name in rule.dimensions_used:
        dimension = rule.dimensions[dimension_name]
        token_column = f"__token_{dimension_name}"
        work = _attach_dimension_token(
            work,
            dimension.resolved_source_column,
            dimension.values,
            token_column,
        )
        missing_reason_expr = (
            pl.when(pl.col(token_column).is_null() & missing_reason_expr.is_null())
            .then(pl.lit(f"missing_dimension_value:{dimension_name}"))
            .otherwise(missing_reason_expr)
        )

    work = work.with_columns(missing_reason_expr.alias("__missing_reason"))
    work = work.with_columns(
        _matrix_name_expr(rule.matrix, rule.dimensions_used).alias("matrix_name")
    )

    errors = (
        work.filter(pl.col("__missing_reason").is_not_null()).select(
            pl.col("_row_id").cast(pl.Int64),
            pl.col("rule_name"),
            pl.col("trip_id"),
            pl.col("lookup_origin").cast(pl.Int64, strict=False).alias("origin"),
            pl.col("lookup_destination")
            .cast(pl.Int64, strict=False)
            .alias("destination"),
            pl.lit(None, dtype=pl.String).alias("matrix_name"),
            pl.col("__missing_reason").alias("reason"),
        )
        if include_errors
        else pl.DataFrame()
    )

    valid = work.filter(pl.col("__missing_reason").is_null()).select(
        "_row_id",
        "trip_id",
        "rule_name",
        "mode",
        "component",
        "output",
        "combine_method",
        "lookup_chain_id",
        "lookup_step_index",
        "lookup_role",
        "lookup_origin",
        "lookup_destination",
        "matrix_name",
    )
    return valid, errors


def _base_rule_work_frame(
    rule: NormalizedLookupRule, subset: pl.DataFrame
) -> pl.DataFrame:
    added_names = {
        "_row_id",
        "rule_name",
        "mode",
        "component",
        "output",
        "combine_method",
        "lookup_chain_id",
        "lookup_step_index",
        "lookup_role",
        "lookup_origin",
        "trip_id",
    }
    select_exprs: list[pl.Expr] = [
        pl.col("_row_id").cast(pl.Int64),
        pl.lit(rule.name).alias("rule_name"),
        pl.lit(rule.mode).alias("mode"),
        pl.lit(rule.component).alias("component"),
        pl.lit(rule.output).alias("output"),
        pl.lit(rule.combine_method).alias("combine_method"),
        pl.lit(rule.lookup_chain_id).alias("lookup_chain_id"),
        pl.lit(rule.lookup_step_index).cast(pl.Int64).alias("lookup_step_index"),
        pl.lit(rule.lookup_role).alias("lookup_role"),
        pl.col(_rule_origin_column(rule)).cast(pl.Float64).alias("lookup_origin"),
    ]
    if "trip_id" in subset.columns:
        select_exprs.append(pl.col("trip_id").cast(pl.Int64, strict=False))
    else:
        select_exprs.append(pl.col("_row_id").cast(pl.Int64).alias("trip_id"))

    destination_column = _rule_destination_column(rule)
    if destination_column is not None:
        select_exprs.append(
            pl.col(destination_column).cast(pl.Float64).alias("lookup_destination")
        )
        added_names.add("lookup_destination")
    else:
        select_exprs.append(pl.lit(None, dtype=pl.Float64).alias("lookup_destination"))
        added_names.add("lookup_destination")

    for dimension_name in rule.dimensions_used:
        source_column = rule.dimensions[dimension_name].resolved_source_column
        if source_column not in added_names:
            select_exprs.append(pl.col(source_column))
            added_names.add(source_column)

    return subset.select(select_exprs)


def _attach_dimension_token(
    work: pl.DataFrame,
    source_column: str,
    values: dict[str, str],
    token_column: str,
) -> pl.DataFrame:
    if not values:
        return work.with_columns(
            pl.when(pl.col(source_column).is_null())
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col(source_column).cast(pl.Utf8))
            .alias(token_column)
        )

    mapping = pl.DataFrame(
        {
            "__dimension_key": list(values.keys()),
            token_column: list(values.values()),
        },
        schema={"__dimension_key": pl.String, token_column: pl.String},
    )
    return (
        work.with_columns(pl.col(source_column).cast(pl.Utf8).alias("__dimension_key"))
        .join(mapping, on="__dimension_key", how="left")
        .drop("__dimension_key")
    )


def _matrix_name_expr(matrix_template: str, dimensions_used: list[str]) -> pl.Expr:
    if not dimensions_used:
        return pl.lit(matrix_template)

    parts: list[pl.Expr] = []
    last = 0
    for match in _PLACEHOLDER_RE.finditer(matrix_template):
        if match.start() > last:
            parts.append(pl.lit(matrix_template[last : match.start()]))
        parts.append(pl.col(f"__token_{match.group(1)}"))
        last = match.end()
    if last < len(matrix_template):
        parts.append(pl.lit(matrix_template[last:]))
    return pl.concat_str(parts, separator="")


def _rule_origin_column(rule: NormalizedLookupRule) -> str:
    return (
        rule.key_column
        if rule.lookup == "key" and rule.key_column is not None
        else rule.origin
    )


def _rule_destination_column(rule: NormalizedLookupRule) -> str | None:
    if rule.lookup == "key":
        return None
    return rule.destination
