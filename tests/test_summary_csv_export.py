from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.summarize.csv_export import write_summary_csvs


def test_write_summary_csvs_round_trips_named_tables(tmp_path: Path) -> None:
    table = pl.DataFrame(
        {
            "tour_purpose": ["work", "school"],
            "tour_count": [12.5, 7.0],
        }
    )

    write_summary_csvs({"tour_counts": table}, tmp_path)

    assert pl.read_csv(tmp_path / "tour_counts.csv").equals(table)


@pytest.mark.parametrize("name", ["", "nested/table", "table.csv"])
def test_write_summary_csvs_rejects_non_stem_names(
    tmp_path: Path,
    name: str,
) -> None:
    with pytest.raises(ValueError, match="Summary CSV name"):
        write_summary_csvs({name: pl.DataFrame({"value": [1]})}, tmp_path)


def test_write_summary_csvs_requires_polars_tables(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="Polars DataFrame"):
        write_summary_csvs({"table": object()}, tmp_path)  # type: ignore[dict-item]
