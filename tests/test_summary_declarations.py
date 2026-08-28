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
from scripts.generate_wiki_catalogs import (
    _validate_processor_output_reference,
    _validate_summary_reference,
    build_processor_output_reference,
    build_summary_catalog as build_wiki_summary_catalog,
)


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


def test_wiki_summary_catalog_documents_build_status_and_all_fields() -> None:
    _validate_summary_reference()

    catalog = build_wiki_summary_catalog()

    assert "### Population and Demographics" in catalog
    assert "Related dashboard pages: Overview." in catalog
    assert (
        "| Summary Table | Information and Analytical Use | "
        "Required Tables/Fields | Output Fields | Summary Function |"
    ) in catalog
    population_row = next(
        line for line in catalog.splitlines() if "`population_totals`<br>" in line
    )
    external_row = next(
        line
        for line in catalog.splitlines()
        if "`auto_vmt_validation_summary`<br>" in line
    )

    assert "`population_totals.csv`" in population_row
    assert "`per`: Prepared person table." in population_row
    assert "`finalweight` (`Float64`): Person expansion weight" in population_row
    assert "`person_count` (`Float64`): weighted persons." in population_row
    assert "`auto_vmt_validation_summary.csv`" in external_row
    assert "Default build: **no**" in external_row
    assert sum(line.startswith("| `") for line in catalog.splitlines()) == 100


def test_processor_output_reference_covers_each_output_boundary() -> None:
    _validate_processor_output_reference()
    reference = build_processor_output_reference()

    assert "## 1. Prepared Output Tables" in reference
    assert "## 2. Summary Output Tables" in reference
    assert "### Population and Demographics" in reference
    assert "## 3. Hypothetical All-Modes Skim Tables" in reference
    assert "## 4. Externally Supplied Table Schemas" in reference
    assert "**These tables are not created by the processor.**" in reference
    assert "### `households` Prepared Table" in reference
    assert "_Processor runtime name: `hh`._" in reference
    assert "| Field | Type | Description |" in reference
    assert "| Summary Table | Information and Analytical Use | Fields |" in reference
    assert (
        "Every summary table is saved as a CSV file named "
        "`<summary_table>.csv`." in reference
    )
    assert "Required Tables/Fields" not in reference
    assert "Summary Function" not in reference
    household_row = next(
        line for line in reference.splitlines() if line.startswith("| `household_id`")
    )
    population_row = next(
        line
        for line in reference.splitlines()
        if line.startswith("| `population_totals` |")
    )
    sidecar_row = next(
        line
        for line in reference.splitlines()
        if line.startswith("| `trip_hypothetical_skims` |")
    )
    external_row = next(
        line
        for line in reference.splitlines()
        if line.startswith("| `auto_vmt_validation_summary` |")
    )
    assert "| `household_id` | `Int64` |" in household_row
    assert "`population_totals.csv`" not in population_row
    assert "`person_count` (`Float64`): weighted persons." in population_row
    assert "`trip_id` (`Int64`)" in sidecar_row
    assert "`auto_vmt_validation_summary.csv`" not in external_row
    assert "skim_lookup_summary.csv" not in reference

    summary_section, remainder = reference.split(
        "## 2. Summary Output Tables", maxsplit=1
    )[1].split("## 3. Hypothetical All-Modes Skim Tables", maxsplit=1)
    sidecar_section, external_section = remainder.split(
        "## 4. Externally Supplied Table Schemas", maxsplit=1
    )
    assert sum(line.startswith("| `") for line in summary_section.splitlines()) == 87
    assert sum(line.startswith("| `") for line in sidecar_section.splitlines()) == 2
    assert sum(line.startswith("| `") for line in external_section.splitlines()) == 13
