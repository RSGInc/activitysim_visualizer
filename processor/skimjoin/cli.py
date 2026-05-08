from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import polars as pl

from processor.skimjoin.activitysim_scan import (
    load_table,
    scan_activitysim_tables,
    summarize_table_columns,
)
from processor.skimjoin.annotate.tours import aggregate_tours_from_trips
from processor.skimjoin.annotate.trips import annotate_trips
from processor.skimjoin.config.io import load_config_file
from processor.skimjoin.config.normalize import normalize_config
from processor.skimjoin.config.validation import (
    ConfigValidationError,
    ValidationArtifacts,
    load_config,
    validate_config,
)
from processor.skimjoin.inventory import inventory_skim_files
from processor.skimjoin.reports.qa import (
    write_normalized_config,
    write_table,
    write_validation_failure_report,
    write_validation_report,
)


LOGGER = logging.getLogger("skimjoin.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skimjoin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--config", required=True)
    inventory_parser.add_argument("--preview", action="store_true")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--config", required=True)

    annotate_parser = subparsers.add_parser("annotate-trips")
    annotate_parser.add_argument("--config", required=True)
    annotate_parser.add_argument("--out")
    annotate_parser.add_argument("--preview", action="store_true")

    aggregate_parser = subparsers.add_parser("aggregate-tours")
    aggregate_parser.add_argument("--config", required=True)
    aggregate_parser.add_argument("--trips")
    aggregate_parser.add_argument("--out")
    aggregate_parser.add_argument("--preview", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--out-trips")
    run_parser.add_argument("--out-tours")
    run_parser.add_argument("--preview", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config).resolve()
    config_data = _load_yaml(config_path)

    if args.command == "inventory":
        skim_files, output_dir = _inventory_inputs_from_config(parser, config_data, "inventory")
        trips_path, tours_path = _inventory_table_paths_from_config(config_data)
        _configure_inventory_logging(output_dir / "inventory_debug.log")
        _log_inventory_debug(
            config_path=config_path,
            skim_files=skim_files,
            output_dir=output_dir,
            trips_path=trips_path,
            tours_path=tours_path,
        )
        inventory = inventory_skim_files(skim_files)
        output_path = output_dir / "skim_inventory.csv"
        _log(f"Inventory resolved {inventory.select(pl.col('file_path').n_unique()).item()} skim file(s)")
        _log(f"Inventory found {inventory.height} matrix record(s)")
        _log(f"Writing inventory CSV to: {output_path}")
        _write_dataframe(output_path, inventory)
        if args.preview:
            _write_activitysim_inventory_outputs(output_dir, trips_path=trips_path, tours_path=tours_path)
        _log(f"Inventory write complete: {output_path}")
        print(output_path)
        return 0

    if args.command == "validate":
        qa_dir = _report_dir_from_raw_config(config_data, config_path)
        try:
            artifacts = _validate_from_config_data(config_data, config_path)
        except ConfigValidationError as exc:
            normalized = _safe_normalize(config_data)
            if normalized is not None:
                write_normalized_config(qa_dir / "config_normalized.yaml", normalized)
            write_validation_failure_report(qa_dir / "validation_report.txt", str(exc), normalized=normalized)
            return 1
        default_output_dir = _default_output_dir(artifacts, config_path)
        _write_validation_artifacts(artifacts, default_output_dir or qa_dir)
        return 0

    artifacts = _validate_from_config_data(config_data, config_path, strict=False)
    default_output_dir = _default_output_dir(artifacts, config_path)

    if args.command == "annotate-trips":
        out_path = _resolve_output_path(
            parser,
            args.out,
            default_output_dir,
            "trips_with_skims.parquet",
            "annotate-trips",
        )
        annotated, lookup_summary, missing = annotate_trips(
            load_table(artifacts.config.activitysim.trips_table),
            artifacts.normalized,
            artifacts.inventory,
        )
        _write_dataframe(out_path, annotated)
        qa_dir = out_path.parent
        _write_validation_artifacts(artifacts, qa_dir)
        write_table(qa_dir / "skim_lookup_summary.csv", lookup_summary)
        write_table(qa_dir / "missing_lookup_report.csv", missing)
        if args.preview:
            _write_table_preview(qa_dir / "annotated_trips_columns.csv", annotated, table_name="annotated_trips")
        return 0

    if args.command == "aggregate-tours":
        out_path = _resolve_output_path(
            parser,
            args.out,
            default_output_dir,
            "tours_with_skims.parquet",
            "aggregate-tours",
        )
        trips_path = _resolve_existing_input_path(
            parser,
            args.trips,
            default_output_dir / "trips_with_skims.parquet" if default_output_dir is not None else None,
            "aggregate-tours",
            "trips",
        )
        trips = load_table(trips_path)
        tours = load_table(artifacts.config.activitysim.tours_table)
        aggregated, summary = aggregate_tours_from_trips(trips, tours, artifacts.normalized)
        _write_dataframe(out_path, aggregated)
        write_table(out_path.parent / "tour_aggregation_summary.csv", summary)
        if args.preview:
            _write_table_preview(out_path.parent / "aggregated_tours_columns.csv", aggregated, table_name="aggregated_tours")
        return 0

    if args.command == "run":
        out_trips = _resolve_output_path(
            parser,
            args.out_trips,
            default_output_dir,
            "trips_with_skims.parquet",
            "run",
        )
        out_tours = _resolve_output_path(
            parser,
            args.out_tours,
            default_output_dir,
            "tours_with_skims.parquet",
            "run",
        )
        trips = load_table(artifacts.config.activitysim.trips_table)
        tours = load_table(artifacts.config.activitysim.tours_table)
        annotated, lookup_summary, missing = annotate_trips(trips, artifacts.normalized, artifacts.inventory)
        _write_dataframe(out_trips, annotated)
        aggregated, summary = aggregate_tours_from_trips(annotated, tours, artifacts.normalized)
        _write_dataframe(out_tours, aggregated)
        qa_dir = out_trips.parent
        _write_validation_artifacts(artifacts, qa_dir)
        write_table(qa_dir / "skim_lookup_summary.csv", lookup_summary)
        write_table(qa_dir / "missing_lookup_report.csv", missing)
        write_table(qa_dir / "tour_aggregation_summary.csv", summary)
        if args.preview:
            _write_table_preview(qa_dir / "annotated_trips_columns.csv", annotated, table_name="annotated_trips")
            _write_table_preview(qa_dir / "aggregated_tours_columns.csv", aggregated, table_name="aggregated_tours")
        return 0

    return 0


def _load_yaml(path: Path) -> dict[str, Any]:
    return load_config_file(path)


def _validate_from_config_data(
    config_data: dict[str, Any],
    config_path: Path,
    *,
    strict: bool = True,
) -> ValidationArtifacts:
    skim_files = config_data.get("skim_files")
    if skim_files is None:
        skim_files = (config_data.get("project") or {}).get("skim_files", [])
    activitysim = dict(config_data.get("activitysim") or {})
    project = dict(config_data.get("project") or {})
    trips_path = activitysim.get("trips_table", project.get("trips_table"))
    tours_path = activitysim.get("tours_table", project.get("tours_table"))
    inventory = inventory_skim_files(skim_files)
    trips = load_table(trips_path)
    tours = load_table(tours_path) if tours_path else None
    return validate_config(config_data, inventory, trips, tours=tours, strict=strict)


def _inventory_inputs_from_config(
    parser: argparse.ArgumentParser,
    config_data: dict[str, Any],
    command: str,
) -> tuple[list[str], Path]:
    project = dict(config_data.get("project") or {})
    skim_files = project.get("skim_files")
    output_dir = project.get("output_dir")
    if not skim_files:
        parser.error(f"{command} requires project.skim_files in the config file.")
    if output_dir is None:
        parser.error(f"{command} requires project.output_dir in the config file.")
    return list(skim_files), Path(output_dir).resolve()


def _log(message: str) -> None:
    LOGGER.info(message)


def _configure_inventory_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = LOGGER
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)


