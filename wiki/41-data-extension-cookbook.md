# 41 - Data Extension Cookbook

This chapter contains end-to-end examples for extending the data that reaches
the dashboard. Each recipe starts at the narrowest supported boundary.

## Choose The Smallest Extension

| Need | Extension |
|---|---|
| Load a dashboard-ready file produced elsewhere | Register an external summary schema and use `summary_table_map`. |
| Reuse one derived value in several summaries | Add a column to an existing prepared table. |
| Carry a genuinely new row grain through the whole application | Add a prepared table. |

Adding a prepared table is much more invasive than adding a column. Prefer a
column unless the new data has its own stable row grain and lifecycle.

## Worked Example: Add An Outside Summary Table

Suppose another process writes `regional_emissions.csv`:

```csv
pollutant,tons
CO2,1250.5
NOX,18.2
```

The visualizer only accepts registered summary IDs with exact schemas. Register
the outside table with a no-op builder in an owning summary module. For a group
of project-supplied tables, a module such as
`processor/summarize/summaries/external_project.py` is appropriate:

```python
import polars as pl

from processor.models import RunData
from processor.summarize import summary
from runtime.config import Config


@summary(
    id="regional_emissions",
    build_by_default=False,
    schema={
        "pollutant": pl.Utf8,
        "tons": pl.Float64,
    },
)
def regional_emissions(run: RunData, config: Config) -> pl.DataFrame:
    return regional_emissions.empty()
```

`build_by_default=False` is important: raw ActivitySim runs cannot build this
table, but the ID and contract must exist so an outside file can be validated.

If this is a new module, import it and add it to `SUMMARY_MODULES` in
`processor/summarize/catalog.py`:

```python
from processor.summarize.summaries import external_project

SUMMARY_MODULES = (
    # existing modules...
    external_project,
)
```

Point a run at the file:

```yaml
runs:
  - label: Regional Inventory
    summary_table_map:
      regional_emissions: inputs/regional_emissions.csv
```

Relative paths resolve from the main config file. CSV and Parquet are
supported. The loader:

1. rejects unknown summary IDs;
2. rejects missing or unexpected columns;
3. casts to the declared dtypes and declared column order; and
4. exposes the same outside table under every configured weighting mode.

The fourth behavior matters: an outside table is assumed to be already
aggregated. Selecting Weighted or Unweighted does not recalculate it.

Wire the table to a page as optional data:

```python
@dashboard_page(
    page_id="regional_validation",
    title="Regional Validation",
    optional_summary_ids=("regional_emissions",),
)
class RegionalValidationPage(DashboardPage):
    def render_emissions(self):
        data = self.data.summary("regional_emissions")
        if not data:
            return self.data_not_available_card(
                detail="Provide regional_emissions with summary_table_map.",
                missing_items=["regional_emissions"],
            )
        return self.plot.bar(data, x="pollutant", y="tons")
```

Use `required_summary_ids` only if the page has no meaningful primary view
without the table.

Tests should prove registration, strict schema validation, loading, and page
requirements:

```python
def test_regional_emissions_is_external_only():
    definition = SUMMARY_BY_ID["regional_emissions"]
    assert definition.build_by_default is False
    assert list(definition.contract.schema) == ["pollutant", "tons"]


def test_external_emissions_loads(tmp_path, config):
    path = tmp_path / "regional_emissions.csv"
    pl.DataFrame(
        {"pollutant": ["CO2"], "tons": [1250.5]}
    ).write_csv(path)
    run = load_summary_table_map(
        summary_table_map={"regional_emissions": str(path)},
        label="Inventory",
        run_key="inventory",
        config=config,
    )
    assert run.summaries_by_mode["weighted"]["regional_emissions"].height == 1
```

Run:

```bash
pytest tests/test_summary_declarations.py tests/test_runtime_workflows.py
python scripts/generate_wiki_catalogs.py
```

## Worked Example: Add A Column To An Existing Prepared Table

Suppose several summaries need a canonical household field named
`area_type`. The raw table already contains enough information to derive it.

Put the transformation in the enrichment module that owns the domain. For a
household field, that is normally
`processor/prepare/enrichment/households_persons.py`:

```python
def _add_household_area_type(state: _PrepareState) -> _PrepareState:
    if "density" not in state.hh.columns:
        return state
    state.hh = state.hh.with_columns(
        pl.when(pl.col("density") >= 10_000)
        .then(pl.lit("urban"))
        .otherwise(pl.lit("non_urban"))
        .alias("area_type")
    )
    return state
```

Call it from the owning domain in
`processor/prepare/enrichment/domains.py`:

```python
def enrich_people_and_places_domain(state, config):
    # existing enrichment...
    state = _add_household_area_type(state)
    return state
```

