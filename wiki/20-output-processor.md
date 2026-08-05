# 20 - Output Processor

The Output Processor converts ActivitySim model output to stable data for the
dashboard.

```text
raw ActivitySim tables or prepared table inputs
  -> prepare
  -> optional skimjoin
  -> optional segmentation
  -> summarize
  -> prepared caches and summary caches
```

The main code lives under [`processor/`](../processor), with workflow
orchestration under [`runtime/workflows`](../runtime/workflows).

## Responsibilities

The processor does these tasks:

- reading raw `.csv` or `.parquet` ActivitySim outputs
- normalizing identifiers and column names
- deriving canonical fields used by summary builders
- applying weights
- adding geography and zone fields
- optionally joining skim values to trips and tours
- optionally dividing output into configured segments
- writing prepared and summary caches
- recording manifests and diagnostics to identify stale output

The dashboard must not read raw ActivitySim files again. It must use summary
caches. It uses prepared tables only for pages that require them.

## Runtime Data Contract

The key runtime object is `RunData` in
[`processor/models.py`](../processor/models.py). It holds one prepared run:

| Attribute | Meaning |
|---|---|
| `hh` | Prepared households. |
| `per` | Prepared persons. |
| `day` | Optional day table. |
| `tours` | Prepared tours. |
| `trips` | Prepared trips. |
| `vehicles` | Optional vehicles. |
| `joint_participants` | Joint tour participants. |
| `land_use` | Prepared land-use/geography table. |
| `skim_matrix` | Optional distance skim support. |
| `skimjoin_artifacts` | Optional skimjoin manifest and QA reports. |

Summary builders and prepared-data dashboard pages must use this prepared
contract. They must not use raw, model-specific table layouts.

## Processor Subsystems

| Subsystem | Chapter | What to use it for |
|---|---|---|
| Prepare | [21 - Prepared Tables](21-prepared-tables.md) | Normalize raw outputs and add derived fields. |
| Skimjoin | [22 - Skimjoin](22-skimjoin.md) | Add skim-derived trip and tour columns. |
| Summaries | [23 - Summary Functions](23-summary-functions.md) | Build dashboard-ready tables. |
| Summary catalog | [24 - Summary Catalog](24-summary-catalog.md) | Inspect registered summary outputs. |

The former static prepared-cache schema described one `estimation-output` data
set. It included row counts and model-specific columns. This schema was not a
portable runtime contract. It became incorrect when the input changed. Use
[Prepared Table Names and Fields](21-prepared-tables.md) for the stable
contract. Examine the applicable cache manifest and table schema for exact
model-specific columns.

## Where Processor Output Goes

Prepared caches contain reusable canonical data. Summary caches contain
smaller CSV files for the dashboard. The summary cache is the standard
dashboard input.

The processor also keeps diagnostic status. A table or summary can be:

- available and populated
- available but empty
- unavailable because an optional input is missing
- failed, with a recorded diagnostic

This behavior lets the dashboard show partial results. One unavailable optional
table or summary does not stop the complete workflow.

"Empty" and "unavailable" have different meanings. Empty means that the input
and calculation were valid, but the result has zero rows. Unavailable means
that a required table or column was absent. It can also mean that a declared
operation could not execute. Failed means that the configured failure policy
recorded an exception. Keep the availability metadata when you copy `RunData`.
A check of only `DataFrame.is_empty()` removes this information.

### Example: Follow One Metric

For a chart of trips by mode, the processor path is:

```text
final_trips.csv
  -> prepare canonicalizes trip_mode and finalweight
  -> RunData.trips
  -> trips_by_mode summary groups and weights rows
  -> registered summary cache
  -> page reads the table through self.data.summary(...)
```

Each boundary has one owner. Prepare resolves source file names and aliases.
The summary defines the aggregate. The cache validates the stored contract.
The page controls the presentation. Thus, a page must not open a raw file or
repeat a weighted aggregation. Chapter 44 gives the code for this example.

## Extension Checklist

To add processor behavior, do these steps:

1. Decide whether the new data belongs in prepared tables, skimjoin output, or
   a summary table.
2. Add or update the smallest processor subsystem that owns that behavior.
3. Keep stable output schemas and use typed empty fallback results when possible.
4. Update dashboard page requirements if a page depends on the new output.
5. Add focused tests for the new behavior.
6. Regenerate wiki catalogs if summary declarations or page definitions changed.

## Related Chapters

- [21 - Prepared Tables](21-prepared-tables.md)
- [22 - Skimjoin](22-skimjoin.md)
- [23 - Summary Functions](23-summary-functions.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
- [40 - Developer Workflows](40-developer-workflows.md)
