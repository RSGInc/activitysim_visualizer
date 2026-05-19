"""Manifest and report packaging helpers for integrated skimjoin."""

from __future__ import annotations

import re

import polars as pl


_DIRECTION_SUFFIX_RE = re.compile(r"\.(outbound|inbound)$")
_FALLBACK_SUFFIX_RE = re.compile(r"\.fallback_\d+$")


def _skimjoin_manifest(
    *,
    enabled: bool,
    status: str,
    config_digest: str | None,
    applied_outputs: list[str] | None = None,
    skipped_rules: list[dict[str, object]] | None = None,
    warning_count: int = 0,
    fallback_count: int = 0,
    fallback_outputs: list[str] | None = None,
    failure_detail: str | None = None,
) -> dict[str, object]:
    return {
        "skimjoin_enabled": enabled,
        "skimjoin_status": status,
        "skimjoin_config_digest": config_digest,
        "skimjoin_applied_outputs": list(applied_outputs or []),
        "skimjoin_skipped_rules": list(skipped_rules or []),
        "skimjoin_warning_count": int(warning_count),
        "skimjoin_fallback_count": int(fallback_count),
        "skimjoin_fallback_outputs": list(fallback_outputs or []),
        "skimjoin_failure_detail": failure_detail,
    }


def _empty_lookup_summary() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "rule_name": pl.String,
            "mode": pl.String,
            "component": pl.String,
            "output": pl.String,
            "matrix_name": pl.String,
            "n_trips": pl.Int64,
            "origin_column": pl.String,
            "destination_column": pl.String,
            "mean_value": pl.Float64,
            "min_value": pl.Float64,
            "max_value": pl.Float64,
            "n_missing": pl.Int64,
        }
    )


def _empty_missing_lookup_report() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "rule_name": pl.String,
            "trip_id": pl.Int64,
            "origin": pl.Int64,
            "destination": pl.Int64,
            "matrix_name": pl.String,
            "reason": pl.String,
        }
    )


def _empty_skipped_rule_report() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "rule_name": pl.String,
            "reason": pl.String,
            "n_rows": pl.Int64,
        }
    )


def _empty_fallback_lookup_report() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "table_name": pl.String,
            "rule_name": pl.String,
            "output": pl.String,
            "logical_id": pl.Int64,
            "direction": pl.String,
            "primary_matrix_name": pl.String,
            "fallback_matrix_name": pl.String,
            "fallback_step_index": pl.Int64,
            "fallback_reason": pl.String,
            "fallback_eligible": pl.Boolean,
            "fallback_attempted": pl.Boolean,
            "fallback_succeeded": pl.Boolean,
            "fallback_exhausted": pl.Boolean,
        }
    )


def _empty_tour_aggregation_summary() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "aggregation_column": pl.String,
            "aggregation_function": pl.String,
            "n_tours_with_values": pl.Int64,
            "n_tours_missing_values": pl.Int64,
            "mean_value": pl.Float64,
            "min_value": pl.Float64,
            "max_value": pl.Float64,
        }
    )


def _empty_failure_report() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "stage": pl.String,
            "error_type": pl.String,
            "detail": pl.String,
        }
    )


def _failure_report(stage: str, exc: Exception) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "stage": stage,
                "error_type": type(exc).__name__,
                "detail": str(exc),
            }
        ],
        schema=_empty_failure_report().schema,
    )


def _skipped_rule_report(missing: pl.DataFrame) -> pl.DataFrame:
    if missing.is_empty() or "reason" not in missing.columns:
        return _empty_skipped_rule_report()

    skip_rows = missing.filter(
        pl.col("reason").cast(pl.Utf8).str.starts_with("missing_trip_column:")
        | pl.col("reason").cast(pl.Utf8).str.starts_with("missing_mode_column:")
    )
    if skip_rows.is_empty():
        return _empty_skipped_rule_report()

    return (
        skip_rows.with_columns(
            pl.col("rule_name")
            .cast(pl.Utf8)
            .map_elements(_canonical_rule_name, return_dtype=pl.String)
            .alias("rule_name")
        )
        .group_by(["rule_name", "reason"])
        .agg(n_rows=pl.len())
        .with_columns(
            pl.col("rule_name").cast(pl.String),
            pl.col("reason").cast(pl.String),
            pl.col("n_rows").cast(pl.Int64),
        )
        .sort(["rule_name", "reason"])
    )


def _canonical_rule_name(rule_name: str | None) -> str | None:
    if rule_name is None:
        return None
    canonical = _DIRECTION_SUFFIX_RE.sub("", rule_name)
    canonical = _FALLBACK_SUFFIX_RE.sub("", canonical)
    return canonical
