# 14 - Input Data Contract

This chapter defines the boundary between ActivitySim output, canonical
prepared tables, summaries, and dashboard pages. Use it when you create a new
configuration, generate tables outside the visualizer, or diagnose an
unavailable summary.

The visualizer accepts three input levels:

```text
raw ActivitySim tables -> prepare -> canonical prepared tables -> summarize
canonical prepared tables -------------------------------> summarize
registered summary tables --------------------------------> dashboard
```

The level you supply determines which checks and transformations the visualizer
can perform.

## Raw Table Inventory

The raw reader recognizes these logical table IDs. The default file stems are
defined by `files` and can be changed globally or with `runs[*].file_map`.

| Table ID | Default stem | Coverage role | Main keys and relationships |
|---|---|---|---|
| `households` | `final_households` | Core | One row per `household_id`. Supplies household attributes and home zone. |
| `persons` | `final_persons` | Core | One row per `person_id`; `household_id` refers to households. |
| `tours` | `final_tours` | Core | One row per `tour_id`; normally contains `person_id` and `household_id`. |
| `trips` | `final_trips` | Core | One row per `trip_id`; normally contains `tour_id`, `person_id`, and `household_id`. |
| `day` | `final_day` | Optional | Person-day or household-day rows. Uses `day_id`, `person_id`, and/or `household_id`. |
| `vehicles` | `final_vehicles` | Optional | Vehicle rows related to households by `household_id`. |
| `joint_tour_participants` | `final_joint_tour_participants` | Optional | Participation rows related by `tour_id` and `person_id`. |
| `land_use` | `final_land_use` | Optional | One row per MAZ or TAZ. Supplies employment, enrollment, parking, and geography data. |

“Core” means the table is part of the standard household-person-tour-trip
model and is needed for broad default-page coverage. The reader does not stop
when one core file is absent. It marks that table `unavailable`, continues with
the tables it can load, and lets summary contracts identify the affected
outputs. A run is skipped only when none of the four core tables is usable.

Optional tables can still be required by individual summaries or pages. For
example, vehicle-characteristic summaries need `vehicles`, and several
geography or parking outputs need `land_use`.

## Raw File And Column Rules

For a configured stem without an extension, the reader first looks for
`<stem>.parquet` and then `<stem>.csv` in the run directory. An explicit `.csv`
or `.parquet` name selects only that file. A configured `fallback_files` path
is tried after the run-local file is absent; fallbacks are supported for
`day`, `vehicles`, `joint_tour_participants`, and `land_use`.

Raw column names are not a fixed schema. The `columns` and `zones` settings
select source names and prepare copies the first available alias into a
canonical column. These are the minimum relationship concepts for a fully
connected standard run:

| Concept | Canonical name | Expected tables |
|---|---|---|
| Household key | `household_id` | households, persons, tours, trips; optional day and vehicles |
| Person key | `person_id` | persons, tours, trips; optional day and joint participants |
| Tour key | `tour_id` | tours, trips, joint participants |
| Trip key | `trip_id` | trips |
| Home zone | `home_zone_id` | households and/or persons |
| Work/school zone | `workplace_zone_id`, `school_zone_id` | persons |
| Origin/destination | `origin`, `destination` | tours and trips |
| Land-use zone | `MAZ`, `TAZ` | land use |

