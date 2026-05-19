"""Runtime adapter for optional late-prepare skim enrichment."""

from __future__ import annotations

from activitysim_viz_logging import get_logger
import polars as pl

from processor.models import RunData, SkimjoinArtifacts
from processor.skimjoin.annotate.tours import aggregate_tours_from_trips
from processor.skimjoin.annotate.trips import annotate_trips
from processor.skimjoin.runtime_execution import _run_integrated_skimjoin
from processor.skimjoin.runtime_reports import (
    _empty_failure_report,
    _empty_fallback_lookup_report,
    _empty_lookup_summary,
    _empty_missing_lookup_report,
    _empty_skipped_rule_report,
    _empty_tour_aggregation_summary,
    _failure_report,
    _skimjoin_manifest,
    _skipped_rule_report,
)
from runtime.config import Config

LOGGER = get_logger("processor.skimjoin")


def apply_skimjoin(rd: RunData, config: Config) -> RunData:
    """Apply optional skim enrichment to prepared trips and tours."""
    if not config.skimjoin.enabled:
        return _package_disabled_skimjoin(rd)

    LOGGER.info("[skimjoin] Starting late-prepare skim enrichment for '%s'", rd.label)
    normalized = config.skimjoin.normalized_config
    try:
        if normalized is None:
            raise ValueError(
                "Skimjoin is enabled, but no normalized skimjoin config is loaded."
            )
        result = _run_integrated_skimjoin(
            rd=rd,
            normalized=normalized,
            annotate_trips_fn=annotate_trips,
            aggregate_tours_from_trips_fn=aggregate_tours_from_trips,
        )
    except Exception as exc:
        return _package_failed_skimjoin(rd, config, exc)
    return _package_applied_skimjoin(rd, config, result)


def _package_disabled_skimjoin(rd: RunData) -> RunData:
    manifest = _skimjoin_manifest(
        enabled=False,
        status="disabled",
        config_digest=None,
    )
    reports: dict[str, pl.DataFrame] = {}
    rd.skimjoin_artifacts = SkimjoinArtifacts(
        manifest=dict(manifest),
        reports=dict(reports),
    )
    rd.skimjoin_manifest = dict(manifest)
    rd.skimjoin_reports = dict(reports)
    return rd


def _package_failed_skimjoin(rd: RunData, config: Config, exc: Exception) -> RunData:
    failure_detail = f"{type(exc).__name__}: {exc}"
    manifest = _skimjoin_manifest(
        enabled=True,
        status="failed",
        config_digest=config.skimjoin.config_digest,
        fallback_count=0,
        fallback_outputs=[],
        failure_detail=failure_detail,
    )
    reports = {
        "skim_lookup_summary": _empty_lookup_summary(),
        "missing_lookup_report": _empty_missing_lookup_report(),
        "fallback_lookup_report": _empty_fallback_lookup_report(),
        "skipped_rule_report": _empty_skipped_rule_report(),
        "tour_aggregation_summary": _empty_tour_aggregation_summary(),
        "failure_report": _failure_report("integrated_skimjoin", exc),
    }
    rd.skimjoin_artifacts = SkimjoinArtifacts(
        manifest=dict(manifest),
        reports=dict(reports),
    )
    rd.skimjoin_manifest = dict(manifest)
    rd.skimjoin_reports = dict(reports)
    LOGGER.warning(
        "[skimjoin] Skipping skim enrichment for '%s' after failure: %s",
        rd.label,
        failure_detail,
    )
    return rd


def _package_applied_skimjoin(rd: RunData, config: Config, result: object) -> RunData:
    skipped_rules = _skipped_rule_report(result.missing_lookup_report)
    applied_outputs = _applied_output_columns(
        result.annotated_trips,
        result.enriched_tours,
    )
    fallback_outputs = (
        sorted(
            set(
                result.fallback_lookup_report.filter(pl.col("fallback_succeeded"))[
                    "output"
                ].drop_nulls().to_list()
            )
        )
        if not result.fallback_lookup_report.is_empty()
        else []
    )
    status = "applied" if applied_outputs else "no_outputs"

    rd.trips = result.annotated_trips
    rd.tours = result.enriched_tours
    manifest = _skimjoin_manifest(
        enabled=True,
        status=status,
        config_digest=config.skimjoin.config_digest,
        applied_outputs=applied_outputs,
        skipped_rules=skipped_rules.to_dicts(),
        warning_count=int(result.missing_lookup_report.height),
        fallback_count=int(result.fallback_lookup_report.height),
        fallback_outputs=fallback_outputs,
    )
    reports = {
        "skim_lookup_summary": result.lookup_summary,
        "missing_lookup_report": result.missing_lookup_report,
        "fallback_lookup_report": result.fallback_lookup_report,
        "skipped_rule_report": skipped_rules,
        "tour_aggregation_summary": result.tour_aggregation_summary,
        "failure_report": _empty_failure_report(),
    }
    rd.skimjoin_artifacts = SkimjoinArtifacts(
        manifest=dict(manifest),
        reports=dict(reports),
    )
    rd.skimjoin_manifest = dict(manifest)
    rd.skimjoin_reports = dict(reports)
    LOGGER.info(
        "[skimjoin] Completed skim enrichment for '%s' with status=%s, outputs=%s",
        rd.label,
        status,
        len(applied_outputs),
    )
    return rd


def _applied_output_columns(
    annotated_trips: pl.DataFrame,
    enriched_tours: pl.DataFrame,
) -> list[str]:
    return sorted(
        {
            column
            for column in [*annotated_trips.columns, *enriched_tours.columns]
            if "skim_" in column
        }
    )
