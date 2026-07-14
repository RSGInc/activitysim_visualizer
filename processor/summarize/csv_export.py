"""Supported CSV export boundary for summary calibration tables."""

from collections.abc import Mapping
from pathlib import Path

from runtime.logging import get_logger
import polars as pl

LOGGER = get_logger("processor.summarize.csv_export")


def write_summary_csvs(
    summaries: Mapping[str, pl.DataFrame], output_dir: str | Path
) -> None:
    """
    Write named summary DataFrames to the supported calibration CSV layout.

    Args:
        summaries: mapping from a plain filename stem to a DataFrame
        output_dir: directory to write files to

    Raises:
        TypeError: if a summary value is not a Polars DataFrame
        ValueError: if a filename stem is empty, includes a directory, or has a suffix
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, df in summaries.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Summary CSV names must be non-empty strings.")
        if Path(name).name != name or Path(name).suffix:
            raise ValueError(
                f"Summary CSV name {name!r} must be a plain filename without a suffix."
            )
        if not isinstance(df, pl.DataFrame):
            raise TypeError(
                f"Summary CSV {name!r} must be a Polars DataFrame, got {type(df).__name__}."
            )
        path = output_dir / f"{name}.csv"
        df.write_csv(path)
        LOGGER.info("Written: %s", path)
