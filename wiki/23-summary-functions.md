# 23 - Summary Functions

Summary functions convert prepared `RunData` into Polars `DataFrame` objects
for the dashboard. Each function keeps its identity, requirements, output
schema, cache name, and builder in one declaration.

## Data flow

```text
RunData + Config
  -> @summary declaration and builder
  -> validated Polars DataFrame
  -> weighted/unweighted summary cache
  -> dashboard page
```

Builders live under [`processor/summarize/summaries`](../processor/summarize/summaries).
`processor.summarize.catalog` imports those modules and discovers their
declarations, so there is no separate summary specification registry to edit.

## Summary Declaration

Use `@summary(...)` from `processor.summarize`. The declaration provides:

- the stable summary ID and optional cache file name
- an ordered Polars output schema
- required prepared tables and columns
- a typed empty result
- strict result validation
- default build status

```python
import polars as pl

from processor.models import RunData
from processor.summarize import summary
from runtime.config import Config


@summary(
    id="trip_distance_by_mode",
    schema={
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
        "average_distance": pl.Float64,
    },
    required_columns={
        "trips": ("trip_mode", "od_dist", "finalweight"),
    },
)
def trip_distance_by_mode(run: RunData, config: Config) -> pl.DataFrame:
    return (
        run.trips.group_by("trip_mode")
        .agg(
            trip_count=pl.col("finalweight").sum(),
            average_distance=(
                (pl.col("od_dist") * pl.col("finalweight")).sum()
                / pl.col("finalweight").sum()
            ),
        )
        .with_columns(
            pl.col("trip_mode").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
            pl.col("average_distance").cast(pl.Float64),
        )
        .select("trip_mode", "trip_count", "average_distance")
    )
```

A successful builder must return the declared columns, in order, with the
declared data types. Before running the builder, the workflow checks for missing
declared input and returns the typed empty result if any input is unavailable.

Use `required_tables` only when a complete table or `skim` is enough to state
the requirement. For standard table dependencies, use `required_columns`,
which also requires the named runtime table. Specify `RunData` names such as
`hh`, `per`, `tours`, `trips`, `joint_participants`, and `land_use`, not
configuration IDs such as `households` or `persons`.

## Weighting

Builders aggregate `finalweight`. They do not select a weighting mode. The
summary workflow supplies the required prepared data for weighted and
unweighted builds.

## Adding A Summary Function

For an example with a calculation, contract test, catalog, and page connection,
use the [Summary Function Cookbook](44-summary-function-cookbook.md).

1. Put the builder in the domain module that owns the calculation.
2. Decorate it with `@summary(...)` and declare identity, ordered schema, and
   mechanical prerequisites.
3. Read prepared `RunData` tables, not raw files.
4. Aggregate `finalweight` and return one long-form `pl.DataFrame`.
5. Cast and select explicitly at the end of the builder.
6. Use `builder.empty()` only for domain-specific empty conditions that the
   declared prerequisites cannot express.
7. Add focused calculation and contract tests.
8. Add the summary ID to a page's required or optional summaries when needed.
9. Use `uv run python scripts/generate_wiki_catalogs.py`.

The catalog import rejects duplicate IDs. Standard summarize workflows build
every declaration with `build_by_default=True`, regardless of enabled page
requirements. Setting `build_by_default=False` registers the contract without
adding it to standard builds. Use this setting for an external table in the
public workflow and supply the table through `summary_table_map`. Referencing a
non-default ID in a page declaration does not start its builder.

## Summary CSV Boundary

Summary caches are the dashboard input. The visualizer stores registered tables
as CSV files for each run and weighting mode, and standard summarize workflows
write any that are missing or stale. Use `--skip-summary-cache-write` to prevent
these writes.

For a developer diagnostic, the following command ignores reusable summary
caches, rebuilds the configured summaries, and writes their CSV files and
manifests:

```bash
uv run activitysim-viz --config local_config.yaml --summarize --write-csvs
```

The command does not create a second export format or a separate calibration
directory. Cache storage uses the shared
`processor.summarize.csv_export.write_summary_csvs()` writer. Dashboard pages
load registered summaries through `self.data`. They do not open the CSV files
directly.

To register a new dashboard-ready table produced outside the visualizer, use
the [outside summary table recipe](41-data-extension-cookbook.md#worked-example-add-an-outside-summary-table).

## Segmentation

Segmentation runs in the summarize workflow. It builds the same declarations
for configured parts of the prepared data. A segment source can be a prepared
column or a CSV lookup. `segment.dashboard` controls dashboard visibility.

## Summary Catalog

The generated [24 - Summary Catalog](24-summary-catalog.md) lists each current
declaration, output file name, builder, schema, and requirement. Regenerate the
catalog after you change a summary declaration.

## Related Chapters

- [20 - Output Processor](20-output-processor.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [31 - Dashboard Pages](31-dashboard-pages.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
