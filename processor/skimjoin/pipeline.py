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
        rd.skimjoin_manifest = {
            "skimjoin_enabled": False,
            "skimjoin_status": "disabled",
            "skimjoin_config_digest": None,
            "skimjoin_applied_outputs": [],
            "skimjoin_skipped_rules": [],
            "skimjoin_warning_count": 0,
        }
        rd.skimjoin_reports = {}
        return rd

    normalized = config.skimjoin.normalized_config
    if normalized is None:
        raise ValueError("Skimjoin is enabled, but no normalized skimjoin config is loaded.")

    LOGGER.info("[skimjoin] Starting late-prepare skim enrichment for '%s'", rd.label)
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
    rd.skimjoin_manifest = {
        "skimjoin_enabled": True,
        "skimjoin_status": status,
        "skimjoin_config_digest": config.skimjoin.config_digest,
        "skimjoin_applied_outputs": applied_outputs,
        "skimjoin_skipped_rules": skipped_rules.to_dicts(),
        "skimjoin_warning_count": int(missing.height),
    }
    rd.skimjoin_reports = {
        "skim_lookup_summary": lookup_summary,
        "missing_lookup_report": missing,
        "skipped_rule_report": skipped_rules,
        "tour_aggregation_summary": tour_summary,
    }
    LOGGER.info(
        "[skimjoin] Completed skim enrichment for '%s' with status=%s, outputs=%s",
        rd.label,
        status,
        len(applied_outputs),
    )
    return rd


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
        return pl.DataFrame(
            schema={
                "rule_name": pl.String,
                "reason": pl.String,
                "n_rows": pl.Int64,
            }
        )

    skip_rows = missing.filter(
        pl.col("reason").cast(pl.Utf8).str.starts_with("missing_trip_column:")
        | pl.col("reason").cast(pl.Utf8).str.starts_with("missing_mode_column:")
    )
    if skip_rows.is_empty():
        return pl.DataFrame(
            schema={
                "rule_name": pl.String,
                "reason": pl.String,
                "n_rows": pl.Int64,
            }
        )

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
