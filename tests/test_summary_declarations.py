from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.models import RunData
from processor.summarize.catalog import build_summary_catalog
from processor.summarize.contracts import SummaryResultError, summary


def _run(**tables) -> RunData:
    defaults = {
        "hh": pl.DataFrame(),
        "per": pl.DataFrame(),
        "tours": pl.DataFrame(),
        "trips": pl.DataFrame(),
        "joint_participants": pl.DataFrame(),
        "land_use": pl.DataFrame(),
    }
    defaults.update(tables)
    return RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        skim_matrix=None,
        skim_zone_map=None,
        **defaults,
    )


def test_summary_declaration_supplies_identity_filename_and_typed_empty_preflight() -> (
    None
):
    calls = []

    @summary(
        id="probe",
        filename="probe_external_name",
        schema={"value": pl.Float64},
        required_columns={"trips": ("needed",)},
    )
    def probe(run: RunData, config) -> pl.DataFrame:
        calls.append(run.label)
        return pl.DataFrame({"value": [1.0]})

    result = probe(_run(), None)

    assert result.schema == {"value": pl.Float64}
    assert result.is_empty()
    assert calls == []
    assert probe.summary_definition.summary_id == "probe"
    assert probe.summary_definition.filename == "probe_external_name"


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (pl.DataFrame({"extra": [1.0]}), "missing columns: value"),
        (pl.DataFrame({"value": [1]}), "expected Float64, got Int64"),
        (
            pl.DataFrame({"other": [1.0], "value": [2.0]}),
            "columns in the wrong order",
        ),
    ],
)
def test_summary_declaration_rejects_invalid_successful_results(
    result, message
) -> None:
    schema = {"value": pl.Float64}
    if "other" in result.columns:
        schema = {"value": pl.Float64, "other": pl.Float64}

    @summary(id="invalid_result", schema=schema)
    def invalid_result(run: RunData, config) -> pl.DataFrame:
        return result

    with pytest.raises(SummaryResultError, match=message):
        invalid_result(_run(), None)


def test_explicit_catalog_rejects_duplicate_summary_ids() -> None:
    module = ModuleType("tests.duplicate_summaries")

    def first(run, config):
        return pl.DataFrame({"value": [1.0]})

    def second(run, config):
        return pl.DataFrame({"value": [2.0]})

    first.__module__ = module.__name__
    second.__module__ = module.__name__
    module.first = summary(id="duplicate", schema={"value": pl.Float64})(first)
    module.second = summary(id="duplicate", schema={"value": pl.Float64})(second)

    with pytest.raises(ValueError, match="Duplicate summary id 'duplicate'"):
        build_summary_catalog((module,))
