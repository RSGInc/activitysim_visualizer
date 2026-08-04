"""Generate deterministic estimated tables for validation-page demonstrations."""

from __future__ import annotations

import csv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "outside_summary_tables"
OUTPUT_DIR = SOURCE_DIR / "estimated_fixtures"
RUNS = ("unfiltered", "filtered", "override", "estimation-output")
RUN_BIASES = (-0.08, -0.03, 0.03, 0.08)
PERIOD_COLUMNS = ("am_vol", "md_vol", "pm_vol", "day_vol")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _estimated_value(value: str | float, run_index: int, row_index: int, column_index: int) -> float:
    variation = (((row_index + 3) * (column_index + 5) * (run_index + 2)) % 17 - 8) / 100
    return max(0.0, float(value) * (1.0 + RUN_BIASES[run_index] + variation))


def _write_count_locations(run: str, run_index: int) -> None:
    source = _read_rows(SOURCE_DIR / "countLocCounts.csv")
    rows: list[dict[str, object]] = []
    for row_index, row in enumerate(source):
        output: dict[str, object] = {"id": row["id"], "FACTYPE": row["FACTYPE"]}
        for column_index, column in enumerate(PERIOD_COLUMNS):
            output[column] = _estimated_value(
                row[column], run_index, row_index, column_index
            )
        rows.append(output)
    _write_rows(
        OUTPUT_DIR / run / "count_location_volumes_validation_summary.csv",
        ["id", "FACTYPE", *PERIOD_COLUMNS],
        rows,
    )


def _write_links(run: str, run_index: int) -> None:
    source = _read_rows(SOURCE_DIR / "allLinkSummary.csv")[:2000]
    rows: list[dict[str, object]] = []
    for row_index, row in enumerate(source):
        output: dict[str, object] = {
            "id": row["id"],
            "From_Node": row["From_Node"],
            "To_Node": row["To_Node"],
            "FACTYPE": row["FACTYPE"],
        }
        for column_index, column in enumerate(PERIOD_COLUMNS):
            output[column] = _estimated_value(
                row[column], run_index, row_index, column_index
            )
        rows.append(output)
    _write_rows(
        OUTPUT_DIR / run / "link_validation_summary.csv",
        ["id", "From_Node", "To_Node", "FACTYPE", *PERIOD_COLUMNS],
        rows,
    )


def _write_screenlines(run: str, run_index: int) -> None:
    counts = _read_rows(SOURCE_DIR / "countLocCounts.csv")[:16]
    rows: list[dict[str, object]] = []
    for row_index, row in enumerate(counts):
        for column_index, (period, column) in enumerate(
            zip(("AM", "MD", "PM", "Day"), PERIOD_COLUMNS)
        ):
            observed = float(row[column])
            rows.append(
                {
                    "screenline_id": f"SL-{row_index + 1:02d}",
                    "direction": "NB/EB" if row_index % 2 == 0 else "SB/WB",
                    "count_period": period,
                    "facility_type": row["FACTYPE"],
                    "observed_volume": observed,
                    "modeled_volume": _estimated_value(
                        observed, run_index, row_index, column_index
                    ),
                }
            )
    _write_rows(
        OUTPUT_DIR / run / "screenline_flow_comparisons.csv",
        [
            "screenline_id",
            "direction",
            "count_period",
            "facility_type",
            "observed_volume",
            "modeled_volume",
        ],
        rows,
    )


def _write_commuting_flows(run: str, run_index: int) -> None:
    rows: list[dict[str, object]] = []
    for source_name, geography_type in (
        ("countyFlows.csv", "district"),
        ("countyFlows_JoJa.csv", "county"),
    ):
        for row_index, row in enumerate(_read_rows(SOURCE_DIR / source_name)):
            origin = row.get("") or row.get("Origin")
            if origin is None or origin.strip().lower() == "total":
                continue
            for column_index, (destination, value) in enumerate(row.items()):
                if destination in {"", "Origin", "Total"}:
                    continue
                rows.append(
                    {
                        "origin_geography_type": geography_type,
                        "origin_geography_id": origin,
                        "destination_geography_type": geography_type,
                        "destination_geography_id": destination,
                        "commuter_count": _estimated_value(
                            value, run_index, row_index, column_index
                        ),
                    }
                )
    _write_rows(
        OUTPUT_DIR / run / "commuting_flows.csv",
        [
            "origin_geography_type",
            "origin_geography_id",
            "destination_geography_type",
            "destination_geography_id",
            "commuter_count",
        ],
        rows,
    )


