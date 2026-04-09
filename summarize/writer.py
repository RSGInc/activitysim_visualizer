"""Optional CSV writer for calibration compatibility."""

from pathlib import Path

from activitysim_viz_logging import get_logger
import polars as pl

LOGGER = get_logger("summarize.writer")


def write_all(summaries: dict[str, pl.DataFrame], output_dir: str | Path) -> None:
    """
    Write all summary DataFrames to CSV files.

    Args:
        summaries: dict mapping filename (without .csv) to DataFrame
        output_dir: directory to write files to
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, df in summaries.items():
        path = output_dir / f"{name}.csv"
        df.write_csv(path)
        LOGGER.info("Written: %s", path)
