# 20 - Output Processor

The Output Processor turns ActivitySim model outputs into stable data products
for the dashboard.

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
- optionally slicing outputs into configured segments
- writing prepared and summary caches
- recording manifests and diagnostics so stale outputs can be detected

The dashboard should not re-read raw ActivitySim files. It should consume
summary caches and, only for pages that explicitly ask for them, prepared tables.

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

Summary builders and prepared-data dashboard pages should depend on this
prepared contract rather than raw model-specific table layouts.

## Processor Subsystems

| Subsystem | Chapter | What to use it for |
|---|---|---|
| Prepare | [21 - Prepared Tables](21-prepared-tables.md) | Normalize raw outputs and add derived fields. |
| Skimjoin | [22 - Skimjoin](22-skimjoin.md) | Add skim-derived trip and tour columns. |
| Summaries | [23 - Summary Functions](23-summary-functions.md) | Build dashboard-ready tables. |
| Summary catalog | [24 - Summary Catalog](24-summary-catalog.md) | Inspect registered summary outputs. |

## Where Processor Output Goes

Prepared caches are reusable canonical data. Summary caches are smaller,
dashboard-ready CSVs. The summary cache is the normal dashboard input.

The processor also carries diagnostic state. A table or summary can be:

- available and populated
- available but empty
- unavailable because an optional input is missing
- failed, with a recorded diagnostic

This is intentional. The dashboard can show partial results instead of failing
the entire workflow when one optional table or summary is unavailable.

## Extension Checklist

When adding new processor-visible behavior:

1. Decide whether the new data belongs in prepared tables, skimjoin outputs, or
   a summary table.
2. Add or update the smallest processor subsystem that owns that behavior.
3. Preserve stable output schemas and use typed empty fallbacks where possible.
4. Update dashboard page requirements if a page depends on the new output.
5. Add focused tests for the new behavior.
6. Regenerate wiki catalogs if summary specs or page definitions changed.

## Related Chapters

- [21 - Prepared Tables](21-prepared-tables.md)
- [22 - Skimjoin](22-skimjoin.md)
- [23 - Summary Functions](23-summary-functions.md)
- [40 - Developer Workflows](40-developer-workflows.md)