The [configuration reference](13-configuration-reference.md#columns) lists all
configurable aliases. A missing concept does not necessarily invalidate its
whole table. It makes calculations that declare that column unavailable.

## Canonical Prepared Contract

Prepare preserves source columns and adds or normalizes canonical fields. The
portable contract is therefore a set of stable concepts, not one exhaustive
column list for every regional model.

| Prepared table | Stable identifiers | Common normalized or derived fields |
|---|---|---|
| `hh` | `household_id` (`Int64`) | `home_zone_id`, `HHVEH`, `HHSIZE`, `WORKERS`, `ADULTS`, `AUTOSUFF`, `HGEO`, `finalweight` |
| `per` | `person_id`, `household_id` (`Int64`) | `person_type`, home/work/school zones and geographies, worker/student fields, work/school distance, `finalweight` |
| `day` | `day_id`, `person_id`, `household_id` (`Int64` when present) | activity pattern, date/day fields, `finalweight` |
| `tours` | `tour_id`, `person_id`, `household_id` (`Int64`) | purpose, mode, category, time, stops, zones, distance, geography, `finalweight` |
| `trips` | `trip_id`, `tour_id`, `person_id`, `household_id` (`Int64`) | purpose, mode, departure, direction, stops, zones, distance, geography, `finalweight` |
| `vehicles` | `vehicle_id`, `household_id` (`Int64`) | number, type, body, fuel, age, `finalweight` |
| `joint_participants` | `tour_id`, `person_id` (`Int64`) | participant attributes retained from the source |
| `land_use` | `MAZ`, `TAZ` (`Int64` when present) | employment/enrollment, parking, and named geography fields |

The table-specific finalizer casts known canonical numeric fields to integer or
`Float64`, categorical fields to strings, and `finalweight` to `Float64`.
Columns not owned by the canonical contract keep their source types. See
[21 - Prepared Tables](21-prepared-tables.md) for the enrichment stages and
[26 - Summary Catalog](26-summary-catalog.md) for the exact fields required by
each summary.

## Prepared Relationship Checks

After prepare or `prepared_table_map` loading, the runtime can check these
foreign-key relationships:

| Source | Source key | Target | Target key |
|---|---|---|---|
| persons | `household_id` | households | `household_id` |
| day | `household_id` | households | `household_id` |
| day | `person_id` | persons | `person_id` |
| tours | `household_id` | households | `household_id` |
| tours | `person_id` | persons | `person_id` |
| trips | `household_id` | households | `household_id` |
| trips | `person_id` | persons | `person_id` |
| trips | `tour_id` | tours | `tour_id` |
| vehicles | `household_id` | households | `household_id` |
| joint participants | `person_id` | persons | `person_id` |
| joint participants | `tour_id` | tours | `tour_id` |

A check is skipped when a table or key column is unavailable. With
`prepare.validation.relationships: warn`, orphan rows produce warnings. With
`error`, they stop the workflow. Direct aggregations can still count an orphan
row, while an aggregation that joins to the parent can drop it. Fixing keys is
therefore preferable to suppressing the check.

## Using `prepared_table_map`

`prepared_table_map` loads CSV or Parquet files directly into `RunData`. It
does not run canonicalization, enrichment, weighting, geography mapping, or
integrated skimjoin. Supply canonical fields and types yourself.

The accepted keys are the eight config/file table IDs in the inventory above.
Omitted optional tables are marked `unavailable`. Omitted core tables are
represented as empty tables. Files that do not exist are `unavailable`; files
that cannot be read are `failed`. These states and their details flow into
summary and page diagnostics.

Before using custom prepared tables, verify:

1. IDs and foreign keys use compatible types and values.
2. Every requested summary has its required columns from chapter 26.
3. Every weighted table has the intended `finalweight`.
4. Geography and skimjoin columns already exist if the corresponding outputs
   depend on them.
5. Named weighting source columns are present when configured.

## Using `summary_table_map`

A mapped summary file is already at the final aggregation boundary. Its key
must be a registered summary ID, and its columns, order, and Polars-compatible
types must match that summary's declared schema.

The visualizer cannot derive prepared rows, alternate weights, or segment
membership from an aggregated summary file. Built-in weighted and unweighted
modes copy the same mapped table into both modes. Declarative or custom modes
normally reject mapped summaries unless their registered external-summary
policy explicitly permits copying.

If a run also has raw or prepared input, mapped summary tables replace the same
generated IDs and leave other generated summaries unchanged. During
segmentation, the same mapped table overlays every analysis unit; it does not
change by segment.

## Availability States

Tables and summaries use four stored states:

| State | Meaning |
|---|---|
| `available` | The source loaded or the calculation returned rows. |
| `empty` | The source or valid result contains no rows. |
| `unavailable` | A file, table, or declared prerequisite is absent. |
| `failed` | Reading or calculation raised an error under the recording policy. |

An empty cache file uses an internal `__empty__` sentinel column so CSV and
Parquet can store an otherwise zero-column frame. The loader converts it back
to an empty `DataFrame`; user-created input tables should not use this sentinel
as application data.

## Contract Checklist

When adding or exchanging data across the boundary:

1. Use config table IDs for file mappings and `RunData` names in Python
   contracts.
2. Preserve unique IDs and valid relationships.
3. Materialize canonical fields before bypassing prepare.
4. Declare exact summary inputs and output schema.
5. Treat units and weighting as part of the data contract, even when the file
   format cannot encode them.
6. Test unavailable, empty, and partial-run behavior, not only the complete
   case.

## Related Chapters

- [11 - Configuring Your Data](11-configuring-your-data.md)
- [13 - Configuration Reference](13-configuration-reference.md)
- [15 - Cache And Manifest Reference](15-cache-manifest-reference.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [26 - Summary Catalog](26-summary-catalog.md)
- [90 - Troubleshooting](90-troubleshooting.md)
