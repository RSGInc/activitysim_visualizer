# 21 - Prepared Tables

Prepared tables are the processor's canonical form of ActivitySim output. They
hide raw file naming differences and expose stable fields for summaries and
dashboard pages.

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

Runtime table names are defined in `processor.models.PreparedTableName`:

| Name | Meaning |
|---|---|
| `hh` | Households. |
| `per` | Persons. |
| `day` | Day table when available. |
| `tours` | Tours. |
| `trips` | Trips. |
| `vehicles` | Vehicles when available. |
| `joint_participants` | Joint tour participants. |
| `land_use` | Land use and geography lookup data. |
| `skim` | Optional skim matrix support. |

## Common Prepared Fields

The exact schema can differ by model and optional inputs, but summaries commonly
rely on:

- canonical IDs: `household_id`, `person_id`, `tour_id`, `trip_id`
- purpose and mode fields: `tour_purpose`, `trip_purpose`, `tour_mode`, `trip_mode`
- time fields: `start_hour`, `end_hour`, `depart_hour`
- stop fields: `num_ob_stops`, `num_ib_stops`, `num_tot_stops`, `stops`
- distance/geography fields: `SKIMDIST`, `OTAZ`, `DTAZ`, `HGEO`, `WGEO`
- household/person aliases: `HHVEH`, `HHSIZE`, `AUTOSUFF`, `NUMBER_HH`
- aggregation weight: `finalweight`

Use the prepared field when it exists rather than probing raw names in a summary
or page.

## Adding A Prepared Column

For an end-to-end worked example, see
[Add A Column To An Existing Prepared Table](41-data-extension-cookbook.md#worked-example-add-a-column-to-an-existing-prepared-table).

Use this path when many summaries/pages need the same derived field or when the
field is part of canonical model-output normalization.

Checklist:

1. Choose the owning enrichment module.
2. Add the Polars expression or transformation in the appropriate stage.
3. Keep missing source columns graceful when the input is optional.
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

Do not add page-only formatting columns to prepared tables. Prefer page helpers
or summary output columns for presentation concerns.

## Using Prepared Tables As Inputs

`prepared_table_map` lets a config bypass raw prepare for a run:

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

This path assumes the supplied tables already match the prepared contract.

Adding a new prepared table type is a larger change covering config, `RunData`,
reader, availability, cache IO, pruning, and possibly segmentation. Follow the
[complete worked example](41-data-extension-cookbook.md#worked-example-add-a-prepared-table).

## Related Chapters

- [11 - Configuring Your Data](11-configuring-your-data.md#already-prepared-tables)
- [23 - Summary Functions](23-summary-functions.md)
- [31 - Dashboard Pages](31-dashboard-pages.md)