Then declare the prepared dependency where it is consumed:

```python
@summary(
    id="households_by_area_type",
    schema={
        "area_type": pl.Utf8,
        "household_count": pl.Float64,
    },
    required_columns={"hh": ("area_type", "finalweight")},
)
def households_by_area_type(run, config):
    return (
        run.hh.group_by("area_type")
        .agg(pl.col("finalweight").sum().alias("household_count"))
        .with_columns(
            pl.col("area_type").cast(pl.Utf8),
            pl.col("household_count").cast(pl.Float64),
        )
        .select("area_type", "household_count")
    )
```

Add a prepare test with the source column present and another with it absent.
Optional source data should leave the table usable; the summary contract will
record the new summary as unavailable when `area_type` is absent.

If config affects the derived value, also add that config value to
`prepare_signature_payload()` in `runtime/config/signatures.py`. Otherwise a
prepared cache built with old config could be reused incorrectly.

## Worked Example: Add A Prepared Table

Assume ActivitySim now emits one row per zone in `final_accessibility.csv`, and
the table cannot sensibly be represented as columns on `land_use`.

### 1. Define Names And Runtime Storage

Add the raw/config ID in `runtime/config/constants.py`:

```python
FILE_MAPPING_DEFAULTS = {
    # existing tables...
    "accessibility": "final_accessibility",
}
OPTIONAL_PREPARED_TABLE_IDS = {
    # existing optional tables...
    "accessibility",
}
```

Add the runtime attribute in `processor/models.py`:

```python
PreparedTableName = Literal[
    # existing names...
    "accessibility",
]

@dataclass
class RunData:
    # existing fields...
    accessibility: pl.DataFrame = field(default_factory=pl.DataFrame)
```

Also update `PREPARED_TABLE_NAMES`, `prune_prepared_run()`, and every explicit
`RunData(...)` copy constructor. Copy constructors are intentionally explicit;
missing one is a common source of a table disappearing between workflows.

### 2. Read It And Track Availability

In `processor/prepare/reader.py`:

```python
accessibility = _read("accessibility")

return attach_table_availability(
    RunData(
        # existing arguments...
        accessibility=accessibility,
    ),
    table_states=table_states,
    table_reasons=table_reasons,
)
```

Add `("accessibility", "accessibility")` to `RUN_TABLE_ATTRS` and the ID to
`PREPARED_TABLE_IDS` in `processor/prepare/availability.py`.

### 3. Carry It Through Prepare State And Cache IO

Add the field to `_PrepareState.from_run()` and `_PrepareState.to_run()` in
`processor/prepare/enrichment/types.py`. Then add this cache mapping in
`processor/prepare/cache.py`:

```python
PREPARED_TABLE_ATTRS = (
    # attribute, config/table ID, file stem
    # existing entries...
    ("accessibility", "accessibility", "accessibility"),
)
```

That one tuple drives prepared filenames, manifest entries, writes, and most
loads. Because it changes the prepared cache contract, increment
`SCHEMA_VERSION` and decide whether old schema versions remain readable.

### 4. Decide Segmentation And Dashboard Behavior

If segmentation must filter or anchor on the new table, add explicit rules in
`processor/segmentation.py` and aliases in
`runtime/config/normalize_segmentation.py`. Do not silently copy the full table
into every segment unless that is correct for its row grain.

Pages can now declare:

```python
@dashboard_page(
    page_id="accessibility",
    title="Accessibility",
    prepared_data_mode="required",
    required_prepared_tables=("accessibility",),
)
```

### 5. Test Every Boundary

At minimum, cover:

- config filename and `prepared_table_map` acceptance;
- raw reader success and optional-file absence;
- prepare-state round trip;
- prepared cache write/read and manifest schema version;
- pruning for pages that request or do not request the table;
- segmentation behavior, if supported; and
- one page-registry requirement test.

Useful suites:

```bash
pytest tests/test_processor_prepare.py tests/test_prepare_cache.py
pytest tests/test_runtime_workflows.py tests/test_page_registry_contract.py
```

## Completion Checklist

- The extension uses the narrowest suitable boundary.
- IDs are stable across config, runtime, cache, and dashboard declarations.
- Cache identity changes whenever config changes data content.
- Missing optional input produces typed empty/unavailable state, not a crash.
- External schemas reject extra as well as missing columns.
- Generated catalogs have been refreshed.

## Related Chapters

- [21 - Prepared Tables](21-prepared-tables.md)
- [23 - Summary Functions](23-summary-functions.md)
- [24 - Summary Catalog](24-summary-catalog.md)
- [42 - Config, Columns, and Labels](42-config-column-label-cookbook.md)
