"""Runtime adapter for optional late-prepare skim enrichment."""

from __future__ import annotations

from collections import Counter

from activitysim_viz_logging import get_logger
import polars as pl

from processor.models import RunData
from processor.skimjoin.annotate.tours import aggregate_tours_from_trips
from processor.skimjoin.annotate.trips import annotate_trips
from processor.skimjoin.inventory import inventory_skim_files
from processor.skimjoin.skimstore.omx import OmxSkimStore
from runtime.config import Config

LOGGER = get_logger("processor.skimjoin")


def apply_skimjoin(rd: RunData, config: Config) -> RunData:
    """Apply optional skim enrichment to prepared trips and tours."""
    if not config.skimjoin.enabled:
        rd.skimjoin_manifest = _skimjoin_manifest(
            enabled=False,
            status="disabled",
            config_digest=None,
        )
        rd.skimjoin_reports = {}
        return rd

    LOGGER.info("[skimjoin] Starting late-prepare skim enrichment for '%s'", rd.label)
    normalized = config.skimjoin.normalized_config
    try:
        if normalized is None:
            raise ValueError(
                "Skimjoin is enabled, but no normalized skimjoin config is loaded."
            )

        inventory = inventory_skim_files(normalized.skim_files)
        _validate_runtime_inventory(inventory)

        annotated_trips, lookup_summary, missing = annotate_trips(
            rd.trips,
            normalized,
            inventory,
            skim_store=OmxSkimStore(),
        )
        enriched_tours, tour_summary = aggregate_tours_from_trips(
            annotated_trips,
            rd.tours,
            normalized,
        )
    except Exception as exc:
        failure_detail = f"{type(exc).__name__}: {exc}"
        rd.skimjoin_manifest = _skimjoin_manifest(
            enabled=True,
            status="failed",
            config_digest=config.skimjoin.config_digest,
            failure_detail=failure_detail,
        )
        rd.skimjoin_reports = {
            "skim_lookup_summary": _empty_lookup_summary(),
            "missing_lookup_report": _empty_missing_lookup_report(),
            "skipped_rule_report": _empty_skipped_rule_report(),
            "tour_aggregation_summary": _empty_tour_aggregation_summary(),
            "failure_report": _failure_report("integrated_skimjoin", exc),
        }
        LOGGER.warning(
            "[skimjoin] Skipping skim enrichment for '%s' after failure: %s",
            rd.label,
            failure_detail,
        )
        return rd

    skipped_rules = _skipped_rule_report(missing)
    applied_outputs = sorted(
        {
            column
            for column in [*annotated_trips.columns, *enriched_tours.columns]
            if "skim_" in column
        }
    )
    status = "applied" if applied_outputs else "no_outputs"

    rd.trips = annotated_trips
    rd.tours = enriched_tours
    rd.skimjoin_manifest = _skimjoin_manifest(
        enabled=True,
        status=status,
        config_digest=config.skimjoin.config_digest,
        applied_outputs=applied_outputs,
        skipped_rules=skipped_rules.to_dicts(),
        warning_count=int(missing.height),
    )
    rd.skimjoin_reports = {
        "skim_lookup_summary": lookup_summary,
        "missing_lookup_report": missing,
        "skipped_rule_report": skipped_rules,
        "tour_aggregation_summary": tour_summary,
        "failure_report": _empty_failure_report(),
    }
    LOGGER.info(
        "[skimjoin] Completed skim enrichment for '%s' with status=%s, outputs=%s",
        rd.label,
        status,
        len(applied_outputs),
    )
    return rd


def _skimjoin_manifest(
    *,
    enabled: bool,
    status: str,
    config_digest: str | None,
    applied_outputs: list[str] | None = None,
    skipped_rules: list[dict[str, object]] | None = None,
    warning_count: int = 0,
    failure_detail: str | None = None,
) -> dict[str, object]:
    return {
        "skimjoin_enabled": enabled,
        "skimjoin_status": status,
        "skimjoin_config_digest": config_digest,
        "skimjoin_applied_outputs": list(applied_outputs or []),
        "skimjoin_skipped_rules": list(skipped_rules or []),
        "skimjoin_warning_count": int(warning_count),
        "skimjoin_failure_detail": failure_detail,
    }


def _validate_runtime_inventory(inventory: pl.DataFrame) -> None:
    if inventory.is_empty():
        raise ValueError("Integrated skimjoin could not resolve any OMX skim matrices.")

    suffixes = {
        str(path).lower().rsplit(".", 1)[-1]
        for path in inventory.get_column("file_path").unique().to_list()
    }
    if suffixes != {"omx"}:
        raise ValueError(
            "Integrated skimjoin currently supports OMX skim inputs only."
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
            "Integrated skimjoin requires unique matrix names across OMX inputs. "
            + "Duplicate names: "
            + ", ".join(repr(name) for name in duplicates)
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
        skip_rows.group_by(["rule_name", "reason"])
        .agg(n_rows=pl.len())
        .with_columns(
            pl.col("rule_name").cast(pl.String),
            pl.col("reason").cast(pl.String),
            pl.col("n_rows").cast(pl.Int64),
        )
        .sort(["rule_name", "reason"])
    )


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
