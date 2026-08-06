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

The processor is responsible for:

- reading raw `.csv` or `.parquet` ActivitySim outputs
- normalizing identifiers and column names
- deriving canonical fields used by summary builders
- applying weights
- adding geography and zone fields
- optionally joining skim values to trips and tours
- optionally dividing output into configured segments
- writing prepared and summary caches
- recording manifests and diagnostics to identify stale output

The dashboard reads summary caches instead of reopening raw ActivitySim files.
Only pages that require prepared data read the prepared tables.

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
| Segmentation | [24 - Segmentation](24-segmentation.md) | Slice related prepared tables and repeat summaries for configured subsets. |
| Summaries | [25 - Summary Functions](25-summary-functions.md) | Build dashboard-ready tables. |
| Summary catalog | [26 - Summary Catalog](26-summary-catalog.md) | Inspect registered summary outputs. |
| Geography | [27 - Geography](27-geography.md) | Add consistent MAZ-, TAZ-, and custom geography fields. |

The former static prepared-cache schema described one `estimation-output` data
set, including its row counts and model-specific columns. Because those details
became incorrect when the input changed, the schema was not a portable runtime
contract. Use [Prepared Table Names and Fields](21-prepared-tables.md) for the
stable contract, and inspect the relevant cache manifest and table schema for
exact model-specific columns.

## Where Processor Output Goes

Prepared caches contain reusable canonical data, while summary caches contain
the smaller CSV files that serve as the standard dashboard input.

The processor also keeps diagnostic status. A table or summary can be:

- available and populated
- available but empty
- unavailable because an optional input is missing
- failed, with a recorded diagnostic

This status information lets the dashboard show partial results instead of
stopping the entire workflow when an optional table or summary is unavailable.

"Empty" and "unavailable" have different meanings. An empty result is valid but
has zero rows. An unavailable result is missing a required table or column, or
its declared operation could not run. A failed result means that the configured
failure policy recorded an exception. Preserve the availability metadata when
you copy `RunData`; checking only `DataFrame.is_empty()` loses this distinction.

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

Each boundary has one owner: prepare resolves source file names and aliases,
the summary defines the aggregate, the cache validates the stored contract, and
the page controls presentation. A page should therefore neither open a raw file
nor repeat a weighted aggregation. Chapter 44 gives the code for this example.

## Extension Checklist

To add processor behavior:

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
- [24 - Segmentation](24-segmentation.md)
- [25 - Summary Functions](25-summary-functions.md)
- [27 - Geography](27-geography.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
- [40 - Developer Workflows](40-developer-workflows.md)
