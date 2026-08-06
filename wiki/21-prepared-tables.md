# 21 - Prepared Tables

Prepared tables are the canonical form of ActivitySim output. They remove
differences in raw file names and provide stable fields for summaries and
dashboard pages.

[14 - Input Data Contract](14-input-data-contract.md) defines the exact input
inventory, canonical identifiers and types, relationship checks, availability
states, and requirements for bypassing prepare. This chapter explains how the
processor creates and extends that contract.

## Prepare Data Flow

```text
reader
  -> identifier and column canonicalization
  -> escort and weight normalization
  -> zone context
  -> household/person enrichment
  -> student enrollment
  -> day and vehicle preparation
  -> tour enrichment
  -> trip enrichment
  -> non-motorized distance and time-period enrichment
  -> VOT bins
  -> final casts
  -> prepared cache
```

The public orchestration lives in
[`processor/prepare/enrichment/pipeline.py`](../processor/prepare/enrichment/pipeline.py),
with domain boundaries in `processor/prepare/enrichment/domains.py`.

## Important Modules

| Module | Role |
|---|---|
| `processor/prepare/reader.py` | Loads raw files and prepared-table inputs. |
| `processor/prepare/enrichment/pipeline.py` | Public prepare entry point. |
| `processor/prepare/enrichment/domains.py` | Source, people/place, mobility, and final-output orchestration. |
| `processor/prepare/enrichment/canonicalize.py` | Identifier and core column normalization. |
| `processor/prepare/enrichment/weights.py` | `finalweight` behavior. |
| `processor/prepare/enrichment/zones.py` | MAZ/TAZ and geography fields. |
| `processor/prepare/enrichment/tours.py` | Tour-level prepared fields. |
| `processor/prepare/enrichment/trips.py` | Trip-level prepared fields. |
| `processor/prepare/enrichment/non_motorized_distance.py` | Optional walk/bike distance enrichment. |
| `processor/prepare/enrichment/time_periods.py` | Canonical trip and tour period fields. |
| `processor/prepare/enrichment/finalize.py` | Final table casting. |
| `processor/prepare/cache.py` | Prepared cache IO and manifests. |

## Prepared Table Names

`processor.models.PreparedTableName` defines the runtime table names:

| Config/file table ID | `RunData`/summary-contract name | Meaning |
|---|---|---|
| `households` | `hh` | Households. |
| `persons` | `per` | Persons. |
| `day` | `day` | Day table when available. |
| `tours` | `tours` | Tours. |
| `trips` | `trips` | Trips. |
| `vehicles` | `vehicles` | Vehicles when available. |
| `joint_tour_participants` | `joint_participants` | Joint tour participants. |
| `land_use` | `land_use` | Land use and geography lookup data. |
| no file-map ID | `skim` | Optional `skim_matrix` support exposed as a special prepared requirement. |

Use configuration and file IDs in `files`, `file_map`, and
`prepared_table_map`. Use runtime names to access `RunData` and in
`@summary(required_columns=...)`. Examples are `run.per` and
`required_columns={"per": ("person_type",)}`.

## Common Prepared Fields

The exact schema can differ for each model and optional input. Summaries
frequently use these fields:

- canonical IDs: `household_id`, `person_id`, `tour_id`, `trip_id`
- purpose and mode fields: `tour_purpose`, `trip_purpose`, `tour_mode`, `trip_mode`
- time fields: `start_hour`, `end_hour`, `depart_hour`
- stop fields: `num_ob_stops`, `num_ib_stops`, `num_tot_stops`, `stops`
- distance/geography fields: `SKIMDIST`, `OTAZ`, `DTAZ`, `HGEO`, `WGEO`
- household/person aliases: `HHVEH`, `HHSIZE`, `AUTOSUFF`, `NUMBER_HH`
- aggregation weight: `finalweight`

Use the prepared field when it exists. Do not search for raw names in a summary
or page.

This introductory list does not imply that every table has every field. For a
specific summary, the generated catalog in chapter 26 lists the required
prepared columns. At runtime, `@summary` requirements and prepared-table
availability metadata determine whether a calculation can run.

## Inspecting An Exact Prepared Schema

The repository does not treat the columns in one sample prepared cache as a
fixed schema. Raw model extensions, optional inputs, and other input changes
make that list model-specific.

To inspect a cache:

1. Read the run's `manifest.json`. Find the prepared-table files and the
   recorded availability status.
2. Examine the Parquet or CSV schema for the relevant table.
3. Use `processor.models.RunData` names at runtime and the file/config names in
   [Prepared Table Names](#prepared-table-names).
4. Use the generated [Summary Catalog](26-summary-catalog.md) to find the exact
   prepared columns required by each registered summary.

Add stable fields to the relevant prepare enrichment module, with a prepare
test for each field. A row count or column found in only one regional model
describes that data set, not the portable visualizer contract.

## Adding A Prepared Column

For a complete example, see
[Add A Column To An Existing Prepared Table](41-data-extension-cookbook.md#worked-example-add-a-column-to-an-existing-prepared-table).

Use this approach when many summaries or pages need the same derived field, or
when the field is part of canonical model-output normalization.

Checklist:

1. Choose the owning enrichment module.
2. Add the Polars expression or transformation in the relevant stage.
3. If the input is optional, keep the table usable when source columns are missing.
4. Add final type/cast behavior if the field must be stable.
5. Add or update tests that prepare a minimal run and assert the new column.
6. If a summary depends on the column, add it to that summary's contract
   `required_columns`.
7. If a page reads it directly, add the table to `required_prepared_tables`.

Example pattern:

```python
if "source_column" in state.trips.columns:
    state.trips = state.trips.with_columns(
        pl.col("source_column").cast(pl.Float64).alias("new_prepared_column")
    )
```

Do not add page formatting columns to prepared tables. Use page helpers or
summary output columns for presentation.

## Using Prepared Tables As Inputs

Use `prepared_table_map` to omit raw prepare for a run:

```yaml
runs:
  - label: Custom Prepared
    prepared_table_map:
      households: C:\prepared\households.parquet
      persons: C:\prepared\persons.parquet
      tours: C:\prepared\tours.parquet
      trips: C:\prepared\trips.parquet
      land_use: C:\prepared\land_use.parquet
```

The supplied tables must agree with the prepared contract.

A new prepared table type changes the configuration, `RunData`, reader,
availability, cache I/O, and pruning. It can also change segmentation. Follow
the [complete example](41-data-extension-cookbook.md#worked-example-add-a-prepared-table).

## Related Chapters

- [11 - Configuring Your Data](11-configuring-your-data.md#already-prepared-tables)
- [14 - Input Data Contract](14-input-data-contract.md)
- [15 - Cache And Manifest Reference](15-cache-manifest-reference.md)
- [25 - Summary Functions](25-summary-functions.md)
- [24 - Segmentation](24-segmentation.md)
- [27 - Geography](27-geography.md)
- [31 - Dashboard Page Contract](31-dashboard-pages.md)
- [01 - Architecture](01-architecture.md)
