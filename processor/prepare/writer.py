"""Prepared-table writer helpers."""

from __future__ import annotations

from pathlib import Path

from activitysim_viz_logging import get_logger
import polars as pl

LOGGER = get_logger("processor.prepare.writer")


def write_all(
    tables: dict[str, pl.DataFrame],
    output_dir: str | Path,
    *,
    file_format: str = "parquet",
) -> None:
    """Write prepared tables to one directory using a consistent file format."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if file_format not in {"parquet", "csv"}:
        raise ValueError(
            f"Unsupported prepared table file format {file_format!r}. "
            "Supported formats: 'parquet', 'csv'."
        )

    for stem, table in tables.items():
        path = output_dir / f"{stem}.{file_format}"
        if file_format == "parquet":
            table.write_parquet(path)
        else:
            table.write_csv(path)
        LOGGER.info("Written prepared table: %s", path)
