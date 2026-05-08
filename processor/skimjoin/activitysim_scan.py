from __future__ import annotations

from pathlib import Path

import polars as pl


def load_table(path: str | Path) -> pl.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return pl.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    raise ValueError(f"Unsupported table format: {path}")


def summarize_table_columns(table: pl.DataFrame, *, table_name: str) -> pl.DataFrame:
    column_rows: list[dict[str, object]] = []
    preview_rows = table.head(5).to_dicts()
    for column in table.columns:
        row = {
            "table": table_name,
            "column": column,
            "dtype": str(table.schema[column]),
            "n_unique": int(table.select(pl.col(column).n_unique()).item()),
        }
        for index in range(5):
            value = preview_rows[index].get(column) if index < len(preview_rows) else None
            row[f"row_{index + 1}_value"] = "" if value is None else str(value)
        column_rows.append(row)
    return pl.DataFrame(column_rows, schema=_column_schema())


def scan_activitysim_tables(
    trips: pl.DataFrame, tours: pl.DataFrame | None = None
) -> tuple[pl.DataFrame, pl.DataFrame]:
    mode_rows: list[dict[str, object]] = []
    column_frames: list[pl.DataFrame] = []

    scan_targets = [("trips", trips, ["trip_mode", "tour_mode", "purpose"])]
    if tours is not None:
        scan_targets.append(("tours", tours, ["tour_mode", "primary_purpose"]))

    for table_name, table, columns in scan_targets:
        for column in columns:
            if column not in table.columns:
                continue
            counts = table.get_column(column).value_counts(sort=True)
            value_name = column
            count_name = "count" if "count" in counts.columns else "counts"
            for value, n_rows in counts.select(value_name, count_name).iter_rows():
                mode_rows.append(
                    {
                        "table": table_name,
                        "column": column,
                        "value": value,
                        "n_rows": int(n_rows),
                    }
                )

        column_frames.append(summarize_table_columns(table, table_name=table_name))

    mode_schema = {
        "table": pl.String,
        "column": pl.String,
        "value": pl.String,
        "n_rows": pl.Int64,
    }
    if column_frames:
        column_rows = pl.concat(column_frames, how="vertical")
    else:
        column_rows = pl.DataFrame(schema=_column_schema())
    return pl.DataFrame(mode_rows, schema=mode_schema), column_rows


def _column_schema() -> dict[str, pl.DataType]:
    return {
        "table": pl.String,
        "column": pl.String,
        "dtype": pl.String,
        "n_unique": pl.Int64,
        "row_1_value": pl.String,
        "row_2_value": pl.String,
        "row_3_value": pl.String,
        "row_4_value": pl.String,
        "row_5_value": pl.String,
    }