def _log_inventory_debug(
    *,
    config_path: Path,
    skim_files: list[str],
    output_dir: Path,
    trips_path: Path | None,
    tours_path: Path | None,
) -> None:
    _log(f"Inventory config: {config_path}")
    _log(f"Inventory output dir: {output_dir}")
    _log("Inventory skim file inputs:")
    for skim_file in skim_files:
        _log(f"  - {skim_file}")
    _log(f"Inventory trips table: {trips_path if trips_path is not None else 'not provided'}")
    _log(f"Inventory tours table: {tours_path if tours_path is not None else 'not provided'}")


def _inventory_table_paths_from_config(config_data: dict[str, Any]) -> tuple[Path | None, Path | None]:
    project = dict(config_data.get("project") or {})
    activitysim = dict(config_data.get("activitysim") or {})
    trips_path = activitysim.get("trips_table", project.get("trips_table"))
    tours_path = activitysim.get("tours_table", project.get("tours_table"))
    return (_optional_path(trips_path), _optional_path(tours_path))


def _optional_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).resolve()


def _write_activitysim_inventory_outputs(
    output_dir: Path,
    *,
    trips_path: Path | None,
    tours_path: Path | None,
) -> None:
    trips = None
    tours = None
    if trips_path is not None:
        _log(f"Loading trips table for inventory: {trips_path}")
        trips = load_table(trips_path)
        _log(f"Trips table has {trips.height} row(s) and {len(trips.columns)} column(s)")
    if tours_path is not None:
        _log(f"Loading tours table for inventory: {tours_path}")
        tours = load_table(tours_path)
        _log(f"Tours table has {tours.height} row(s) and {len(tours.columns)} column(s)")
    if trips is None:
        return

    value_rows, column_rows = scan_activitysim_tables(trips, tours=tours)
    write_table(output_dir / "trips_columns.csv", column_rows.filter(pl.col("table") == "trips").drop("table"))
    if tours is not None:
        write_table(output_dir / "tours_columns.csv", column_rows.filter(pl.col("table") == "tours").drop("table"))
    if not value_rows.is_empty():
        write_table(output_dir / "activitysim_value_counts.csv", value_rows)


