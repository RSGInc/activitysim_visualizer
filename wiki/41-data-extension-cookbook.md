# 41 - Data Extension Cookbook

This chapter gives complete examples of data extensions, starting at the
smallest supported boundary for each one.

## Choose The Smallest Extension

| Need | Extension |
|---|---|
| Load a dashboard-ready file produced elsewhere | Register an external summary schema and use `summary_table_map`. |
| Reuse one derived value in several summaries | Add a column to an existing prepared table. |
| Carry a new row type through the complete application | Add a prepared table. |

A prepared table changes more interfaces than a prepared column. Add a column
unless the new data has its own stable row type and lifecycle.

## Worked Example: Add An Outside Summary Table

In this example, a different process writes `regional_emissions.csv`:

```csv
pollutant,tons
CO2,1250.5
NOX,18.2
```

The visualizer accepts only registered summary IDs with exact schemas. Register
the external table with a builder that does not calculate values, and place it
in the relevant summary module. For multiple project tables, use a module such
as `processor/summarize/summaries/external_project.py`:

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

Set `build_by_default=False` because the standard ActivitySim workflow cannot
build this table. The ID and contract must exist to validate an external file.

If you add a module, import it and add it to `SUMMARY_MODULES` in
`processor/summarize/catalog.py`:

```python
from processor.summarize.summaries import external_project

SUMMARY_MODULES = (
    # existing modules...
    external_project,
)
```

Add the file to a run:

```yaml
runs:
  - label: Regional Inventory
    summary_table_map:
      regional_emissions: inputs/regional_emissions.csv
```

Relative paths start from the main configuration file. For both CSV and Parquet,
the loader performs these checks and actions:

1. rejects unknown summary IDs;
2. rejects missing or unexpected columns;
3. casts to the declared dtypes and declared column order; and
4. exposes the same outside table under every configured weighting mode.

The loader treats an external table as already aggregated, so the Weighted and
Unweighted selections do not calculate it again.

Connect the table to a page as optional data:

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

Use `required_summary_ids` only if the table is necessary for the primary page
view.

Add the table's category, analytical use, and field descriptions to
`scripts/summary_catalog_metadata.yaml` so chapter 26 can combine them with the
registered contract.

Tests must verify registration, strict schema validation, loading, and page
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

Use these commands:

```bash
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_summary_declarations.py tests/test_runtime_workflows.py
uv run python scripts/generate_wiki_catalogs.py
```

## Worked Example: Add A Column To An Existing Prepared Table

In this example, several summaries require a canonical household field named
`area_type`. The raw table contains the information to calculate it.

Put the transformation in the enrichment module for the domain. For a
household field, this module is usually
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

Then declare the prepared dependency where the summary uses it:

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

Add one prepare test with the source column and one without it. If the optional
source data is absent, the table must stay usable. The summary contract records
the new summary as unavailable when `area_type` is absent.

If configuration changes the derived value, add that configuration value to
`prepare_signature_payload()` in `runtime/config/signatures.py`. Without this
change, the visualizer can incorrectly use a cache from an old configuration.

## Worked Example: Add A Prepared Table

In this example, ActivitySim writes one row for each zone in
`final_accessibility.csv`. Columns on `land_use` cannot correctly represent
this table.

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
`RunData(...)` copy constructor. Because the copy constructors list fields
explicitly, missing one can cause a workflow to omit the table.

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

This tuple controls prepared file names, manifest entries, writes, and most
loads. Because it changes the prepared cache contract, increment
`SCHEMA_VERSION` and decide whether the reader can read older schema versions.

### 4. Decide Segmentation And Dashboard Behavior

If segmentation must filter or use the new table as an anchor, add rules in
`processor/segmentation.py`. Add aliases in
`runtime/config/normalize_segmentation.py`. Do not copy the complete table to
each segment unless this is correct for its row type.

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

At a minimum, test these items:

- config filename and `prepared_table_map` acceptance;
- raw reader success and optional-file absence;
- prepare-state round trip;
- prepared cache write/read and manifest schema version;
- pruning for pages that request or do not request the table;
- segmentation behavior, if supported; and
- one page-registry requirement test.

Useful suites:

```bash
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_processor_prepare.py tests/test_prepare_cache.py
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_runtime_workflows.py tests/test_page_registry_contract.py
```

## Completion Checklist

- The extension uses the narrowest suitable boundary.
- IDs are stable across config, runtime, cache, and dashboard declarations.
- Cache identity changes whenever config changes data content.
- Missing optional input produces typed empty/unavailable state, not a crash.
- External schemas reject extra and missing columns.
- Generated catalogs have been refreshed.

## Related Chapters

- [21 - Prepared Tables](21-prepared-tables.md)
- [25 - Summary Functions](25-summary-functions.md)
- [26 - Summary Catalog](26-summary-catalog.md)
- [42 - Config, Columns, and Labels](42-config-column-label-cookbook.md)
