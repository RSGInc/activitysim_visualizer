"""Compare Tour Time summaries for two runs from a visualizer config.

This script rebuilds the prepared tour tables and the weighted
``tour_time_of_day_by_tour_purpose`` summary for two runs, then prints a
compact mismatch report. It uses the same prepare and summary code paths as
the dashboard, so it helps distinguish underlying data differences from page
rendering issues.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.config import Config
import runtime.workflows as runtime_workflows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose Tour Time differences between two runs."
    )
    parser.add_argument(
        "--config",
        "-c",
        default="configs/will_config.yaml",
        help="Path to the visualizer config file.",
    )
    parser.add_argument(
        "--run-a",
        default=None,
        help="Label of the first run to compare. Defaults to the first config run.",
    )
    parser.add_argument(
        "--run-b",
        default=None,
        help="Label of the second run to compare. Defaults to the second config run.",
    )
    return parser.parse_args()


def _resolve_run_pair(
    config: Config,
    label_a: str | None,
    label_b: str | None,
) -> tuple[dict, dict]:
    runs = list(config.runs)
    if len(runs) < 2:
        raise ValueError("Config must define at least two runs.")

    if label_a is None and label_b is None:
        return runs[0], runs[1]

    runs_by_label = {str(run["label"]): run for run in runs}
    if label_a is None or label_b is None:
        raise ValueError("Provide both --run-a and --run-b, or neither.")
    if label_a not in runs_by_label:
        raise ValueError(f"Run label not found: {label_a!r}")
    if label_b not in runs_by_label:
        raise ValueError(f"Run label not found: {label_b!r}")
    return runs_by_label[label_a], runs_by_label[label_b]


def _prepare_run(run_entry: dict, config: Config):
    logging.disable(logging.CRITICAL)
    result = runtime_workflows.run_summary_workflow(
        config=config,
        cache_root=REPO_ROOT / "tmp_diag_summary",
        prepared_root=REPO_ROOT / "tmp_diag_prepared",
        run_entries=[run_entry],
        prefer_cache=False,
        prepared_prefer_cache=False,
        write_cache=False,
        existing_result=None,
    )
    _, prepared = next(iter(result.prepared_runs_by_key.values()))
    summary = result.summary_runs[0].summaries_by_mode["weighted"][
        "tour_time_of_day_by_tour_purpose"
    ]
    return prepared, summary


def _read_raw_tours(run_entry: dict, config: Config) -> pl.DataFrame:
    run_dir = Path(run_entry["dir"])
    configured = str(config.files["tours"])
    path = Path(configured)
    suffix = path.suffix.lower()
    stem = path.stem if suffix in (".csv", ".parquet") else path.name
    if suffix == ".parquet":
        return pl.read_parquet(run_dir / path)
    if suffix == ".csv":
        return pl.read_csv(run_dir / path, infer_schema_length=0)
    parquet_path = run_dir / f"{stem}.parquet"
    csv_path = run_dir / f"{stem}.csv"
    if parquet_path.exists():
        return pl.read_parquet(parquet_path)
    if csv_path.exists():
        return pl.read_csv(csv_path, infer_schema_length=0)
    raise FileNotFoundError(f"Could not find raw tours file for {run_entry['label']!r}")


def _resolve_first_present(df: pl.DataFrame, candidates: list[str]) -> str:
    for column in candidates:
        if column in df.columns:
            return column
    raise ValueError(f"None of these columns were found: {candidates}")


def _resolve_preferred_purpose_column(df: pl.DataFrame, candidates: list[str]) -> str:
    present = [column for column in candidates if column in df.columns]
    if not present:
        raise ValueError(f"None of these columns were found: {candidates}")
    for column in present:
        if column == "primary_purpose":
            return column
    for column in present:
        series = df[column].drop_nulls().head(20).cast(pl.Utf8, strict=False)
        if series.len() == 0:
            continue
        values = [str(v).strip() for v in series.to_list()]
        if any(not value.lstrip("-").isdigit() for value in values):
            return column
    return present[0]


def _raw_tour_comparison(
    raw_a: pl.DataFrame,
    raw_b: pl.DataFrame,
    config: Config,
) -> pl.DataFrame:
    tour_id_a = _resolve_first_present(raw_a, list(config.col_tour_id))
    tour_id_b = _resolve_first_present(raw_b, list(config.col_tour_id))
    purpose_a = _resolve_preferred_purpose_column(raw_a, list(config.col_tour_purpose))
    purpose_b = _resolve_preferred_purpose_column(raw_b, list(config.col_tour_purpose))
    start_a = _resolve_first_present(raw_a, list(config.col_tour_start))
    start_b = _resolve_first_present(raw_b, list(config.col_tour_start))
    end_a = _resolve_first_present(raw_a, list(config.col_tour_end))
    end_b = _resolve_first_present(raw_b, list(config.col_tour_end))
    dur_a = _resolve_first_present(raw_a, list(config.col_tour_duration))
    dur_b = _resolve_first_present(raw_b, list(config.col_tour_duration))

    left = raw_a.select(
        [
            pl.col(tour_id_a).cast(pl.Int64).alias("tour_id"),
            pl.col(purpose_a).cast(pl.Utf8).alias("run_a_raw_purpose"),
            pl.col(start_a).cast(pl.Int64).alias("run_a_raw_start"),
            pl.col(end_a).cast(pl.Int64).alias("run_a_raw_end"),
            pl.col(dur_a).cast(pl.Int64).alias("run_a_raw_duration"),
        ]
    )
    right = raw_b.select(
        [
            pl.col(tour_id_b).cast(pl.Int64).alias("tour_id"),
            pl.col(purpose_b).cast(pl.Utf8).alias("run_b_raw_purpose"),
            pl.col(start_b).cast(pl.Int64).alias("run_b_raw_start"),
            pl.col(end_b).cast(pl.Int64).alias("run_b_raw_end"),
            pl.col(dur_b).cast(pl.Int64).alias("run_b_raw_duration"),
        ]
    )
    return left.join(right, on="tour_id", how="full", coalesce=True)


def _metric_diff_table(
    summary_a: pl.DataFrame,
    summary_b: pl.DataFrame,
    metric: str,
) -> pl.DataFrame:
    left = summary_a.select(["tour_purpose", "time_bin", metric]).rename(
        {metric: "run_a_count"}
    )
    right = summary_b.select(["tour_purpose", "time_bin", metric]).rename(
        {metric: "run_b_count"}
    )
    return (
        left.join(right, on=["tour_purpose", "time_bin"], how="full", coalesce=True)
        .fill_null(0.0)
        .with_columns((pl.col("run_a_count") - pl.col("run_b_count")).alias("diff"))
        .filter(pl.col("tour_purpose") != "all_tour_purposes")
        .filter(pl.col("diff") != 0)
    )


def _prepared_tour_totals(prepared) -> pl.DataFrame:
    return (
        prepared.tours.select(pl.col("summary_tour_purpose").alias("tour_purpose"))
        .drop_nulls()
        .group_by("tour_purpose")
        .len()
        .rename({"len": "tour_count"})
        .sort("tour_purpose")
    )


def _print_metric_report(name: str, diff_table: pl.DataFrame) -> None:
    print()
    print(name)
    if diff_table.is_empty():
        print("  no differences")
        return
    report = (
        diff_table.group_by("tour_purpose")
        .agg(
            pl.len().alias("diff_bins"),
            pl.col("diff").abs().sum().alias("abs_diff"),
        )
        .sort("tour_purpose")
    )
    print(report)


def _tour_row_comparison(prepared_a, prepared_b) -> pl.DataFrame:
    cols = ["tour_id", "summary_tour_purpose", "start_hour", "end_hour", "tourdur"]
    left = prepared_a.tours.select(cols).rename(
        {
            "summary_tour_purpose": "run_a_purpose",
            "start_hour": "run_a_start_hour",
            "end_hour": "run_a_end_hour",
            "tourdur": "run_a_tourdur",
        }
    )
    right = prepared_b.tours.select(cols).rename(
        {
            "summary_tour_purpose": "run_b_purpose",
            "start_hour": "run_b_start_hour",
            "end_hour": "run_b_end_hour",
            "tourdur": "run_b_tourdur",
        }
    )
    return left.join(right, on="tour_id", how="full", coalesce=True)


def _print_tour_id_alignment_report(comp: pl.DataFrame) -> None:
    missing_in_a = comp.filter(pl.col("run_a_purpose").is_null()).height
    missing_in_b = comp.filter(pl.col("run_b_purpose").is_null()).height
    matched = comp.filter(
        pl.col("run_a_purpose").is_not_null() & pl.col("run_b_purpose").is_not_null()
    )

    print()
    print("Tour ID alignment")
    print(f"  tours only in run A: {missing_in_b}")
    print(f"  tours only in run B: {missing_in_a}")
    print(f"  tours present in both: {matched.height}")


def _print_row_level_metric_report(
    comp: pl.DataFrame,
    *,
    metric: str,
    example_limit: int = 10,
) -> None:
    run_a_col = f"run_a_{metric}"
    run_b_col = f"run_b_{metric}"
    matched = comp.filter(
        pl.col("run_a_purpose").is_not_null() & pl.col("run_b_purpose").is_not_null()
    )
    mismatches = matched.filter(pl.col(run_a_col) != pl.col(run_b_col)).with_columns(
        pl.coalesce([pl.col("run_a_purpose"), pl.col("run_b_purpose")]).alias(
            "tour_purpose"
        )
    )

    print()
    print(f"Row-level mismatches for {metric}")
    if mismatches.is_empty():
        print("  no differences")
        return

    by_purpose = (
        mismatches.group_by("tour_purpose")
        .agg(pl.len().alias("mismatched_tours"))
        .sort("tour_purpose")
    )
    print(by_purpose)

    example_cols = ["tour_id", "tour_purpose", run_a_col, run_b_col]
    for column in [
        "run_a_start_hour",
        "run_b_start_hour",
        "run_a_end_hour",
        "run_b_end_hour",
        "run_a_tourdur",
        "run_b_tourdur",
    ]:
        if column not in example_cols:
            example_cols.append(column)

    examples = (
        mismatches.select(example_cols)
        .sort(["tour_purpose", "tour_id"])
        .head(example_limit)
    )
    print("Examples")
    print(examples)


def _print_raw_metric_report(
    raw_comp: pl.DataFrame,
    *,
    metric: str,
    example_limit: int = 10,
) -> None:
    run_a_col = f"run_a_raw_{metric}"
    run_b_col = f"run_b_raw_{metric}"
    matched = raw_comp.filter(
        pl.col("run_a_raw_purpose").is_not_null() & pl.col("run_b_raw_purpose").is_not_null()
    )
    mismatches = matched.filter(pl.col(run_a_col) != pl.col(run_b_col)).with_columns(
        pl.coalesce([pl.col("run_a_raw_purpose"), pl.col("run_b_raw_purpose")]).alias(
            "raw_purpose"
        )
    )
    print()
    print(f"Raw-data mismatches for {metric}")
    if mismatches.is_empty():
        print("  no differences")
        return
    by_purpose = (
        mismatches.group_by("raw_purpose")
        .agg(pl.len().alias("mismatched_tours"))
        .sort("raw_purpose")
    )
    print(by_purpose)
    example_cols = ["tour_id", "raw_purpose", run_a_col, run_b_col]
    for column in [
        "run_a_raw_start",
        "run_b_raw_start",
        "run_a_raw_end",
        "run_b_raw_end",
        "run_a_raw_duration",
        "run_b_raw_duration",
    ]:
        if column not in example_cols:
            example_cols.append(column)
    examples = (
        mismatches.select(example_cols)
        .sort(["raw_purpose", "tour_id"])
        .head(example_limit)
    )
    print("Examples")
    print(examples)


def main() -> None:
    args = parse_args()
    config = Config.from_yaml(Path(args.config))
    run_a, run_b = _resolve_run_pair(config, args.run_a, args.run_b)

    raw_a = _read_raw_tours(run_a, config)
    raw_b = _read_raw_tours(run_b, config)
    prepared_a, summary_a = _prepare_run(run_a, config)
    prepared_b, summary_b = _prepare_run(run_b, config)

    print(
        f"Comparing Tour Time summaries: {run_a['label']!r} vs {run_b['label']!r}"
    )
    print(f"Config: {Path(args.config).resolve()}")

    totals_a = _prepared_tour_totals(prepared_a).rename({"tour_count": "run_a_count"})
    totals_b = _prepared_tour_totals(prepared_b).rename({"tour_count": "run_b_count"})
    totals = (
        totals_a.join(totals_b, on="tour_purpose", how="full", coalesce=True)
        .fill_null(0)
        .with_columns((pl.col("run_a_count") - pl.col("run_b_count")).alias("diff"))
        .sort("tour_purpose")
    )

    print()
    print("Prepared tour totals by summary purpose")
    print(totals)

    raw_comp = _raw_tour_comparison(raw_a, raw_b, config)
    print()
    print("Raw tour ID alignment")
    print(
        f"  tours only in run A: {raw_comp.filter(pl.col('run_a_raw_purpose').is_not_null() & pl.col('run_b_raw_purpose').is_null()).height}"
    )
    print(
        f"  tours only in run B: {raw_comp.filter(pl.col('run_a_raw_purpose').is_null() & pl.col('run_b_raw_purpose').is_not_null()).height}"
    )
    print(
        f"  tours present in both: {raw_comp.filter(pl.col('run_a_raw_purpose').is_not_null() & pl.col('run_b_raw_purpose').is_not_null()).height}"
    )

    tour_comp = _tour_row_comparison(prepared_a, prepared_b)
    _print_tour_id_alignment_report(tour_comp)

    _print_metric_report(
        "Departure differences by purpose",
        _metric_diff_table(summary_a, summary_b, "departure_tour_count"),
    )
    _print_metric_report(
        "Arrival differences by purpose",
        _metric_diff_table(summary_a, summary_b, "arrival_tour_count"),
    )
    _print_metric_report(
        "Duration differences by purpose",
        _metric_diff_table(summary_a, summary_b, "duration_tour_count"),
    )
    _print_row_level_metric_report(tour_comp, metric="start_hour")
    _print_row_level_metric_report(tour_comp, metric="end_hour")
    _print_row_level_metric_report(tour_comp, metric="tourdur")
    _print_raw_metric_report(raw_comp, metric="start")
    _print_raw_metric_report(raw_comp, metric="end")
    _print_raw_metric_report(raw_comp, metric="duration")


if __name__ == "__main__":
    main()