def _write_wide_summary(
    run: str,
    run_index: int,
    *,
    source_name: str,
    output_name: str,
    category_column: str,
    value_columns: list[str],
) -> None:
    source = _read_rows(SOURCE_DIR / source_name)
    rows: list[dict[str, object]] = []
    for row_index, row in enumerate(source):
        output: dict[str, object] = {category_column: row[category_column]}
        for column_index, column in enumerate(value_columns):
            output[column] = _estimated_value(
                row[column], run_index, row_index, column_index
            )
        output["Total"] = sum(float(output[column]) for column in value_columns)
        rows.append(output)
    _write_rows(
        OUTPUT_DIR / run / output_name,
        [category_column, *value_columns, "Total"],
        rows,
    )


def _write_observed_series() -> None:
    observed_dir = OUTPUT_DIR / "observed"
    _write_rows(
        observed_dir / "transit_boardings_by_operator_and_technology.csv",
        ["operator", "technology", "boardings"],
        [
            {"operator": "City Transit", "technology": "Bus", "boardings": 18400.0},
            {"operator": "Regional Transit", "technology": "Bus", "boardings": 9200.0},
            {"operator": "Regional Transit", "technology": "Rail", "boardings": 6100.0},
        ],
    )
    _write_rows(
        observed_dir / "transit_transfer_rate.csv",
        ["operator", "technology", "access_mode", "transfer_rate"],
        [
            {"operator": "City Transit", "technology": "Bus", "access_mode": "Walk", "transfer_rate": 1.21},
            {"operator": "Regional Transit", "technology": "Bus", "access_mode": "Walk", "transfer_rate": 1.34},
            {"operator": "Regional Transit", "technology": "Rail", "access_mode": "PNR", "transfer_rate": 1.47},
        ],
    )
    _write_rows(
        observed_dir / "bicycle_vmt_by_facility_type.csv",
        ["facility_type", "bicycle_vmt"],
        [
            {"facility_type": "Protected Bike Lane", "bicycle_vmt": 12400.0},
            {"facility_type": "Bike Lane", "bicycle_vmt": 18750.0},
            {"facility_type": "Shared Roadway", "bicycle_vmt": 9300.0},
            {"facility_type": "Multi-Use Path", "bicycle_vmt": 15600.0},
        ],
    )


def _write_estimated_series(run: str, run_index: int) -> None:
    observed_dir = OUTPUT_DIR / "observed"
    table_specs = (
        (
            "transit_boardings_by_operator_and_technology.csv",
            ["operator", "technology", "boardings"],
            ["boardings"],
        ),
        (
            "transit_transfer_rate.csv",
            ["operator", "technology", "access_mode", "transfer_rate"],
            ["transfer_rate"],
        ),
        (
            "bicycle_vmt_by_facility_type.csv",
            ["facility_type", "bicycle_vmt"],
            ["bicycle_vmt"],
        ),
    )
    for filename, fieldnames, value_columns in table_specs:
        source = _read_rows(observed_dir / filename)
        rows: list[dict[str, object]] = []
        for row_index, row in enumerate(source):
            output: dict[str, object] = dict(row)
            for column_index, column in enumerate(value_columns):
                output[column] = _estimated_value(
                    row[column], run_index, row_index, column_index
                )
            rows.append(output)
        _write_rows(OUTPUT_DIR / run / filename, fieldnames, rows)


def generate() -> None:
    _write_observed_series()
    for run_index, run in enumerate(RUNS):
        _write_count_locations(run, run_index)
        _write_links(run, run_index)
        _write_screenlines(run, run_index)
        _write_commuting_flows(run, run_index)
        _write_estimated_series(run, run_index)
        _write_wide_summary(
            run,
            run_index,
            source_name="cvm_summary.csv",
            output_name="commercial_vehicle_validation_summary.csv",
            category_column="tod",
            value_columns=["car", "mu", "su"],
        )
        _write_wide_summary(
            run,
            run_index,
            source_name="cvm_vmt_summary.csv",
            output_name="commercial_vehicle_vmt_validation_summary.csv",
            category_column="tod",
            value_columns=["car", "mu", "su"],
        )
        external_columns = [
            "hbcoll",
            "hbo",
            "hbr",
            "hbs",
            "hbsch",
            "hbw",
            "nhbnw",
            "nhbw",
            "truck",
        ]
        _write_wide_summary(
            run,
            run_index,
            source_name="ext_summary.csv",
            output_name="external_trip_validation_summary.csv",
            category_column="tod",
            value_columns=external_columns,
        )
        _write_wide_summary(
            run,
            run_index,
            source_name="ext_vmt_summary.csv",
            output_name="external_vmt_validation_summary.csv",
            category_column="tod",
            value_columns=external_columns,
        )


if __name__ == "__main__":
    generate()