def _write_table_preview(path: Path, table: pl.DataFrame, *, table_name: str) -> None:
    write_table(path, summarize_table_columns(table, table_name=table_name).drop("table"))


def _default_output_dir(artifacts: ValidationArtifacts, config_path: Path) -> Path | None:
    project = artifacts.config.project
    if project is None or project.output_dir is None:
        return None
    return Path(project.output_dir).resolve()


def _report_dir_from_raw_config(config_data: dict[str, Any], config_path: Path) -> Path:
    project = dict(config_data.get("project") or {})
    output_dir = project.get("output_dir")
    if output_dir is None:
        return config_path.parent
    return Path(output_dir).resolve()


def _safe_normalize(config_data: dict[str, Any]):
    try:
        config = load_config(config_data)
        return normalize_config(config)
    except Exception:
        return None


def _resolve_output_path(
    parser: argparse.ArgumentParser,
    explicit: str | None,
    default_output_dir: Path | None,
    default_filename: str,
    command: str,
) -> Path:
    if explicit:
        return Path(explicit).resolve()
    if default_output_dir is not None:
        return (default_output_dir / default_filename).resolve()
    parser.error(f"{command} requires an explicit output flag or project.output_dir in the config file.")
    raise AssertionError("unreachable")


def _resolve_existing_input_path(
    parser: argparse.ArgumentParser,
    explicit: str | None,
    default_path: Path | None,
    command: str,
    label: str,
) -> Path:
    if explicit:
        return Path(explicit).resolve()
    if default_path is not None:
        return default_path.resolve()
    parser.error(f"{command} requires --{label} or project.output_dir in the config file.")
    raise AssertionError("unreachable")


def _write_validation_artifacts(artifacts: ValidationArtifacts, qa_dir: Path) -> None:
    write_normalized_config(qa_dir / "config_normalized.yaml", artifacts.normalized)
    write_validation_report(qa_dir / "validation_report.txt", artifacts.normalized)


def _write_dataframe(path: Path, df: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        df.write_parquet(path)
        return
    if path.suffix.lower() == ".csv":
        df.write_csv(path)
        return
    raise ValueError(f"Unsupported output format: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
